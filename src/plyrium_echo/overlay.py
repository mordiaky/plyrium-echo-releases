"""Floating recording indicator — clean Wispr-style "Flow Bar".

A small, dark, fully-rounded pill near the bottom-center of the screen. During
recording it shows a minimal **audio visualizer**: a row of thin, rounded,
white bars that grow symmetrically from the centerline, driven by live mic
level, with a gentle gaussian taper (taller in the middle) and smooth motion.
While transcribing, the bars settle into a slow, even "breathing" shimmer. No
red dot, no chunky bars — understated and out of the way.

Threading: Tkinter owns the main thread. Background threads call
show()/hide()/transcribing()/set_level(), which enqueue onto a thread-safe queue
drained by a periodic ``after()`` tick. No-op if Tk is unavailable.
"""

from __future__ import annotations

import math
import queue
import sys

try:
    import tkinter as tk

    _TK_OK = True
except Exception:  # pragma: no cover
    _TK_OK = False

# ── geometry ──
_W, _H = 168, 44
_BOTTOM_GAP = 22
_PAD_X = 18          # horizontal inset for the bar field
_BARS = 22           # thin bars
_BAR_W = 3           # bar width (thin)
_GAP = None          # computed
_RADIUS = _H // 2    # full lozenge

# ── colors ──
_PILL = "#1b1d23"    # dark body
_CHROMA = "#010203"  # transparency key (rounded corners cut out)
_BAR = (236, 238, 245)   # near-white bars
_BAR_DIM = (120, 126, 140)  # idle/low bars
_REC_TINT = (255, 120, 120)  # very subtle warm tint at peaks (not a red dot)


class _Smoother:
    """Per-bar smoothing so motion is fluid, not jittery (spring-ish)."""

    def __init__(self, n):
        self.v = [0.0] * n

    def push(self, targets, rate=0.35):
        for i, t in enumerate(targets):
            self.v[i] += (t - self.v[i]) * rate
        return self.v


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(c):
    return "#%02x%02x%02x" % c


