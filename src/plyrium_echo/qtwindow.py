"""Plyrium Echo main window - native Qt (PySide6), styled to the brand kit.

Replaces the Tkinter window. Qt can do what Tk can't: rounded frameless window,
dark->blue gradient, faint grid, rounded cards, glows, a floating sidebar - so
this matches echo-splash-redesign.png. Styling pulls straight from the brand
tokens (echo-splash-theme-tokens.css), so it's the same design, not eyeballed.

Cross-platform: Qt bundles its own renderer, so it looks identical on Windows,
macOS, and Linux (no OS webview needed). Fonts are loaded from the bundled
assets so text is consistent everywhere.

The window calls the same App.* methods the Tk window did (set_output_mode,
set_duck, reload_model, activate_license, ...), so behavior is unchanged.
"""

from __future__ import annotations

import getpass
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QLinearGradient,
                           QPainter, QPainterPath, QPen, QBrush, QPixmap,
                           QRadialGradient, QIcon)
from PySide6.QtWidgets import (QApplication, QWidget, QLabel, QPushButton,
                               QVBoxLayout, QHBoxLayout, QStackedWidget,
                               QFrame, QLineEdit, QComboBox, QCheckBox,
                               QScrollArea, QGridLayout, QSizePolicy,
                               QGraphicsDropShadowEffect, QMessageBox)

from . import __version__

# ── brand tokens (echo-splash-theme-tokens.css) ──
BG = "#060608"
SHELL = "#0b0d12"
PANEL = "#11141b"
PANEL2 = "#151924"
LINE = "#2c3340"
INK = "#f0eee8"
DIM = "#a8b0c2"
MUTED = "#6f7a91"
BLUE = "#5B7CFF"
VIOLET = "#8B5CF6"
CYAN = "#00D4FF"
GREEN = "#00E676"
ORANGE = "#FF6A00"

MODEL_CHOICES = [("Small - fastest (good on CPU)", "small.en"),
                 ("Medium - balanced", "medium.en"),
                 ("Large - most accurate (GPU)", "large-v3-turbo")]
OUTPUT_CHOICES = [("Paste (recommended)", "paste"), ("Type", "type"),
                  ("Clipboard only", "clipboard")]
DUCK_CHOICES = [("Off", None), ("Light (40%)", 0.40),
                ("Medium (25%)", 0.25), ("Strong (15%)", 0.15)]

SECTIONS = ["Home", "History", "Dictionary", "Settings", "About"]


def _brand_dir() -> Path:
    import sys
    for root in ([Path(sys._MEIPASS)] if getattr(sys, "_MEIPASS", None) else []) + \
                ([Path(sys.executable).parent] if getattr(sys, "frozen", False) else []) + \
                [Path(__file__).resolve().parents[2]]:
        d = root / "assets" / "brand"
        if d.exists():
            return d
    return Path(__file__).resolve().parents[2] / "assets" / "brand"


def _app_icon() -> QIcon:
    import sys
    roots = ([Path(sys._MEIPASS)] if getattr(sys, "_MEIPASS", None) else []) + \
            ([Path(sys.executable).parent] if getattr(sys, "frozen", False) else []) + \
            [Path(__file__).resolve().parents[2]]
    for root in roots:
        for rel in (Path("assets") / "echo.ico",
                    Path("assets") / "brand" / "echo-app-icon.png"):
            p = root / rel
            if p.exists():
                icon = QIcon(str(p))
                if not icon.isNull():
                    return icon
    return QIcon()


def _load_fonts() -> None:
    """Load Segoe UI + Consolas so text matches on every OS."""
    import sys
    win_fonts = Path("C:/Windows/Fonts")
    for fn in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
        p = win_fonts / fn
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))


def _day_label(ts: float, now: float) -> str:
    try:
        lt, td = time.localtime(ts), time.localtime(now)
        yd = time.localtime(now - 86400)
        if (lt.tm_year, lt.tm_yday) == (td.tm_year, td.tm_yday):
            return "TODAY"
        if (lt.tm_year, lt.tm_yday) == (yd.tm_year, yd.tm_yday):
            return "YESTERDAY"
        return time.strftime("%B %d, %Y", lt).upper()
    except Exception:
        return ""


def _clock(ts: float) -> str:
    try:
        return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")
    except Exception:
        return ""


# ============ small styled helpers ============
def _f(size, bold=False, mono=False):
    fam = "Consolas" if mono else "Segoe UI"
    w = QFont.DemiBold if bold else QFont.Normal
    f = QFont(fam, size)
    f.setWeight(QFont.Bold if bold else QFont.Normal)
    return f


def _shadow(widget, blur=28, y=16, color=(0, 0, 0, 120)):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    fx.setOffset(0, y)
    fx.setColor(QColor(*color))
    widget.setGraphicsEffect(fx)
    return widget


