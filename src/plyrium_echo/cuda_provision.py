"""On-demand GPU acceleration — fetch the NVIDIA CUDA libraries once.

The slim installer omits ~1.9 GB of CUDA libs (cuBLAS, cuDNN, NVRTC) so the
download stays small and CPU/AMD/Intel users never pay for them. When an NVIDIA
GPU is present and the user opts in, we download the official ``nvidia-*-cu12``
wheels from PyPI (they're just zip files), extract the DLLs into the user data
dir, and add that dir to the DLL search path. No admin rights, nothing written
to the read-only install dir, and it only happens once.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

from . import paths

# Pinned to versions verified with this CTranslate2 build. What matters is the
# SONAME major: cublas64_12 / cudnn*64_9 / nvrtc64_120. Bump if CTranslate2's
# CUDA major changes.
_WHEELS = {
    "nvidia-cublas-cu12": "12.9.2.10",
    "nvidia-cudnn-cu12": "9.22.0.52",
    "nvidia-cuda-nvrtc-cu12": "12.9.86",
}
_MARKER = "cublas64_12.dll"   # its presence means "provisioned"


def cuda_dir() -> Path:
    d = paths.data_dir() / "cuda"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_provisioned() -> bool:
    return (cuda_dir() / _MARKER).exists()


def activate() -> None:
    """Make provisioned DLLs loadable by CTranslate2 (call before a cuda load)."""
    d = paths.data_dir() / "cuda"
    if not d.exists():
        return
    try:
        os.add_dll_directory(str(d))
    except Exception:
        pass
    if str(d) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def _wheel_url(pkg: str, ver: str) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/{ver}/json",
                                timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    for f in data.get("urls", []):
        if f.get("filename", "").endswith("win_amd64.whl"):
            return f["url"]
    raise RuntimeError(f"no win_amd64 wheel for {pkg}=={ver}")


def _download(url: str, dst: Path, progress, label: str) -> None:
    with urllib.request.urlopen(url, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with open(dst, "wb") as f:
            while True:
                chunk = r.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(f"Downloading {label} — {done * 100 // total}%")


def _extract_dlls(whl: Path, dest: Path) -> int:
    n = 0
    with zipfile.ZipFile(whl) as z:
        for m in z.namelist():
            norm = m.replace("\\", "/")
            if norm.lower().endswith(".dll") and "/bin/" in norm:
                name = norm.rsplit("/", 1)[-1]
                with z.open(m) as src, open(dest / name, "wb") as out:
                    shutil.copyfileobj(src, out)
                n += 1
    return n


def provision(progress=None) -> bool:
    """Download + install the CUDA libraries. Returns True on success.

    ``progress`` (optional) is called with short human-readable status strings.
    """
    d = cuda_dir()
    tmp = d / "_dl"
    tmp.mkdir(exist_ok=True)
    try:
        for pkg, ver in _WHEELS.items():
            if progress:
                progress(f"Resolving {pkg} …")
            url = _wheel_url(pkg, ver)
            whl = tmp / f"{pkg}.whl"
            _download(url, whl, progress, pkg)
            if progress:
                progress(f"Installing {pkg} …")
            _extract_dlls(whl, d)
            try:
                whl.unlink()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as exc:
        if progress:
            progress(f"GPU setup failed: {exc}")
        return False
    activate()
    ok = is_provisioned()
    if progress:
        progress("GPU acceleration ready." if ok else "GPU setup incomplete.")
    return ok
