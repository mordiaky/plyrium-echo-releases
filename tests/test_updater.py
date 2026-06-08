"""Unit tests for Echo updater helpers.

Run with: .venv\\Scripts\\python.exe tests\\test_updater.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo.updater import (  # noqa: E402
    _expected_sha256,
    is_newer_version,
    parse_version,
    platform_asset_name,
)

cases = []


def check(name, got, want):
    ok = got == want
    cases.append(ok)
    flag = "ok " if ok else "FAIL"
    print(f"[{flag}] {name}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")


check("parse v tag", parse_version("v1.0.4"), (1, 0, 4))
check("parse suffix", parse_version("1.2.0-beta.1"), (1, 2, 0, 1))
check("newer patch", is_newer_version("1.0.6", "1.0.5"), True)
check("same version", is_newer_version("v1.0.5", "1.0.5"), False)
check("older version", is_newer_version("1.0.4", "1.0.5"), False)
check("minor beats patch", is_newer_version("1.1.0", "1.0.99"), True)
check(
    "sha sidecar parse",
    _expected_sha256("abc " + "f" * 64 + "  Plyrium-Echo-Setup.exe"),
    "f" * 64,
)
check("windows asset", platform_asset_name("win32"), "Plyrium-Echo-Setup.exe")
check("macos asset", platform_asset_name("darwin"), "Plyrium-Echo-macOS.zip")
check("linux asset", platform_asset_name("linux"), "Plyrium-Echo-Linux.AppImage")
check("linux variant asset", platform_asset_name("linux2"), "Plyrium-Echo-Linux.AppImage")
check("unknown platform", platform_asset_name("freebsd13"), None)

passed = sum(cases)
total = len(cases)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