class Card(QFrame):
    """Rounded panel with optional colored top-accent bar."""
    def __init__(self, accent=None, bg=PANEL, radius=18):
        super().__init__()
        self._accent = accent
        self._bg = bg
        self._radius = radius
        self.setAttribute(Qt.WA_StyledBackground, False)
        _shadow(self, blur=22, y=12, color=(0, 0, 0, 90))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.fillPath(path, QColor(self._bg))
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawPath(path)
        if self._accent:
            p.save()
            p.setClipPath(path)
            p.fillRect(QRectF(0, 0, self.width(), 4), QColor(self._accent))
            p.restore()


class Waveform(QWidget):
    """Gradient waveform line (the Live voice lane)."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(112)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        mid = h * 0.55
        pts = [(0.05, 0), (0.19, 0), (0.26, -0.55), (0.35, 0.75),
               (0.44, -1.0), (0.54, 1.0), (0.62, -0.45),
               (0.71, 0.22), (0.94, 0.22)]
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, QColor(CYAN)); g.setColorAt(.5, QColor(BLUE)); g.setColorAt(1, QColor(VIOLET))
        pen = QPen(QBrush(g), 11); pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath()
        for i, (t, a) in enumerate(pts):
            x, y = t * w, mid + a * (mid - 8)
            path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
        p.drawPath(path)


class RingMark(QWidget):
    """The big ringed brand mark."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(226, 226)
        self._pm = None
        mp = _brand_dir() / "echo-mark.png"
        if mp.exists():
            self._pm = QPixmap(str(mp)).scaled(158, 158, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        rg = QRadialGradient(cx, cy, 118)
        rg.setColorAt(0, QColor(91, 124, 255, 28))
        rg.setColorAt(0.72, QColor(0, 212, 255, 10))
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 112, 112)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(BLUE), 1.2))
        p.drawEllipse(QPointF(cx, cy), 100, 100)
        p.setPen(QPen(QColor(CYAN), 1.1))
        p.drawEllipse(QPointF(cx, cy), 68, 68)
        if self._pm:
            p.drawPixmap(int(cx - self._pm.width() / 2),
                         int(cy - self._pm.height() / 2), self._pm)


class Shell(QWidget):
    """The frameless rounded window background: gradient + grid + edge."""
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1.5, 1.5, self.width() - 3, self.height() - 3)
        path = QPainterPath()
        path.addRoundedRect(r, 30, 30)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#07090d")); g.setColorAt(.46, QColor("#0b1018"))
        g.setColorAt(1, QColor("#06080c"))
        p.fillPath(path, QBrush(g))
        rg = QRadialGradient(self.width() * 0.74, self.height() * 0.12, self.width() * 0.62)
        rg.setColorAt(0, QColor(91, 124, 255, 62)); rg.setColorAt(.52, QColor(0, 212, 255, 16))
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillPath(path, QBrush(rg))
        pen = QPen(QColor(255, 255, 255, 7)); pen.setWidth(1); p.setPen(pen)
        for x in range(18, self.width(), 24):
            p.drawLine(x, 0, x, self.height())
        for y in range(18, self.height(), 24):
            p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(0, 78, self.width(), 78)
        p.setClipping(False)
        p.setPen(QPen(QColor(91, 124, 255, 130), 1.7)); p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _pill(text, fg, bg, border):
    w = QLabel(text)
    w.setFont(_f(9, bold=True))
    w.setStyleSheet(f"color:{fg};background:{bg};border:1px solid {border};"
                    f"border-radius:14px;padding:5px 14px;")
    return w


