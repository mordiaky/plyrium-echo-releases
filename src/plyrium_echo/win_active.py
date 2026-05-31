"""Foreground-application awareness (Windows, ctypes only).

Wispr Flow adapts formatting to the app you're typing into — most visibly by
dropping the trailing period in chat apps. ``foreground_app()`` returns the
lowercased executable name of the window that currently has focus (e.g.
``"slack.exe"``) so the formatter can do the same. Pure ctypes; no extra deps.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

_CHAT_APPS = {
    "slack.exe", "discord.exe", "teams.exe", "ms-teams.exe", "whatsapp.exe",
    "telegram.exe", "signal.exe", "messenger.exe", "skype.exe",
}

try:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _AVAILABLE = True
except Exception:  # pragma: no cover - non-Windows
    _AVAILABLE = False

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def foreground_app() -> str:
    """Return the focused window's exe name (lowercased), or '' if unknown."""
    if not _AVAILABLE:
        return ""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(len(buf))
            ok = _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            path = buf.value
        finally:
            _kernel32.CloseHandle(h)
        return path.rsplit("\\", 1)[-1].lower()
    except Exception:
        return ""


def is_chat_app() -> bool:
    """True when the focused app is a casual chat app (drop trailing periods)."""
    return foreground_app() in _CHAT_APPS