class Overlay:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled and _TK_OK
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._level = 0.0
        self._state = "hidden"
        self._visible = True   # tray can toggle the pill off without killing Tk
        self._phase = 0.0
        self._sm = _Smoother(_BARS)
        self._root = self._canvas = self._win = None

    # callable from any thread
    def show(self, label: str = "recording") -> None:
        self._q.put(("show", None))

    def transcribing(self) -> None:
        self._q.put(("state", "transcribing"))

    def hide(self) -> None:
        self._q.put(("hide", None))

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def set_visible(self, visible: bool) -> None:
        self._q.put(("visible", bool(visible)))

    def run_on_ui(self, fn) -> None:
        """Run ``fn`` on the Tk main thread (used to open windows from the tray)."""
        self._q.put(("call", fn))

    def stop(self) -> None:
        self._q.put(("quit", None))

    def run(self) -> None:
        if not self.enabled:
            return
        self._root = tk.Tk()
        self._root.withdraw()
        self._win = tk.Toplevel(self._root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        try:
            self._win.attributes("-alpha", 0.97)
            self._win.attributes("-transparentcolor", _CHROMA)
        except Exception:
            pass
        sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
        self._win.geometry(f"{_W}x{_H}+{(sw - _W)//2}+{sh - _H - _BOTTOM_GAP}")
        self._canvas = tk.Canvas(self._win, width=_W, height=_H, bg=_CHROMA,
                                 highlightthickness=0)
        self._canvas.pack()
        self._win.withdraw()
        self._root.after(16, self._tick)
        self._root.mainloop()

    def _place(self) -> None:
        try:
            x, y = self._win.winfo_pointerxy()
            if sys.platform == "win32":
                geo = _monitor_geometry_at(x, y)
                if geo is not None:
                    left, top, right, bottom = geo
                    self._win.geometry(
                        f"{_W}x{_H}+{left + ((right - left) - _W)//2}"
                        f"+{bottom - _H - _BOTTOM_GAP}"
                    )
                    return
        except Exception:
            pass
        sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
        self._win.geometry(f"{_W}x{_H}+{(sw - _W)//2}+{sh - _H - _BOTTOM_GAP}")

    def _tick(self) -> None:
        try:
            while True:
                cmd, val = self._q.get_nowait()
                if cmd == "show":
                    self._state = "recording"
                    self._phase = 0.0
                    self._place()
                    if self._visible:
                        self._win.deiconify()
                        self._win.lift()
                elif cmd == "state":
                    self._state = "transcribing"
                elif cmd == "hide":
                    self._state = "hidden"
                    self._win.withdraw()
                elif cmd == "visible":
                    self._visible = val
                    if not val:
                        self._win.withdraw()
                    elif self._state != "hidden":
                        self._win.deiconify()
                        self._win.lift()
                elif cmd == "call":
                    try:
                        val()
                    except Exception as exc:
                        print(f"[overlay] ui call failed: {exc}", flush=True)
                elif cmd == "quit":
                    self._root.destroy()
                    return
        except queue.Empty:
            pass
        if self._state != "hidden" and self._visible:
            self._draw()
        self._phase += 1
        self._root.after(16, self._tick)  # ~60fps

    # ── pill body with rounded ends (drawn, corners keyed transparent) ──
    def _pill(self):
        c, r = self._canvas, _RADIUS
        c.create_oval(0, 0, _H, _H, fill=_PILL, outline="")
        c.create_oval(_W - _H, 0, _W, _H, fill=_PILL, outline="")
        c.create_rectangle(r, 0, _W - r, _H, fill=_PILL, outline="")

    def _bar_targets(self):
        """Per-bar normalized heights (0..1) for the current frame."""
        n = _BARS
        mid = (n - 1) / 2
        lvl = self._level
        out = []
        for i in range(n):
            # gaussian taper across width: center bars allowed to be tallest
            d = (i - mid) / mid
            taper = math.exp(-(d * d) * 1.6)
            if self._state == "recording":
                signal = max(0.0, (lvl - 0.025) / 0.975)
                if signal <= 0.001:
                    h = 0.035
                else:
                    wob = 0.35 + 0.65 * math.sin(self._phase * 0.22 + i * 0.62) ** 2
                    h = (0.035 + 0.58 * signal * wob) * taper
            else:  # transcribing: slow even shimmer
                wob = 0.5 + 0.5 * math.sin(self._phase * 0.10 - i * 0.4)
                h = (0.18 + 0.20 * wob) * taper
            out.append(max(0.04, min(1.0, h)))
        return out

    def _draw(self):
        c = self._canvas
        c.delete("all")
        self._pill()

        heights = self._sm.push(self._bar_targets())
        field_w = _W - 2 * _PAD_X
        gap = (field_w - _BARS * _BAR_W) / (_BARS - 1)
        cy = _H / 2
        max_h = _H - 16  # leave padding top/bottom
        for i, hn in enumerate(heights):
            x = _PAD_X + i * (_BAR_W + gap)
            h = hn * max_h
            # bar color: white, with a faint warm tint only at high peaks
            tint = (hn - 0.7) / 0.3 if hn > 0.7 and self._state == "recording" else 0.0
            base = _BAR if self._state == "recording" else _BAR_DIM
            col = _hex(_lerp(base, _REC_TINT, max(0.0, min(1.0, tint)) * 0.5))
            y0, y1 = cy - h / 2, cy + h / 2
            # rounded-cap bar: a line with round joints reads as a thin pill
            c.create_line(x + _BAR_W / 2, y0, x + _BAR_W / 2, y1,
                          fill=col, width=_BAR_W, capstyle="round")

    # ── static preview (PIL) so the look can be reviewed without launching ──
    @staticmethod
    def save_preview(path, state="recording", level=0.7, seed=0):
        from PIL import Image, ImageDraw

        scale = 5
        W, H = _W * scale, _H * scale
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pill = tuple(int(_PILL[i:i+2], 16) for i in (1, 3, 5))
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=H / 2, fill=(*pill, 247))

        n = _BARS
        mid = (n - 1) / 2
        field_w = (_W - 2 * _PAD_X) * scale
        gap = (field_w - n * _BAR_W * scale) / (n - 1)
        cy = H / 2
        max_h = (_H - 16) * scale
        for i in range(n):
            dd = (i - mid) / mid
            taper = math.exp(-(dd * dd) * 1.6)
            wob = 0.5 + 0.5 * math.sin(seed + i * 0.55)
            if state == "recording":
                hn = (0.12 + 0.88 * level) * (0.45 + 0.55 * wob) * taper
                base = _BAR
            else:
                hn = (0.18 + 0.20 * wob) * taper
                base = _BAR_DIM
            hn = max(0.04, min(1.0, hn))
            x = (_PAD_X * scale) + i * (_BAR_W * scale + gap) + _BAR_W * scale / 2
            h = hn * max_h
            tint = (hn - 0.7) / 0.3 if hn > 0.7 and state == "recording" else 0.0
            col = _lerp(base, _REC_TINT, max(0.0, min(1.0, tint)) * 0.5)
            r = _BAR_W * scale / 2
            d.rounded_rectangle([x - r, cy - h / 2, x + r, cy + h / 2],
                                radius=r, fill=(*col, 255))
        img.resize((_W, _H), Image.LANCZOS).save(path)


def _monitor_geometry_at(x: int, y: int):
    import ctypes
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    monitor = ctypes.windll.user32.MonitorFromPoint(
        wintypes.POINT(x, y), 2
    )
    if not monitor:
        return None
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


class NullOverlay:
    def show(self, label: str = "recording") -> None: ...
    def transcribing(self) -> None: ...
    def hide(self) -> None: ...
    def set_level(self, level: float) -> None: ...
    def set_visible(self, visible: bool) -> None: ...
    def run_on_ui(self, fn) -> None: ...
    def stop(self) -> None: ...
    def run(self) -> None: ...