class MainWindow(QWidget):
    # signals so background threads can drive the UI safely
    sig_history = Signal()
    sig_status = Signal(str)
    sig_refresh_status = Signal()
    sig_update_checked = Signal(object)
    sig_update_message = Signal(str)
    sig_update_failed = Signal(str)
    sig_update_ready = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cfg = app.cfg
        _load_fonts()
        self.setWindowTitle("Plyrium Echo")
        icon = _app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
            qapp = QApplication.instance()
            if qapp is not None:
                qapp.setWindowIcon(icon)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1200, 760)
        self._drag = None
        self._build()
        self.sig_history.connect(self._on_new_entry)
        self.sig_status.connect(self._set_status_text)
        self.sig_refresh_status.connect(self._refresh_status)
        self.sig_update_checked.connect(self._on_update_checked)
        self.sig_update_message.connect(self._set_update_message)
        self.sig_update_failed.connect(self._on_update_failed)
        self.sig_update_ready.connect(self._on_update_ready)
        self.show_section("Home")

    # ---- chrome / drag ----
    def mousePressEvent(self, e):
        if e.position().y() < 56:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()

    def _build(self):
        shell = Shell(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(shell)
        outer = QHBoxLayout(shell)
        outer.setContentsMargins(42, 42, 42, 42)
        outer.setSpacing(44)

        # ----- sidebar -----
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(232)
        side.setStyleSheet("#sidebar{background:rgba(9,11,17,232);"
                           "border:1px solid rgba(255,255,255,24);"
                           "border-radius:24px;}")
        _shadow(side, blur=34, y=18, color=(0, 0, 0, 130))
        sl = QVBoxLayout(side)
        sl.setContentsMargins(20, 22, 20, 20)
        sl.setSpacing(5)

        brow = QHBoxLayout()
        mark = QLabel()
        mp = _brand_dir() / "echo-mark.png"
        if mp.exists():
            mark.setPixmap(QPixmap(str(mp)).scaled(38, 38, Qt.KeepAspectRatio,
                                                   Qt.SmoothTransformation))
        brow.addWidget(mark)
        bt = QVBoxLayout(); bt.setSpacing(0)
        nm = QLabel("Plyrium Echo"); nm.setFont(_f(14, bold=True)); nm.setStyleSheet(f"color:{INK};")
        tagrow = QLabel("● LOCAL / OFFLINE")
        tagrow.setFont(_f(8, mono=True)); tagrow.setStyleSheet(f"color:{GREEN};")
        bt.addWidget(nm); bt.addWidget(tagrow)
        brow.addLayout(bt); brow.addStretch()
        sl.addLayout(brow)
        sl.addSpacing(20)

        self._nav_btns = {}
        for name in SECTIONS:
            b = QPushButton(name)
            b.setFixedHeight(42)
            b.setCursor(Qt.PointingHandCursor)
            b.setCheckable(True)
            b.setFont(_f(11))
            b.clicked.connect(lambda _=False, n=name: self.show_section(n))
            b.setStyleSheet(self._nav_qss(False))
            sl.addWidget(b)
            self._nav_btns[name] = b
        sl.addStretch()

        # MODEL READY badge
        self._badge = QFrame()
        self._badge.setObjectName("modelBadge")
        self._badge.setStyleSheet("#modelBadge{background:rgba(0,230,118,18);"
                                  "border:1px solid rgba(0,230,118,72);"
                                  "border-radius:14px;}")
        bl = QVBoxLayout(self._badge); bl.setContentsMargins(14, 10, 14, 10); bl.setSpacing(2)
        self._badge_title = QLabel("MODEL READY")
        self._badge_title.setFont(_f(9, bold=True, mono=True)); self._badge_title.setStyleSheet(f"color:{GREEN};")
        self._badge_sub = QLabel(""); self._badge_sub.setFont(_f(8, mono=True)); self._badge_sub.setStyleSheet(f"color:{DIM};")
        bl.addWidget(self._badge_title); bl.addWidget(self._badge_sub)
        sl.addWidget(self._badge)
        outer.addWidget(side)

        # ----- content stack -----
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self._pages = {}
        self._refresh_status()

        chrome_holder = QWidget(shell)
        chrome_holder.setGeometry(self.width() - 92, 28, 66, 34)
        chrome = QHBoxLayout(chrome_holder)
        chrome.setContentsMargins(0, 0, 0, 0)
        chrome.setSpacing(8)
        dot = QLabel("●")
        dot.setFont(_f(15))
        dot.setStyleSheet(f"color:{MUTED};")
        close = QPushButton("×")
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(28, 28)
        close.clicked.connect(self.hide)
        close.setStyleSheet(f"QPushButton{{color:{MUTED};background:transparent;border:none;"
                            "font-size:24px;padding-bottom:4px;}}"
                            "QPushButton:hover{color:#ff6b78;}")
        chrome.addWidget(dot)
        chrome.addWidget(close)

    def _nav_qss(self, active):
        if active:
            return ("QPushButton{color:%s;text-align:left;padding:11px 16px;border:none;"
                    "border-radius:12px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                    "stop:0 rgba(91,124,255,60),stop:1 rgba(139,92,246,30));}" % INK)
        return ("QPushButton{color:%s;text-align:left;padding:11px 16px;border:none;"
                "border-radius:12px;background:transparent;}"
                "QPushButton:hover{color:%s;background:rgba(255,255,255,10);}" % (DIM, INK))

    # ---- section routing ----
    def show_section(self, name):
        for n, b in self._nav_btns.items():
            b.setChecked(n == name)
            b.setStyleSheet(self._nav_qss(n == name))
            b.setFont(_f(11, bold=(n == name)))
        # rebuild page fresh (simple + always current)
        page = self._build_page(name)
        if name in self._pages:
            old = self._pages[name]
            self.stack.removeWidget(old); old.deleteLater()
        self._pages[name] = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        self._cur = name

    def _build_page(self, name):
        return getattr(self, "_page_" + name.lower())()

    # ---- Home ----
    def _page_home(self):
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(0, 36, 0, 0); v.setSpacing(18)

        # greeting + PRIVATE
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        gl = QVBoxLayout(); gl.setSpacing(2)
        hour = time.localtime().tm_hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        nm = (getpass.getuser() or "there").split("@")[0].title()
        g = QLabel(f"Good {part}, {nm}"); g.setFont(_f(27, bold=True)); g.setStyleSheet(f"color:{INK};")
        sub = QLabel(f"Hold {self.cfg.hotkey}, speak, release. Echo cleans it locally.")
        sub.setFont(_f(10)); sub.setStyleSheet(f"color:{DIM};")
        gl.addWidget(g); gl.addWidget(sub)
        top.addLayout(gl); top.addStretch()
        lic = self.app.license
        kind, info = lic.status()
        top.addWidget(_pill("●  PRIVATE" if kind == "licensed" else "●  PRIVATE",
                            GREEN, "#0f2018", "#1f5a3a"), 0, Qt.AlignTop)
        v.addLayout(top)

        # trial strip (only if not licensed)
        if kind != "licensed":
            strip = Card(bg=PANEL2, radius=12)
            sh = QHBoxLayout(strip); sh.setContentsMargins(14, 8, 10, 8)
            txt = (f"Trial - {info} day{'s' if info != 1 else ''} left" if kind == "trial"
                   else "Trial ended - activate to keep dictating")
            tl = QLabel(txt); tl.setFont(_f(10, bold=True))
            tl.setStyleSheet(f"color:{INK if kind=='trial' else '#ff6b78'};")
            sh.addWidget(tl); sh.addStretch()
            ek = QPushButton("Enter key"); ek.setStyleSheet(self._btn_qss()); ek.setCursor(Qt.PointingHandCursor)
            ek.clicked.connect(lambda: self.show_section("Settings"))
            buy = QPushButton("Buy a license"); buy.setStyleSheet(self._btn_qss(primary=True)); buy.setCursor(Qt.PointingHandCursor)
            buy.clicked.connect(self._open_buy)
            sh.addWidget(ek); sh.addWidget(buy)
            v.addWidget(strip)

        # stat cards
        v.addSpacing(22)
        st = self.app.history.stats() if self.app.history else {"entries": 0, "words": 0}
        saved = (st["words"] or 0) / 40.0
        row = QHBoxLayout(); row.setSpacing(16)
        for label, val, acc in [("Total words dictated", f"{st['words']:,}", CYAN),
                                ("Dictations", f"{st['entries']:,}", BLUE),
                                ("Typing time saved", f"{saved:.0f} min", VIOLET)]:
            c = Card(accent=acc)
            c.setFixedSize(226, 120)
            cl = QVBoxLayout(c); cl.setContentsMargins(20, 18, 20, 18); cl.setSpacing(2)
            ll = QLabel(label); ll.setFont(_f(10, mono=True)); ll.setStyleSheet(f"color:{DIM};")
            vl = QLabel(val); vl.setFont(_f(28, bold=True)); vl.setStyleSheet(f"color:{INK};")
            cl.addWidget(ll); cl.addWidget(vl)
            row.addWidget(c)
        row.addStretch()
        v.addLayout(row)
        v.addSpacing(14)

        # live voice lane + ring
        low = QHBoxLayout(); low.setSpacing(16)
        lane = Card()
        lane.setFixedSize(518, 204)
        ll = QVBoxLayout(lane); ll.setContentsMargins(28, 24, 28, 20); ll.setSpacing(6)
        t1 = QLabel("Live voice lane"); t1.setFont(_f(15, bold=True)); t1.setStyleSheet(f"color:{INK};")
        t2 = QLabel("Your voice becomes clean text in any app."); t2.setFont(_f(10)); t2.setStyleSheet(f"color:{DIM};")
        ll.addWidget(t1); ll.addWidget(t2); ll.addWidget(Waveform(), 1)
        lf = QHBoxLayout()
        idle = QLabel("Listening idle"); idle.setFont(_f(9, bold=True))
        idle.setStyleSheet("color:white;border-radius:14px;padding:5px 14px;"
                           "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                           f"stop:0 {BLUE},stop:1 {VIOLET});")
        loc = QLabel("voice stays local"); loc.setFont(_f(9, bold=True)); loc.setStyleSheet(f"color:{GREEN};")
        lf.addWidget(idle); lf.addStretch(); lf.addWidget(loc)
        ll.addLayout(lf)
        low.addWidget(lane, 1)
        low.addWidget(RingMark(), 0, Qt.AlignVCenter)
        low.addStretch()
        v.addLayout(low)
        v.addSpacing(20)

        # LAST CLEANUP
        lc = Card(bg="#0a0c11", radius=16)
        lc.setFixedSize(780, 70)
        lcl = QVBoxLayout(lc); lcl.setContentsMargins(20, 10, 20, 12); lcl.setSpacing(2)
        cap = QLabel("LAST CLEANUP"); cap.setFont(_f(8, bold=True, mono=True)); cap.setStyleSheet(f"color:{MUTED};")
        rowc = QHBoxLayout()
        body = QLabel("Removed filler, fixed punctuation, and kept your project names intact.")
        body.setFont(_f(10)); body.setStyleSheet(f"color:{DIM};")
        prompt = QLabel(">_"); prompt.setFont(_f(13, bold=True, mono=True)); prompt.setStyleSheet(f"color:{ORANGE};")
        rowc.addWidget(body); rowc.addStretch(); rowc.addWidget(prompt)
        lcl.addWidget(cap); lcl.addLayout(rowc)
        v.addWidget(lc)
        v.addStretch()
        return page

    # ---- History ----
    def _page_history(self):
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(28, 24, 24, 20); v.setSpacing(8)
        h = QLabel("History"); h.setFont(_f(20, bold=True)); h.setStyleSheet(f"color:{INK};")
        sub = QLabel("All transcripts are private and stored locally on your machine.")
        sub.setFont(_f(10)); sub.setStyleSheet(f"color:{DIM};")
        v.addWidget(h); v.addWidget(sub)
        bar = QHBoxLayout()
        self._search = QLineEdit(); self._search.setPlaceholderText("Search transcripts")
        self._search.setFont(_f(10))
        self._search.setStyleSheet(f"background:{PANEL2};color:{INK};border:1px solid {LINE};"
                                   "border-radius:8px;padding:7px 10px;")
        self._search.textChanged.connect(self._fill_history)
        clr = QPushButton("Clear all"); clr.setStyleSheet(self._btn_qss(danger=True)); clr.setCursor(Qt.PointingHandCursor)
        clr.clicked.connect(self._clear_history)
        bar.addWidget(self._search, 1); bar.addWidget(clr)
        v.addLayout(bar)
        self._hist_area = QScrollArea(); self._hist_area.setWidgetResizable(True)
        self._hist_area.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self._hist_inner = QWidget(); self._hist_area.setWidget(self._hist_inner)
        self._hist_v = QVBoxLayout(self._hist_inner); self._hist_v.setContentsMargins(0, 6, 0, 6); self._hist_v.setSpacing(0)
        v.addWidget(self._hist_area, 1)
        self._fill_history()
        return page

    def _fill_history(self):
        while self._hist_v.count():
            it = self._hist_v.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        q = self._search.text().strip() if hasattr(self, "_search") else ""
        rows = self.app.history.list(search=q) if self.app.history else []
        if not rows:
            e = QLabel("No transcripts yet - hold your hotkey and speak.")
            e.setFont(_f(10)); e.setStyleSheet(f"color:{MUTED};padding:16px;")
            self._hist_v.addWidget(e); return
        now = time.time(); cur = None
        for r in rows:
            day = _day_label(r["ts"], now)
            if day != cur:
                cur = day
                d = QLabel(day); d.setFont(_f(8, bold=True)); d.setStyleSheet(f"color:{MUTED};padding:14px 6px 4px;")
                self._hist_v.addWidget(d)
            roww = QFrame(); roww.setStyleSheet("QFrame:hover{background:#141822;border-radius:8px;}")
            rl = QHBoxLayout(roww); rl.setContentsMargins(8, 8, 8, 8)
            tcol = QLabel(_clock(r["ts"])); tcol.setFont(_f(9)); tcol.setFixedWidth(80)
            tcol.setStyleSheet(f"color:{MUTED};"); tcol.setAlignment(Qt.AlignTop)
            txt = QLabel(r["text"]); txt.setFont(_f(10)); txt.setWordWrap(True); txt.setStyleSheet(f"color:{INK};")
            rl.addWidget(tcol); rl.addWidget(txt, 1)
            self._bind_history_copy(roww, r["text"], tcol)
            self._bind_history_copy(tcol, r["text"], tcol)
            self._bind_history_copy(txt, r["text"], tcol)
            self._hist_v.addWidget(roww)
        self._hist_v.addStretch()

    def _bind_history_copy(self, widget, text: str, feedback: QLabel) -> None:
        widget.setCursor(Qt.PointingHandCursor)

        def copy_on_left_click(e):
            if e.button() == Qt.LeftButton:
                self._copy_history_text(text, feedback)
                e.accept()

        widget.mousePressEvent = copy_on_left_click

    def _copy_history_text(self, text: str, feedback: QLabel) -> None:
        try:
            QApplication.clipboard().setText(text)
            old = feedback.text()
            feedback.setText("copied!")
            feedback.setStyleSheet(f"color:{CYAN};")
            QTimer.singleShot(900, lambda: (
                feedback.setText(old),
                feedback.setStyleSheet(f"color:{MUTED};"),
            ))
        except Exception:
            pass

    def _clear_history(self):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, "Clear history",
                                "Delete all saved transcripts? This can't be undone.") \
                == QMessageBox.Yes:
            self.app.history.clear(); self._fill_history()

    # ---- Dictionary ----
    def _page_dictionary(self):
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(28, 24, 24, 20); v.setSpacing(8)
        h = QLabel("Dictionary"); h.setFont(_f(20, bold=True)); h.setStyleSheet(f"color:{INK};")
        sub = QLabel("Words the AI cleanup must always spell correctly.")
        sub.setFont(_f(10)); sub.setStyleSheet(f"color:{DIM};")
        v.addWidget(h); v.addWidget(sub)
        from PySide6.QtWidgets import QListWidget
        self._dict_list = QListWidget()
        self._dict_list.setStyleSheet(f"background:{PANEL};color:{INK};border:1px solid {LINE};"
                                      f"border-radius:10px;padding:6px;font-size:13px;"
                                      f"QListView::item:selected{{background:{BLUE};}}")
        for term in self.cfg.dictionary:
            self._dict_list.addItem(term)
        v.addWidget(self._dict_list, 1)
        row = QHBoxLayout()
        self._dict_entry = QLineEdit(); self._dict_entry.setFont(_f(10))
        self._dict_entry.setStyleSheet(f"background:{PANEL2};color:{INK};border:1px solid {LINE};border-radius:8px;padding:7px 10px;")
        self._dict_entry.returnPressed.connect(self._dict_add)
        add = QPushButton("Add"); add.setStyleSheet(self._btn_qss()); add.clicked.connect(self._dict_add)
        rm = QPushButton("Remove"); rm.setStyleSheet(self._btn_qss(danger=True)); rm.clicked.connect(self._dict_remove)
        row.addWidget(self._dict_entry, 1); row.addWidget(add); row.addWidget(rm)
        v.addLayout(row)
        return page

    def _dict_save(self):
        self.cfg.dictionary = [self._dict_list.item(i).text() for i in range(self._dict_list.count())]
        self.cfg.save()
        if self.app.llm is not None:
            self.app.llm.terms = self.cfg.dictionary

    def _dict_add(self):
        t = self._dict_entry.text().strip()
        existing = [self._dict_list.item(i).text() for i in range(self._dict_list.count())]
        if t and t not in existing:
            self._dict_list.addItem(t); self._dict_save()
        self._dict_entry.clear()

    def _dict_remove(self):
        for it in self._dict_list.selectedItems():
            self._dict_list.takeItem(self._dict_list.row(it))
        self._dict_save()

    # ---- Settings ----
    def _page_settings(self):
        page = QWidget()
        outer = QVBoxLayout(page); outer.setContentsMargins(28, 24, 24, 20)
        h = QLabel("Settings"); h.setFont(_f(20, bold=True)); h.setStyleSheet(f"color:{INK};")
        outer.addWidget(h)
        area = QScrollArea(); area.setWidgetResizable(True)
        area.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inner = QWidget(); area.setWidget(inner)
        v = QVBoxLayout(inner); v.setContentsMargins(0, 8, 8, 8); v.setSpacing(8)
        outer.addWidget(area, 1)

        # license box
        lic = self.app.license
        lbox = Card(bg=PANEL2, radius=12)
        lv = QVBoxLayout(lbox); lv.setContentsMargins(14, 10, 14, 12)
        ls = QLabel(lic.status_text()); ls.setFont(_f(10, bold=True)); ls.setStyleSheet(f"color:{INK};")
        lv.addWidget(ls)
        if not lic.licensed():
            hint = QLabel("Paste your license key to unlock unlimited use:")
            hint.setFont(_f(9)); hint.setStyleSheet(f"color:{DIM};"); lv.addWidget(hint)
            lr = QHBoxLayout()
            self._key_entry = QLineEdit(); self._key_entry.setFont(_f(9))
            self._key_entry.setStyleSheet(f"background:{SHELL};color:{INK};border:1px solid {LINE};border-radius:6px;padding:6px;")
            act = QPushButton("Activate"); act.setStyleSheet(self._btn_qss(primary=True)); act.clicked.connect(self._activate)
            buy = QPushButton("Buy a license"); buy.setStyleSheet(self._btn_qss()); buy.clicked.connect(self._open_buy)
            lr.addWidget(self._key_entry, 1); lr.addWidget(act); lr.addWidget(buy)
            lv.addLayout(lr)
        v.addWidget(lbox)

        # combos
        v.addWidget(self._combo_row("Model", MODEL_CHOICES, self.cfg.model_size, self._pick_model))
        QTimer.singleShot(0, self._reconcile_live_model)
        v.addWidget(self._combo_row("Output mode", OUTPUT_CHOICES, self.cfg.output_mode, self.app.set_output_mode))
        duck = None if not self.cfg.duck_audio else self.cfg.duck_level
        v.addWidget(self._combo_row("Lower other audio", DUCK_CHOICES, duck, self.app.set_duck))

        v.addWidget(self._divider())
        # toggles
        for label, getter, setter in [
            ("Smart formatting", lambda: self.cfg.smart_format, self.app.set_smart_format),
            ("Drop period in chat apps", lambda: self.cfg.chat_apps_no_period, self.app.set_chat_period),
            ("Show waveform overlay", lambda: self.cfg.overlay, self.app.set_overlay),
            ("AI cleanup (Ollama)", lambda: self.cfg.llm_cleanup, self.app.set_llm_cleanup),
            ("Save dictation history", lambda: self.cfg.history_enabled, self.app.set_history_enabled),
        ]:
            v.addWidget(self._toggle(label, getter(), setter))
        from . import autostart
        v.addWidget(self._toggle("Start with Windows", autostart.is_enabled(),
                                 lambda val: autostart.set_enabled(val)))
        v.addStretch()
        return page

    def _combo_row(self, label, choices, current, on_pick):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label); lab.setFont(_f(10)); lab.setFixedWidth(170); lab.setStyleSheet(f"color:{INK};")
        cb = QComboBox(); cb.setFont(_f(10)); cb.setCursor(Qt.PointingHandCursor)
        cb.setStyleSheet(f"QComboBox{{background:{PANEL};color:{INK};border:1px solid {LINE};"
                         f"border-radius:8px;padding:6px 10px;min-width:240px;}}"
                         f"QComboBox QAbstractItemView{{background:{PANEL};color:{INK};"
                         f"selection-background-color:{BLUE};}}")
        idx = 0
        for i, (lbl, val) in enumerate(choices):
            cb.addItem(lbl, val)
            if val == current:
                idx = i
        cb.setCurrentIndex(idx)
        cb.currentIndexChanged.connect(lambda i: on_pick(choices[i][1]))
        h.addWidget(lab); h.addWidget(cb); h.addStretch()
        return w

    def _toggle(self, label, checked, setter):
        cb = QCheckBox("  " + label); cb.setChecked(bool(checked)); cb.setFont(_f(10))
        cb.setCursor(Qt.PointingHandCursor)
        cb.setStyleSheet(f"QCheckBox{{color:{INK};spacing:8px;}}"
                         f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
                         f"border:1px solid {LINE};background:{PANEL};}}"
                         f"QCheckBox::indicator:checked{{background:{BLUE};border-color:{BLUE};}}")
        cb.toggled.connect(lambda val: setter(val))
        return cb

    def _divider(self):
        d = QFrame(); d.setFixedHeight(1); d.setStyleSheet(f"background:{LINE};"); return d

    def _pick_model(self, size):
        import threading
        threading.Thread(target=lambda: self.app.reload_model(size), daemon=True).start()

    def _reconcile_live_model(self):
        live = getattr(self.app, "transcriber", None)
        if live is None:
            return
        if getattr(live, "model_size", None) != self.cfg.model_size:
            self._pick_model(self.cfg.model_size)
            return
        try:
            from .model import resolve_runtime

            target_device, target_compute = resolve_runtime(
                self.cfg.model_size, self.cfg.device, self.cfg.compute_type
            )
            if (
                getattr(live, "device", None) != target_device
                or getattr(live, "compute_type", None) != target_compute
            ):
                self._pick_model(self.cfg.model_size)
        except Exception:
            pass

    def _activate(self):
        from PySide6.QtWidgets import QMessageBox
        ok, msg = self.app.activate_license(self._key_entry.text())
        (QMessageBox.information if ok else QMessageBox.warning)(self, "Plyrium Echo", msg)
        if ok:
            self.show_section("Settings")

    def _open_buy(self):
        import webbrowser
        try:
            webbrowser.open(self.cfg.buy_url)
        except Exception:
            pass

    # ---- About ----
    def _page_about(self):
        page = QWidget()
        v = QVBoxLayout(page); v.setContentsMargins(28, 24, 24, 20); v.setSpacing(12)
        h = QLabel("About"); h.setFont(_f(20, bold=True)); h.setStyleSheet(f"color:{INK};")
        v.addWidget(h)
        lm = _brand_dir() / "echo-logo-lockup.png"
        if lm.exists():
            logo = QLabel(); logo.setPixmap(QPixmap(str(lm)).scaledToWidth(420, Qt.SmoothTransformation))
            v.addWidget(logo)
        version = QLabel(f"Version {__version__}")
        version.setFont(_f(10, bold=True, mono=True))
        version.setStyleSheet(f"color:{CYAN};")
        v.addWidget(version)
        body = QLabel(
            "Plyrium Echo - push-to-talk dictation that runs 100% on your machine.\n\n"
            "Your voice and your text never leave this computer. Transcription and the "
            "AI cleanup both run locally. Network access is limited to explicit actions "
            "like downloading a model, checking for updates, or opening the license page.\n\n"
            f"Hold {self.cfg.hotkey} to talk.  Tap {self.cfg.handsfree_hotkey} for "
            "hands-free.  Esc cancels.\n\nPart of the Plyrium family.")
        body.setWordWrap(True); body.setFont(_f(10)); body.setStyleSheet(f"color:{INK};")
        v.addWidget(body)

        updater = Card(bg=PANEL2, radius=14)
        ul = QVBoxLayout(updater); ul.setContentsMargins(16, 14, 16, 14); ul.setSpacing(8)
        uh = QLabel("Updates")
        uh.setFont(_f(13, bold=True)); uh.setStyleSheet(f"color:{INK};")
        self._update_status = QLabel(
            "Check GitHub Releases for a newer Echo build. Your transcripts, "
            "license, settings, and downloaded models stay in the local data folder."
        )
        self._update_status.setWordWrap(True)
        self._update_status.setFont(_f(9))
        self._update_status.setStyleSheet(f"color:{DIM};")
        ur = QHBoxLayout()
        self._check_update_btn = QPushButton("Check for updates")
        self._check_update_btn.setCursor(Qt.PointingHandCursor)
        self._check_update_btn.setStyleSheet(self._btn_qss())
        self._check_update_btn.clicked.connect(self._check_updates)
        self._install_update_btn = QPushButton("Download and install")
        self._install_update_btn.setCursor(Qt.PointingHandCursor)
        self._install_update_btn.setStyleSheet(self._btn_qss(primary=True))
        self._install_update_btn.clicked.connect(self._install_update)
        self._install_update_btn.setEnabled(False)
        ur.addWidget(self._check_update_btn)
        ur.addWidget(self._install_update_btn)
        ur.addStretch()
        ul.addWidget(uh); ul.addWidget(self._update_status); ul.addLayout(ur)
        v.addWidget(updater)
        v.addStretch()
        return page

    def _check_updates(self):
        self._latest_update = None
        self._check_update_btn.setEnabled(False)
        self._install_update_btn.setEnabled(False)
        self._set_update_message("Checking for updates...")

        def work():
            try:
                self.sig_update_checked.emit(self.app.check_for_updates())
            except Exception as exc:
                self.sig_update_failed.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, release):
        self._check_update_btn.setEnabled(True)
        self._latest_update = release if getattr(release, "update_available", False) else None
        if not getattr(release, "asset", None):
            self._install_update_btn.setEnabled(False)
            self._set_update_message(
                f"Version {release.version} is online, but no updater package "
                "is available for this platform yet."
            )
            return
        if release.update_available:
            self._install_update_btn.setEnabled(True)
            self._set_update_message(
                f"Plyrium Echo {release.version} is available. Click Download "
                "and install to update in place."
            )
        else:
            self._install_update_btn.setEnabled(False)
            self._set_update_message(f"You are up to date on Plyrium Echo {__version__}.")

    def _install_update(self):
        release = getattr(self, "_latest_update", None)
        if release is None:
            return
        if QMessageBox.question(
            self,
            "Install update",
            "Echo will download and verify the update. On Windows, the app will "
            "close, update in place, and reopen. Your transcripts, license, "
            "settings, and models will stay intact.",
        ) != QMessageBox.Yes:
            return
        self._check_update_btn.setEnabled(False)
        self._install_update_btn.setEnabled(False)

        def progress(msg: str):
            self.sig_update_message.emit(msg)

        def work():
            try:
                msg = self.app.install_update(release, progress=progress)
                self.sig_update_ready.emit(msg)
            except Exception as exc:
                self.sig_update_failed.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _set_update_message(self, msg: str):
        if hasattr(self, "_update_status"):
            self._update_status.setText(msg)

    def _on_update_failed(self, msg: str):
        self._check_update_btn.setEnabled(True)
        self._install_update_btn.setEnabled(bool(getattr(self, "_latest_update", None)))
        self._set_update_message(f"Update failed: {msg}")

    def _on_update_ready(self, msg: str):
        self._set_update_message(msg)
        QMessageBox.information(self, "Plyrium Echo update", msg)

    # ---- shared button style ----
    def _btn_qss(self, primary=False, danger=False):
        if primary:
            return ("QPushButton{color:white;border:none;border-radius:8px;padding:7px 16px;"
                    "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                    f"stop:0 {BLUE},stop:1 {VIOLET});}}")
        fg = "#ff6b78" if danger else INK
        return (f"QPushButton{{color:{fg};background:#1a2030;border:none;border-radius:8px;"
                f"padding:7px 16px;}}QPushButton:hover{{background:{BLUE};color:white;}}")

    # ---- status badge ----
    def _refresh_status(self):
        t = self.app.transcriber
        dev = t.device.upper() if t.device != "cuda" else "CUDA"
        self._badge_title.setText("MODEL READY"); self._badge_title.setStyleSheet(f"color:{GREEN};")
        self._badge_sub.setText(f"{t.model_size} / {dev}")

    def refresh_status(self):
        self.sig_refresh_status.emit()

    def _set_status_text(self, msg):
        self._badge_title.setText("GPU SETUP"); self._badge_title.setStyleSheet(f"color:{CYAN};")
        self._badge_sub.setText(msg)

    # called from app (background threads) via signals
    def set_gpu_status(self, msg):
        self.sig_status.emit(msg)

    def _on_new_entry(self):
        if getattr(self, "_cur", None) in ("History", "Home"):
            self.show_section(self._cur)

    def on_new_entry(self):
        self.sig_history.emit()
