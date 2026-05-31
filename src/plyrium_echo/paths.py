"""Where Plyrium Echo keeps user-writable data (config, models, logs).

A distributed app is typically installed under ``C:\\Program Files`` — which is
read-only for normal users. So when frozen we put config + downloaded models
under ``%LOCALAPPDATA%\\Plyrium Echo``. In a dev checkout we keep using the
project root, so nothing changes for development.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Plyrium Echo"


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def data_dir() -> Path:
    """User-writable root for config/models/logs."""
    if _frozen():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        d = Path(base) / APP_DIR_NAME
    else:
        d = Path(__file__).resolve().parents[2]  # project root in dev
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def bundled_roots() -> list[Path]:
    """Read-only locations shipped inside the exe (PyInstaller bundle / exe dir)."""
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if _frozen():
        roots.append(Path(sys.executable).parent)
    return roots
