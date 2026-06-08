"""In-app update support for Plyrium Echo.

The updater treats the install directory as replaceable and the data directory
as durable. Transcripts, licenses, downloaded models, and config live under
``paths.data_dir()`` and are never deleted by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__, paths

GITHUB_OWNER = "mordiaky"
GITHUB_REPO = "plyrium-echo-releases"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
USER_AGENT = f"PlyriumEcho/{__version__}"

ASSET_BY_PLATFORM = {
    "win32": "Plyrium-Echo-Setup.exe",
    "darwin": "Plyrium-Echo-macOS.zip",
    "linux": "Plyrium-Echo-Linux.AppImage",
}


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int = 0


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    published_at: str
    notes: str
    asset: ReleaseAsset | None
    checksum_asset: ReleaseAsset | None
    update_available: bool


def parse_version(value: str) -> tuple[int, ...]:
    """Return a comparable numeric version tuple from tags like ``v1.0.4``."""
    text = (value or "").strip().lower().lstrip("v")
    parts = re.findall(r"\d+", text)
    return tuple(int(p) for p in parts) if parts else (0,)


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    left = parse_version(candidate)
    right = parse_version(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def platform_asset_name(platform: str | None = None) -> str | None:
    platform = platform or sys.platform
    if platform.startswith("linux"):
        return ASSET_BY_PLATFORM["linux"]
    return ASSET_BY_PLATFORM.get(platform)


def _request_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def latest_release(current_version: str = __version__) -> ReleaseInfo:
    data = _request_json(LATEST_RELEASE_API)
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("v") or current_version
    wanted = platform_asset_name()
    assets = data.get("assets") or []

    asset = None
    checksum = None
    for item in assets:
        name = str(item.get("name") or "")
        url = str(item.get("browser_download_url") or "")
        size = int(item.get("size") or 0)
        if wanted and name == wanted:
            asset = ReleaseAsset(name=name, url=url, size=size)
        if wanted and name == f"{wanted}.sha256":
            checksum = ReleaseAsset(name=name, url=url, size=size)

    return ReleaseInfo(
        version=version,
        tag=tag,
        published_at=str(data.get("published_at") or ""),
        notes=str(data.get("body") or ""),
        asset=asset,
        checksum_asset=checksum,
        update_available=is_newer_version(version, current_version),
    )


def _download_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", errors="replace")


def _expected_sha256(checksum_text: str) -> str | None:
    match = re.search(r"\b[a-fA-F0-9]{64}\b", checksum_text or "")
    return match.group(0).lower() if match else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_release_asset(
    release: ReleaseInfo,
    progress=None,
) -> Path:
    if release.asset is None:
        raise RuntimeError("No update package is available for this platform yet.")

    out_dir = paths.data_dir() / "updates" / release.version
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / release.asset.name
    tmp = target.with_suffix(target.suffix + ".part")

    if progress:
        progress(f"Downloading Plyrium Echo {release.version}...")

    req = urllib.request.Request(release.asset.url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as res, tmp.open("wb") as f:
            total = int(res.headers.get("Content-Length") or release.asset.size or 0)
            done = 0
            last_pct = -1
            while True:
                chunk = res.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    pct = int(done * 100 / total)
                    if pct >= last_pct + 10 or pct == 100:
                        last_pct = pct
                        progress(f"Downloading update... {pct}%")
        tmp.replace(target)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise

    if release.checksum_asset is not None:
        if progress:
            progress("Verifying update...")
        expected = _expected_sha256(_download_text(release.checksum_asset.url))
        actual = _sha256(target)
        if expected and actual.lower() != expected:
            try:
                target.unlink()
            except OSError:
                pass
            raise RuntimeError("Downloaded update failed SHA-256 verification.")

    return target


def launch_installer(package: Path, release: ReleaseInfo) -> str:
    """Start the platform updater and return the user-facing next step."""
    package = package.resolve()
    if sys.platform == "win32":
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Automatic install is only available from the packaged app.")
        helper = package.with_name("apply-echo-update.ps1")
        exe = Path(sys.executable).resolve()
        helper.write_text(
            "\n".join(
                [
                    "param(",
                    "  [string]$Installer,",
                    "  [int]$AppPid,",
                    "  [string]$ExePath",
                    ")",
                    "$ErrorActionPreference = 'Stop'",
                    "try {",
                    "  if ($AppPid -gt 0) {",
                    "    $p = Get-Process -Id $AppPid -ErrorAction SilentlyContinue",
                    "    if ($p) { Wait-Process -Id $AppPid -Timeout 45 -ErrorAction SilentlyContinue }",
                    "  }",
                    "  Start-Process -FilePath $Installer -ArgumentList '/S' -Wait",
                    "  if (Test-Path -LiteralPath $ExePath) {",
                    "    Start-Process -FilePath $ExePath",
                    "  }",
                    "} catch {",
                    "  Add-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'Plyrium Echo\\update-error.log') -Value $_",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
                "-Installer",
                str(package),
                "-AppPid",
                str(os.getpid()),
                "-ExePath",
                str(exe),
            ],
            close_fds=True,
            creationflags=creationflags,
        )
        return "Echo will close, update in place, and reopen automatically."

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(package.parent)])
        return (
            "The macOS update package was downloaded. For the smoothest update, "
            "run: brew upgrade --cask mordiaky/plyrium-forge/plyrium-echo"
        )

    subprocess.Popen(["xdg-open", str(package.parent)])
    return "The Linux update package was downloaded. Replace the current app with the new package when ready."
