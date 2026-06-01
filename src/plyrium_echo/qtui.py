"""Qt UI controller - owns the QApplication, the recording overlay, and the
main window. Replaces the Tkinter stack.

Threading model:
  - Qt's QApplication.exec() owns the MAIN thread (run.py calls QtController.run).
  - The tray (pystray) runs on its own thread (run_detached).
  - The hotkey listener runs on its own thread.
Tray/hotkey callbacks therefore reach Qt from OTHER threads, so every UI
operation is marshaled onto the Qt main thread via Qt signals (queued
connections). That's why ``_Bridge`` exists: the app calls plain methods, the
signals hop the call onto the GUI thread safely.

The ``overlay`` attribute is a drop-in for the old Tk overlay: it implements
show/hide/transcribing/set_level/set_visible/stop, so app.py is unchanged.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QLinearGradient, QIcon
from PySide6.QtWidgets import QApplication, QWidget

# brand signal gradient
CYAN, BLUE, VIOLET = "#00D4FF", "#5B7CFF", "#8B5CF6"
PILL_BG = "#0b0d12"
APP_USER_MODEL_ID = "Plyrium.Echo.Desktop"
FLOWBAR_BOTTOM_GAP = 22


def _asset_path(*parts: str) -> Path:
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).parent)
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        p = root.joinpath(*parts)
        if p.exists():
            return p
    return roots[-1].joinpath(*parts)


def _install_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class FlowBar(QWidget):
    """The recording pill: thin gradient waveform bars on a dark rounded pill,
    bottom-center, frameless + always on top. Driven by live mic level."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)  # Tool = no taskbar entry
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._w, self._h = 176, 46
        self._bars = 22
        self.resize(self._w, self._h)
        self._level = 0.0
        self._state = "hidden"       # hidden | recording | transcribing
        self._phase = 0.0
        self._smooth = [0.0] * self._bars
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._place()

    def _place(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self._w // 2,
            screen.bottom() - self._h - FLOWBAR_BOTTOM_GAP,
        )

    def start(self, state="recording"):
        self._state = state
        self._place()
        self.show()
        self.raise_()
        if not self._timer.isActive():
            self._timer.start(16)  # ~60fps

    def to_transcribing(self):
        self._state = "transcribing"

    def stop_show(self):
        self._state = "hidden"
        self._timer.stop()
        self.hide()

    def set_level(self, lvl):
        self._level = max(0.0, min(1.0, lvl))

    def _tick(self):
        self._phase += 1
        self.update()

    def paintEvent(self, e):
        if self._state == "hidden":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, h / 2, h / 2)
        p.fillPath(path, QColor(PILL_BG))
        p.setPen(QPen(QColor(91, 124, 255, 70), 1))
        p.drawPath(path)

        n = self._bars
        mid = (n - 1) / 2
        pad = 20
        field = w - 2 * pad
        gap = field / (n - 1)
        cy = h / 2
        maxh = h - 18
        g = QLinearGradient(pad, 0, w - pad, 0)
        g.setColorAt(0, QColor(CYAN)); g.setColorAt(.5, QColor(BLUE)); g.setColorAt(1, QColor(VIOLET))
        pen = QPen(QBrush(g), 3); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for i in range(n):
            d = (i - mid) / mid
            taper = math.exp(-(d * d) * 1.6)
            if self._state == "recording":
                wob = 0.5 + 0.5 * math.sin(self._phase * 0.18 + i * 0.55)
                target = (0.12 + 0.88 * self._level) * (0.45 + 0.55 * wob) * taper
            else:  # transcribing shimmer
                wob = 0.5 + 0.5 * math.sin(self._phase * 0.10 - i * 0.4)
                target = (0.18 + 0.20 * wob) * taper
            self._smooth[i] += (target - self._smooth[i]) * 0.35
            bh = max(0.05, min(1.0, self._smooth[i])) * maxh
            x = pad + i * gap
            p.drawLine(int(x), int(cy - bh / 2), int(x), int(cy + bh / 2))


class _Bridge(QObject):
    """Signals to marshal cross-thread calls onto the Qt GUI thread."""
    show_overlay = Signal(str)
    transcribing = Signal()
    hide_overlay = Signal()
    set_visible = Signal(bool)
    open_window = Signal()
    open_window_section = Signal(str)
    quit = Signal()


class _OverlayFacade:
    """Drop-in for the old Tk overlay (thread-safe via the bridge)."""
    def __init__(self, ctrl):
        self._c = ctrl
        self.enabled = True

    def show(self, label="recording"):
        if self._c._visible:
            self._c.bridge.show_overlay.emit(label)

    def transcribing(self):
        if self._c._visible:
            self._c.bridge.transcribing.emit()

    def hide(self):
        self._c.bridge.hide_overlay.emit()

    def set_level(self, lvl):
        # direct attr write is fine (read in GUI thread paint); no signal needed
        self._c.flow.set_level(lvl)

    def set_visible(self, visible):
        self._c.bridge.set_visible.emit(bool(visible))

    def stop(self):
        self._c.bridge.quit.emit()

    def run(self):  # compatibility no-op (Qt loop runs via controller)
        pass


class QtController:
    def __init__(self, app):
        self.app = app
        _install_windows_app_id()
        self.qapp = QApplication.instance() or QApplication([])
        self._app_icon = QIcon(str(_asset_path("assets", "echo.ico")))
        if self._app_icon.isNull():
            self._app_icon = QIcon(str(_asset_path("assets", "brand", "echo-app-icon.png")))
        if not self._app_icon.isNull():
            self.qapp.setWindowIcon(self._app_icon)
        self.qapp.setQuitOnLastWindowClosed(False)  # tray app; don't quit on close
        self.flow = FlowBar()
        self._visible = bool(getattr(app.cfg, "overlay", True))
        self._window = None
        self.bridge = _Bridge()
        self.bridge.show_overlay.connect(lambda s: self.flow.start(s))
        self.bridge.transcribing.connect(self.flow.to_transcribing)
        self.bridge.hide_overlay.connect(self.flow.stop_show)
        self.bridge.set_visible.connect(self._set_visible)
        self.bridge.open_window.connect(self._open_window)
        self.bridge.open_window_section.connect(self._open_window)
        self.bridge.quit.connect(self.qapp.quit)
        self.overlay = _OverlayFacade(self)

    def _set_visible(self, v):
        self._visible = v
        if not v:
            self.flow.stop_show()

    def _open_window(self, section: str = ""):
        from .qtwindow import MainWindow
        if self._window is not None:
            try:
                self._window.showNormal()
                self._window.raise_()
                self._window.activateWindow()
                if section:
                    self._window.show_section(section)
                return
            except Exception:
                self._window = None
        self._window = MainWindow(self.app)
        if not self._app_icon.isNull():
            self._window.setWindowIcon(self._app_icon)
        self.app._window = self._window
        if section:
            self._window.show_section(section)
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    # thread-safe entry points used by app.py
    def open_window(self):
        self.bridge.open_window.emit()

    def open_window_section(self, section: str):
        self.bridge.open_window_section.emit(section)

    def run(self):
        self.qapp.exec()
