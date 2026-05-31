"""Plyrium Echo app icon - sourced from the official brand art.

Joshua's brand kit (assets/brand/) is the source of truth:
  - echo-app-icon.png : the rounded-square app icon (exe / installer / shortcut)
  - echo-mark.png     : the bare waveform mark (tray, window header)

The tray icon is the mark with a small state dot in the corner so
idle/recording/transcribing/paused reads at a glance without recoloring the
art. Everything loads from the bundled assets; if an asset is somehow missing
it falls back to a simple drawn mark so the app never crashes over an icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# State dot colors (brand palette).
_ACCENTS = {
    "app": (0, 212, 255),            # cyan
    "idle": (0, 230, 118),           # local-green (ready)
    "recording": (255, 106, 0),      # forge-orange
    "transcribing": (139, 92, 246),  # signal-violet
    "paused": (111, 122, 145),       # muted
}


def _brand_dir() -> Path:
    """Locate assets/brand whether running from source or frozen."""
    roots = []
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        roots.append(Path(mei) / "assets" / "brand")
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).parent / "assets" / "brand")
    roots.append(Path(__file__).resolve().parents[2] / "assets" / "brand")
    for r in roots:
        if r.exists():
            return r
    return roots[-1]


def _load(name: str) -> Image.Image | None:
    p = _brand_dir() / name
    try:
        return Image.open(p).convert("RGBA") if p.exists() else None
    except Exception:
        return None


def _fallback(size: int, accent=(0, 212, 255)) -> Image.Image:
    """Drawn mark used only if the brand PNG can't be loaded."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = size / 2
    d.ellipse([size * 0.1, size * 0.1, size * 0.9, size * 0.9],
              outline=(91, 124, 255, 200), width=max(2, size // 24))
    d.ellipse([c - size * 0.07, c - size * 0.07, c + size * 0.07, c + size * 0.07],
              fill=(*accent, 255))
    return img


def app_image(size: int = 256) -> Image.Image:
    img = _load("echo-app-icon.png") or _fallback(size)
    return img.resize((size, size), Image.LANCZOS)


def mark_image(size: int = 256) -> Image.Image:
    img = _load("echo-mark.png") or _fallback(size)
    return img.resize((size, size), Image.LANCZOS)


def tray_image(state: str = "idle") -> Image.Image:
    """The mark + a small state dot (bottom-right) so state reads in the tray."""
    size = 64
    base = mark_image(size).copy()
    if state and state != "app":
        d = ImageDraw.Draw(base)
        acc = _ACCENTS.get(state, _ACCENTS["idle"])
        r = size * 0.16
        cx, cy = size - r - 2, size - r - 2
        # dark halo so the dot pops against the mark
        d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(6, 6, 8, 255))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*acc, 255))
    return base


def export_ico(path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base = app_image(256)
    base.save(path, format="ICO",
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                     (128, 128), (256, 256)])
    return path


# Back-compat shim (older callers referenced set_palette); now a no-op.
def set_palette(name: str) -> None:  # pragma: no cover
    pass


if __name__ == "__main__":
    here = Path(__file__).resolve().parents[2]
    assets = here / "assets"
    assets.mkdir(exist_ok=True)
    export_ico(assets / "echo.ico")
    for s in ("idle", "recording", "transcribing", "paused"):
        tray_image(s).save(assets / f"tray_{s}.png")
    print("wrote", assets)
