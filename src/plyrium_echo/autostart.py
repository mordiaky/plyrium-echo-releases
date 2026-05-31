"""Start-with-Windows toggle via the per-user Run registry key.

Uses ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` — no admin
rights needed, applies only to the current user. Safe no-op off Windows.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None  # type: ignore

_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NAME = "PlyriumEcho"


def _launch_cmd() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    # Dev: run the script with the same interpreter (pythonw if available).
    root = Path(__file__).resolve().parents[2]
    return f'"{sys.executable}" "{root / "run.py"}"'


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN) as k:
            val, _ = winreg.QueryValueEx(k, _NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_enabled(on: bool) -> bool:
    """Enable/disable autostart. Returns the resulting state (best-effort)."""
    if winreg is None:
        return False
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN) as k:
            if on:
                winreg.SetValueEx(k, _NAME, 0, winreg.REG_SZ, _launch_cmd())
            else:
                try:
                    winreg.DeleteValue(k, _NAME)
                except FileNotFoundError:
                    pass
        return on
    except OSError:
        return is_enabled()
