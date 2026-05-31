"""The main Plyrium Echo window — a clean, frameless "splash" opened from the tray.

No OS title bar (a Windows chrome looks out of place here); instead a custom
draggable top strip with a close button, Esc to dismiss. Light theme to match
the clean reference look. Left nav + swappable sections:

  Home       greeting + stat cards
  History    every transcript, grouped by day, full word-wrapped text
  Dictionary custom vocab the AI cleanup protects
  Settings   everything the tray has, in a real UI
  About      the privacy story

Pure Tkinter (no new deps). Always created/driven on the Tk main thread — the
tray marshals ``open`` through ``Overlay.run_on_ui``. The only slow action
(switching models) is dispatched to a background thread.
"""

from __future__ import annotations

import getpass
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import autostart

# ── dark graphite palette (Plyrium Echo brand kit, echo-splash-theme-tokens) ──
BG = "#0b0d12"          # shell
SIDEBAR = "#090b11"     # sidebar (slightly darker)
TEXT = "#f0eee8"        # ink
MUTED = "#a8b0c2"       # dim
FAINT = "#6f7a91"       # muted
BORDER = "#2c3340"      # line
CARD = "#11141b"        # panel
CARD_BORDER = "#222a38"
ACCENT = "#5B7CFF"      # EchoBlue
ACCENT2 = "#8B5CF6"     # SignalViolet
CYAN = "#00D4FF"
GREEN = "#00E676"       # local-green
ORANGE = "#FF6A00"      # forge-orange (family accent)
SELECT = "#1a2030"      # selected nav bg
HOVER = "#141822"
ROW_HOVER = "#141822"
DANGER = "#ff6b78"

SECTIONS = [("Home", "⌂"), ("History", "◷"), ("Dictionary", "▤"),
            ("Settings", "⚙"), ("About", "ⓘ")]

MODEL_CHOICES = [
    ("Small — fastest (good on CPU)", "small.en"),
    ("Medium — balanced", "medium.en"),
    ("Large — most accurate (GPU)", "large-v3-turbo"),
]
OUTPUT_CHOICES = [("Paste (recommended)", "paste"), ("Type", "type"),
                  ("Clipboard only", "clipboard")]
DUCK_CHOICES = [("Off", None), ("Light (40%)", 0.40),
                ("Medium (25%)", 0.25), ("Strong (15%)", 0.15)]

_F = "Segoe UI"
_BTN = dict(relief="flat", bd=0, padx=14, pady=6, font=(_F, 9), cursor="hand2",
            bg="#1a2030", fg=TEXT, activebackground=ACCENT, activeforeground="white",
            highlightthickness=0)
_BTN_DANGER = dict(_BTN, fg=DANGER, activebackground="#3a1d22")


def _day_label(ts: float, now: float) -> str:
    try:
        lt = time.localtime(ts)
        today = time.localtime(now)
        ydy = time.localtime(now - 86400)
        if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
            return "TODAY"
        if (lt.tm_year, lt.tm_yday) == (ydy.tm_year, ydy.tm_yday):
            return "YESTERDAY"
        return time.strftime("%B %d, %Y", lt).upper()
    except Exception:
        return ""


def _clock(ts: float) -> str:
    try:
        return time.strftime("%I:%M %p", time.localtime(ts)).lstrip("0")
    except Exception:
        return ""


class MainWindow:
    def __init__(self, root, app):
        self.app = app
        self.cfg = app.cfg
        self.win = tk.Toplevel(root)
        self.win.configure(bg=BG)
        self.win.overrideredirect(True)        # no Windows title bar
        w, h = 980, 660
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2 - 20}")
        self.win.attributes("-topmost", True)
        self.win.after(400, lambda: self._safe(lambda: self.win.attributes("-topmost", False)))
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.option_add("*TCombobox*Listbox.background", CARD)
        self.win.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.win.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.win.option_add("*TCombobox*Listbox.selectForeground", "white")
        self._style()
        self._cur = None
        self._nav = {}
        self._wrap_labels = []   # history text labels to re-wrap on resize
        self._build()
        self.show("Home")
        self.win.after(30, lambda: self._safe(self.win.focus_force))

    # ── infra ──
    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            pass

    def _load_mark(self, size: int):
        """Load the brand mark as a Tk PhotoImage (kept on self so it isn't GC'd)."""
        try:
            from PIL import Image, ImageTk

            from .icon import mark_image
            img = mark_image(size * 4).resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _style(self):
        st = ttk.Style(self.win)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("E.TCombobox", fieldbackground=CARD, background="#1a2030",
                     foreground=TEXT, arrowcolor=TEXT, borderwidth=1,
                     bordercolor=CARD_BORDER, lightcolor=CARD, darkcolor=CARD)
        st.map("E.TCombobox", fieldbackground=[("readonly", CARD)],
               selectbackground=[("readonly", CARD)], selectforeground=[("readonly", TEXT)])
        st.configure("E.Vertical.TScrollbar", background="#2c3340", troughcolor=BG,
                     borderwidth=0, arrowcolor=MUTED)

    @staticmethod
    def _lerp_hex(a, b, t):
        a = tuple(int(a[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(b[i:i + 2], 16) for i in (1, 3, 5))
        return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def _edge_gradient(self, parent, height=3):
        """Cyan->blue->violet accent strip (the brand 'edge' from the splash)."""
        c = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0, bd=0)
        c.pack(side="top", fill="x")
        stops = [(0.0, CYAN), (0.5, ACCENT), (1.0, ACCENT2)]

        def draw(_e=None):
            c.delete("all")
            w = c.winfo_width() or self.win.winfo_width() or 980
            for x in range(w):
                t = x / max(1, w - 1)
                # pick the segment
                if t <= 0.5:
                    col = self._lerp_hex(stops[0][1], stops[1][1], t / 0.5)
                else:
                    col = self._lerp_hex(stops[1][1], stops[2][1], (t - 0.5) / 0.5)
                c.create_line(x, 0, x, height, fill=col)
        c.bind("<Configure>", draw)
        self.win.after(20, draw)

    def _build(self):
        # gradient edge accent at the very top (brand 'edge')
        self._edge_gradient(self.win, height=3)

        # custom draggable top strip with a close button
        top = tk.Frame(self.win, bg=BG, height=34)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)
        for w in (top,):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        close = tk.Label(top, text="✕", bg=BG, fg=FAINT, font=(_F, 12),
                         cursor="hand2", padx=12)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.close())
        close.bind("<Enter>", lambda e: close.config(fg=DANGER))
        close.bind("<Leave>", lambda e: close.config(fg=FAINT))
        mini = tk.Label(top, text="–", bg=BG, fg=FAINT, font=(_F, 12),
                        cursor="hand2", padx=10)
        mini.pack(side="right")
        mini.bind("<Button-1>", lambda e: self.close())  # closes back to tray
        mini.bind("<Enter>", lambda e: mini.config(fg=TEXT))
        mini.bind("<Leave>", lambda e: mini.config(fg=FAINT))

        body = tk.Frame(self.win, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        side = tk.Frame(body, bg=SIDEBAR, width=200)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        head = tk.Frame(side, bg=SIDEBAR)
        head.pack(fill="x", pady=(8, 18), padx=14)
        head.bind("<Button-1>", self._drag_start)
        head.bind("<B1-Motion>", self._drag_move)
        row = tk.Frame(head, bg=SIDEBAR)
        row.pack(fill="x")
        # brand mark image (falls back to a glyph if the asset can't load)
        self._mark_img = self._load_mark(28)
        if self._mark_img is not None:
            ml = tk.Label(row, image=self._mark_img, bg=SIDEBAR)
            ml.pack(side="left", padx=(0, 8))
            ml.bind("<Button-1>", self._drag_start)
            ml.bind("<B1-Motion>", self._drag_move)
        wm = tk.Label(row, text="Plyrium Echo", bg=SIDEBAR, fg=TEXT,
                      anchor="w", font=(_F, 13, "bold"))
        wm.pack(side="left")
        wm.bind("<Button-1>", self._drag_start)
        wm.bind("<B1-Motion>", self._drag_move)
        tag = tk.Frame(head, bg=SIDEBAR)
        tag.pack(fill="x", pady=(3, 0))
        tk.Label(tag, text="●", bg=SIDEBAR, fg=GREEN,
                 font=(_F, 7)).pack(side="left")
        tk.Label(tag, text="LOCAL / OFFLINE", bg=SIDEBAR, fg=FAINT,
                 font=("Consolas", 8), anchor="w").pack(side="left", padx=(5, 0))

        for name, glyph in SECTIONS:
            b = tk.Label(side, text=f"    {glyph}   {name}", bg=SIDEBAR, fg=MUTED,
                         anchor="w", font=(_F, 11), cursor="hand2")
            b.pack(fill="x", ipady=9, padx=8, pady=1)
            b.bind("<Button-1>", lambda e, n=name: self.show(n))
            b.bind("<Enter>", lambda e, n=name: self._hover(n, True))
            b.bind("<Leave>", lambda e, n=name: self._hover(n, False))
            self._nav[name] = b

        # MODEL READY badge box (green), bottom of sidebar
        self._status_box = tk.Frame(side, bg="#0c1812", highlightbackground="#1f5a3a",
                                    highlightthickness=1)
        self._status_box.pack(side="bottom", fill="x", padx=14, pady=14)
        self._status_title = tk.Label(self._status_box, text="MODEL READY",
                                      bg="#0c1812", fg=GREEN, anchor="w",
                                      font=("Consolas", 9, "bold"))
        self._status_title.pack(anchor="w", padx=12, pady=(8, 0))
        self._status = tk.Label(self._status_box, text="", bg="#0c1812", fg=MUTED,
                                anchor="w", font=("Consolas", 8), justify="left")
        self._status.pack(anchor="w", padx=12, pady=(0, 8))
        self._refresh_status()

        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    # ── window move ──
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root, e.y_root
        self._ox, self._oy = self.win.winfo_x(), self.win.winfo_y()

    def _drag_move(self, e):
        nx = self._ox + (e.x_root - self._dx)
        ny = self._oy + (e.y_root - self._dy)
        self.win.geometry(f"+{nx}+{ny}")

    def _hover(self, name, on):
        if name == self._cur:
            return
        self._nav[name].config(bg=HOVER if on else SIDEBAR)

    def _refresh_status(self):
        t = self.app.transcriber
        dev = t.compute_type and (t.device.upper() if t.device != "cuda" else "CUDA")
        self._safe(lambda: self._status_title.config(text="MODEL READY", fg=GREEN))
        self._safe(lambda: self._status.config(
            text=f"{t.model_size} / {dev}"))

    def set_gpu_status(self, msg):
        """Show transient GPU setup progress in the sidebar status badge."""
        self._safe(lambda: self._status_title.config(text="GPU SETUP", fg=CYAN))
        self._safe(lambda: self._status.config(text=msg))

    def show(self, name):
        self._cur = name
        for n, b in self._nav.items():
            sel = n == name
            b.config(bg=SELECT if sel else SIDEBAR, fg=ACCENT if sel else MUTED,
                     font=(_F, 11, "bold") if sel else (_F, 11))
        for w in self.content.winfo_children():
            w.destroy()
        self._wrap_labels = []
        try:
            getattr(self, "_sec_" + name.lower())()
        except Exception as exc:
            tk.Label(self.content, text=f"({name} failed: {exc})", bg=BG,
                     fg=DANGER).pack(padx=24, pady=24)

    def close(self):
        self._safe(self.win.destroy)
        self.app._window = None

    def on_new_entry(self):
        """Called when a fresh dictation lands, so the open view stays live."""
        if self._cur in ("History", "Home"):
            self._safe(lambda: self.show(self._cur))

    def _heading(self, text, sub=None):
        tk.Label(self.content, text=text, bg=BG, fg=TEXT,
                 font=(_F, 20, "bold")).pack(anchor="w", padx=34, pady=(26, 2))
        if sub:
            tk.Label(self.content, text=sub, bg=BG, fg=MUTED,
                     font=(_F, 10)).pack(anchor="w", padx=34, pady=(0, 14))

    # ── Home (matches echo-splash-redesign) ──
    def _sec_home(self):
        hour = time.localtime().tm_hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        name = (getpass.getuser() or "there").split("@")[0].title()

        # greeting row with a PRIVATE pill on the right
        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", padx=34, pady=(26, 0))
        gl = tk.Frame(head, bg=BG)
        gl.pack(side="left")
        tk.Label(gl, text=f"Good {part}, {name}", bg=BG, fg=TEXT,
                 font=(_F, 26, "bold")).pack(anchor="w")
        tk.Label(gl, text=f"Hold {self.cfg.hotkey}, speak, release. Echo cleans "
                 "it locally.", bg=BG, fg=MUTED, font=(_F, 10)).pack(anchor="w",
                                                                     pady=(2, 0))
        pill = tk.Frame(head, bg="#0f2018", highlightbackground="#1f5a3a",
                        highlightthickness=1)
        pill.pack(side="right", pady=(6, 0))
        tk.Label(pill, text="●  PRIVATE", bg="#0f2018", fg=GREEN,
                 font=(_F, 9, "bold")).pack(padx=12, pady=5)

        # license trial strip (kept, restyled dark) - only when not licensed
        lic = self.app.license
        kind, info = lic.status()
        if kind != "licensed":
            bn = tk.Frame(self.content, bg="#151924")
            bn.pack(fill="x", padx=34, pady=(14, 0))
            txt = (f"Trial - {info} day{'s' if info != 1 else ''} left"
                   if kind == "trial" else "Trial ended - activate to keep dictating")
            tk.Label(bn, text=txt, bg="#151924",
                     fg=(TEXT if kind == "trial" else DANGER),
                     font=(_F, 10, "bold")).pack(side="left", padx=12, pady=9)
            tk.Button(bn, text="Buy a license", **_BTN, command=self._open_buy
                      ).pack(side="right", padx=10, pady=6)
            tk.Button(bn, text="Enter key", **_BTN,
                      command=lambda: self.show("Settings")).pack(side="right", pady=6)

        # stat cards with colored top accent bars (cyan / blue / violet)
        st = self.app.history.stats() if self.app.history else {"entries": 0, "words": 0}
        saved = (st["words"] or 0) / 40.0
        cards = [("Total words dictated", f"{st['words']:,}", CYAN),
                 ("Dictations", f"{st['entries']:,}", ACCENT),
                 ("Typing time saved", f"{saved:.0f} min", ACCENT2)]
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="x", padx=30, pady=(16, 0))
        for i, (label, value, accent) in enumerate(cards):
            card = tk.Frame(grid, bg=CARD, highlightbackground=CARD_BORDER,
                            highlightthickness=1)
            card.grid(row=0, column=i, sticky="nsew", padx=6)
            tk.Frame(card, bg=accent, height=3).pack(fill="x")          # top accent
            tk.Label(card, text=label, bg=CARD, fg=MUTED, anchor="w",
                     font=(_F, 9)).pack(anchor="w", padx=18, pady=(14, 0))
            tk.Label(card, text=value, bg=CARD, fg=TEXT, anchor="w",
                     font=(_F, 28, "bold")).pack(anchor="w", padx=18, pady=(2, 16))
            grid.columnconfigure(i, weight=1)

        # lower row: Live voice lane card + big ringed mark
        low = tk.Frame(self.content, bg=BG)
        low.pack(fill="x", padx=30, pady=(16, 0))

        lane = tk.Frame(low, bg=CARD, highlightbackground=CARD_BORDER, highlightthickness=1)
        lane.pack(side="left", fill="both", expand=True, padx=6)
        tk.Label(lane, text="Live voice lane", bg=CARD, fg=TEXT,
                 font=(_F, 14, "bold")).pack(anchor="w", padx=20, pady=(16, 0))
        tk.Label(lane, text="Your voice becomes clean text in any app.", bg=CARD,
                 fg=MUTED, font=(_F, 9)).pack(anchor="w", padx=20)
        wave = tk.Canvas(lane, height=90, bg=CARD, highlightthickness=0)
        wave.pack(fill="x", padx=20, pady=(8, 4))
        wave.bind("<Configure>", lambda e, c=wave: self._draw_voice_lane(c))
        foot = tk.Frame(lane, bg=CARD)
        foot.pack(fill="x", padx=20, pady=(0, 16))
        idle = tk.Frame(foot, bg=ACCENT)
        idle.pack(side="left")
        tk.Label(idle, text="Listening idle", bg=ACCENT, fg="white",
                 font=(_F, 9, "bold")).pack(padx=12, pady=3)
        tk.Label(foot, text="voice stays local", bg=CARD, fg=GREEN,
                 font=(_F, 9, "bold")).pack(side="right")

        ring = tk.Canvas(low, width=210, height=200, bg=BG, highlightthickness=0)
        ring.pack(side="left", padx=6)
        self._draw_ring_mark(ring)

        # LAST CLEANUP footer bar
        lc = tk.Frame(self.content, bg="#0a0c11", highlightbackground=CARD_BORDER,
                      highlightthickness=1)
        lc.pack(fill="x", padx=36, pady=(16, 0))
        tk.Label(lc, text="LAST CLEANUP", bg="#0a0c11", fg=FAINT,
                 font=("Consolas", 8, "bold")).pack(anchor="w", padx=16, pady=(10, 0))
        inner = tk.Frame(lc, bg="#0a0c11")
        inner.pack(fill="x", padx=16, pady=(0, 12))
        tk.Label(inner, text="Removed filler, fixed punctuation, and kept your "
                 "project names intact.", bg="#0a0c11", fg=MUTED,
                 font=(_F, 10)).pack(side="left")
        tk.Label(inner, text=">_", bg="#0a0c11", fg=ORANGE,
                 font=("Consolas", 13, "bold")).pack(side="right")

    def _draw_voice_lane(self, c):
        c.delete("all")
        w = c.winfo_width() or 460
        h = 90
        mid = h / 2
        # a stylized waveform path (matches the splash's edge gradient feel)
        pts = [(0, 0.0), (0.10, 0.05), (0.18, -0.45), (0.27, 0.75),
               (0.40, -0.95), (0.52, 0.9), (0.63, -0.55), (0.72, 0.35),
               (0.85, -0.15), (1.0, 0.0)]
        segs = [CYAN, ACCENT, ACCENT2]
        coords = [(p[0] * w, mid + p[1] * (mid - 8)) for p in pts]
        for i in range(len(coords) - 1):
            col = segs[min(len(segs) - 1, int(i / len(coords) * len(segs)))]
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]
            c.create_line(x1, y1, x2, y2, fill=col, width=4,
                          capstyle="round", joinstyle="round", smooth=True)

    def _draw_ring_mark(self, c):
        cx, cy = 105, 100
        c.create_oval(cx - 95, cy - 95, cx + 95, cy + 95, outline="#23314f", width=1)
        c.create_oval(cx - 66, cy - 66, cx + 66, cy + 66, outline="#1c3b4a", width=1)
        if getattr(self, "_mark_big", None) is None:
            self._mark_big = self._load_mark(120)
        if self._mark_big is not None:
            c.create_image(cx, cy, image=self._mark_big)

    # ── History ──
    def _sec_history(self):
        self._heading("History",
                      "All transcripts are private and stored locally on your machine.")
        bar = tk.Frame(self.content, bg=BG)
        bar.pack(fill="x", padx=34, pady=(0, 8))
        self._search = tk.Entry(bar, bg="#151924", fg=TEXT, insertbackground=TEXT,
                                relief="flat", font=(_F, 10))
        self._search.pack(side="left", fill="x", expand=True, ipady=6, ipadx=8)
        self._search.insert(0, "")
        self._search.bind("<KeyRelease>", lambda e: self._hist_refresh())
        tk.Button(bar, text="Clear all", command=self._hist_clear, **_BTN_DANGER
                  ).pack(side="left", padx=(10, 0))

        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="both", expand=True, padx=(26, 18), pady=(0, 18))
        self._canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self._canvas.yview,
                            style="E.Vertical.TScrollbar")
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._inner = tk.Frame(self._canvas, bg=BG)
        self._inner_id = self._canvas.create_window((0, 0), window=self._inner,
                                                    anchor="nw")
        self._inner.bind("<Configure>", lambda e: self._canvas.configure(
            scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)
        self._hist_refresh()

    def _on_canvas_resize(self, e):
        self._canvas.itemconfigure(self._inner_id, width=e.width)
        wl = max(220, e.width - 150)
        for lbl in self._wrap_labels:
            self._safe(lambda l=lbl: l.config(wraplength=wl))

    def _on_wheel(self, e):
        if getattr(self, "_canvas", None) and self._canvas.winfo_exists():
            self._canvas.yview_scroll(int(-e.delta / 120), "units")

    def _hist_refresh(self):
        for w in self._inner.winfo_children():
            w.destroy()
        self._wrap_labels = []
        store = self.app.history
        q = self._search.get().strip() if hasattr(self, "_search") else ""
        rows = store.list(search=q) if store else []
        if not rows:
            tk.Label(self._inner, text="No transcripts yet — hold your hotkey and "
                     "speak.", bg=BG, fg=FAINT, font=(_F, 10)).pack(anchor="w",
                                                                    padx=10, pady=20)
            return
        now = time.time()
        cur_day = None
        wl = max(220, self._canvas.winfo_width() - 150)
        for r in rows:
            day = _day_label(r["ts"], now)
            if day != cur_day:
                cur_day = day
                tk.Label(self._inner, text=day, bg=BG, fg=FAINT,
                         font=(_F, 8, "bold")).pack(anchor="w", padx=12,
                                                    pady=(16, 4))
            self._hist_row(r, wl)

    def _hist_row(self, r, wl):
        row = tk.Frame(self._inner, bg=BG)
        row.pack(fill="x", padx=4)
        meta = (r["app"] or "").replace(".exe", "")
        tcol = tk.Label(row, text=_clock(r["ts"]), bg=BG, fg=MUTED, width=10,
                        anchor="nw", font=(_F, 9), justify="left")
        tcol.pack(side="left", padx=(8, 10), pady=10, anchor="n")
        txt = tk.Label(row, text=r["text"], bg=BG, fg=TEXT, justify="left",
                       anchor="w", wraplength=wl, font=(_F, 10))
        txt.pack(side="left", fill="x", expand=True, pady=10)
        self._wrap_labels.append(txt)
        sep = tk.Frame(self._inner, bg=BORDER, height=1)
        sep.pack(fill="x", padx=8)

        def hover(on):
            c = ROW_HOVER if on else BG
            for wdg in (row, tcol, txt):
                self._safe(lambda w=wdg: w.config(bg=c))
        for wdg in (row, tcol, txt):
            wdg.bind("<Enter>", lambda e: hover(True))
            wdg.bind("<Leave>", lambda e: hover(False))
            wdg.bind("<Button-1>", lambda e, t=r["text"], tc=tcol: self._copy(t, tc))
            wdg.bind("<Button-3>", lambda e, eid=r["id"]: self._row_menu(e, eid))

    def _copy(self, text, tcol):
        try:
            import pyperclip
            pyperclip.copy(text)
            old = tcol.cget("text")
            tcol.config(text="copied!", fg=ACCENT)
            self.win.after(900, lambda: self._safe(
                lambda: tcol.config(text=old, fg=MUTED)))
        except Exception:
            pass

    def _row_menu(self, e, eid):
        m = tk.Menu(self.win, tearoff=0, bg=CARD, fg=TEXT,
                    activebackground=ACCENT, activeforeground="white")
        ent = self.app.history.get(eid)
        if ent:
            m.add_command(label="Copy",
                          command=lambda: self._safe(
                              lambda: __import__("pyperclip").copy(ent["text"])))
        m.add_command(label="Delete", command=lambda: (
            self.app.history.delete(eid), self._hist_refresh()))
        self._safe(lambda: m.tk_popup(e.x_root, e.y_root))

    def _hist_clear(self):
        if messagebox.askyesno("Clear history",
                               "Delete all saved transcripts? This can't be undone.",
                               parent=self.win):
            self.app.history.clear()
            self._hist_refresh()

    # ── Settings ──
    def _sec_settings(self):
        self._heading("Settings")
        form = tk.Frame(self.content, bg=BG)
        form.pack(fill="both", expand=True, padx=34)

        # ── license ──
        lic = self.app.license
        lf = tk.Frame(form, bg="#151924")
        lf.pack(fill="x", pady=(2, 12))
        tk.Label(lf, text=lic.status_text(), bg="#151924", fg=TEXT,
                 font=(_F, 10, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        if not lic.licensed():
            tk.Label(lf, text="Paste your license key to unlock unlimited use:",
                     bg="#151924", fg=MUTED, font=(_F, 9)).pack(anchor="w", padx=12)
            lr = tk.Frame(lf, bg="#151924")
            lr.pack(fill="x", padx=12, pady=10)
            ent = tk.Entry(lr, bg="#0b0d12", fg=TEXT, relief="flat", font=(_F, 9),
                           insertbackground=TEXT)
            ent.pack(side="left", fill="x", expand=True, ipady=5, ipadx=6)
            tk.Button(lr, text="Activate", **_BTN,
                      command=lambda: self._activate(ent.get())).pack(side="left",
                                                                      padx=(8, 0))
            tk.Button(lr, text="Buy a license", **_BTN, command=self._open_buy
                      ).pack(side="left", padx=6)

        # ── GPU acceleration (NVIDIA, on-demand) ──
        try:
            from .model import _cuda_available, cuda_usable
            gpu_present = _cuda_available()
            gpu_ready = cuda_usable()      # device present AND cuBLAS loadable
        except Exception:
            gpu_present, gpu_ready = False, False
        if gpu_present and not gpu_ready:
            gf = tk.Frame(form, bg="#0f1a14")
            gf.pack(fill="x", pady=(0, 12))
            tk.Label(gf, text="NVIDIA GPU detected", bg="#0f1a14", fg=TEXT,
                     font=(_F, 10, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
            self._gpu_status = tk.Label(
                gf, text="Enable GPU acceleration for much faster, more accurate "
                "dictation (one-time ~1.9 GB download).", bg="#0f1a14", fg=MUTED,
                font=(_F, 9), wraplength=560, justify="left")
            self._gpu_status.pack(anchor="w", padx=12)
            tk.Button(gf, text="Enable GPU acceleration", **_BTN,
                      command=self._enable_gpu).pack(anchor="w", padx=12, pady=10)

        def combo(label, choices, current_value, on_pick):
            r = tk.Frame(form, bg=BG)
            r.pack(fill="x", pady=7)
            tk.Label(r, text=label, bg=BG, fg=TEXT, width=20, anchor="w",
                     font=(_F, 10)).pack(side="left")
            labels = [c[0] for c in choices]
            cur = next((c[0] for c in choices if c[1] == current_value), labels[0])
            var = tk.StringVar(value=cur)
            cb = ttk.Combobox(r, values=labels, textvariable=var, state="readonly",
                              style="E.TCombobox", width=30)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>",
                    lambda e: on_pick(dict(choices)[var.get()]))

        combo("Model", MODEL_CHOICES, self.cfg.model_size, self._pick_model)
        combo("Output mode", OUTPUT_CHOICES, self.cfg.output_mode,
              self.app.set_output_mode)
        duck_cur = None if not self.cfg.duck_audio else self.cfg.duck_level
        combo("Lower other audio", DUCK_CHOICES, duck_cur, self.app.set_duck)

        # ── shortcuts (record any combo you like) ──
        tk.Frame(form, bg=BORDER, height=1).pack(fill="x", pady=10)
        tk.Label(form, text="Shortcuts", bg=BG, fg=MUTED,
                 font=(_F, 9, "bold")).pack(anchor="w")

        def hk_row(label, combo_str, which, allow_disable):
            r = tk.Frame(form, bg=BG)
            r.pack(fill="x", pady=5)
            tk.Label(r, text=label, bg=BG, fg=TEXT, width=20, anchor="w",
                     font=(_F, 10)).pack(side="left")
            tk.Label(r, text=self._pretty(combo_str), bg=BG, fg=ACCENT, width=18,
                     anchor="w", font=(_F, 10, "bold")).pack(side="left")
            tk.Button(r, text="Change", command=lambda: self._capture_hotkey(which),
                      **_BTN).pack(side="left")
            if allow_disable and combo_str:
                tk.Button(r, text="Disable", **_BTN_DANGER,
                          command=lambda: (self.app.set_hotkey(handsfree=None),
                                           self.show("Settings"))).pack(side="left",
                                                                        padx=6)

        hk_row("Push-to-talk", self.cfg.hotkey, "ptt", False)
        hk_row("Hands-free toggle", self.cfg.handsfree_hotkey, "hf", True)

        def check(label, getter, setter):
            var = tk.BooleanVar(value=bool(getter()))
            tk.Checkbutton(form, text="  " + label, variable=var,
                           command=lambda: setter(var.get()), bg=BG, fg=TEXT,
                           selectcolor="#1a2030", activebackground=BG,
                           activeforeground=TEXT, anchor="w", font=(_F, 10),
                           highlightthickness=0, bd=0).pack(fill="x", pady=3)

        tk.Frame(form, bg=BORDER, height=1).pack(fill="x", pady=10)
        check("Smart formatting", lambda: self.cfg.smart_format,
              self.app.set_smart_format)
        check("Drop period in chat apps", lambda: self.cfg.chat_apps_no_period,
              self.app.set_chat_period)
        check("Show waveform overlay", lambda: self.cfg.overlay, self.app.set_overlay)
        check("AI cleanup (Ollama)", lambda: self.cfg.llm_cleanup,
              self.app.set_llm_cleanup)
        check("Save dictation history", lambda: self.cfg.history_enabled,
              self.app.set_history_enabled)
        tk.Frame(form, bg=BORDER, height=1).pack(fill="x", pady=10)
        check("Start with Windows", autostart.is_enabled,
              lambda v: autostart.set_enabled(v))

    def _open_buy(self):
        try:
            webbrowser.open(self.cfg.buy_url)
        except Exception:
            pass

    def _enable_gpu(self):
        def prog(m):
            self._safe(lambda: self.win.after(
                0, lambda: self._gpu_status.config(text=m)))

        def work():
            ok = self.app.provision_gpu(notify=prog)
            self._safe(lambda: self.win.after(
                0, lambda: (self._refresh_status(),
                            self.show("Settings") if ok else None)))
        threading.Thread(target=work, daemon=True).start()

    def _activate(self, key):
        ok, msg = self.app.activate_license(key)
        if ok:
            messagebox.showinfo("Plyrium Echo", msg, parent=self.win)
            self.show("Settings")
        else:
            messagebox.showerror("Plyrium Echo", msg, parent=self.win)

    def _pick_model(self, size):
        if size == self.cfg.model_size:
            return
        # reload_model loads the model (on CPU if CUDA isn't ready) and then, for
        # a heavy model on an NVIDIA box, auto-fetches CUDA + switches to GPU in
        # the background — no manual step needed.
        threading.Thread(
            target=lambda: (self.app.reload_model(size),
                            self._safe(lambda: self.win.after(0, self._refresh_status))),
            daemon=True).start()

    # ── hotkey capture ──
    _MODORD = ["ctrl", "alt", "shift", "win"]
    _NICE = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win",
             "space": "Space", "caps_lock": "Caps", "tab": "Tab"}

    def _pretty(self, combo_str):
        toks = [t for t in (combo_str or "").lower().split("+") if t]
        if not toks:
            return "Disabled"
        return " + ".join(self._NICE.get(t, t.upper() if len(t) <= 2
                                         else t.capitalize()) for t in toks)

    def _order(self, s):
        mods = [m for m in self._MODORD if m in s]
        rest = sorted(x for x in s if x not in self._MODORD)
        return mods + rest

    @staticmethod
    def _tk_token(keysym):
        m = {"Control_L": "ctrl", "Control_R": "ctrl", "Alt_L": "alt",
             "Alt_R": "alt", "Shift_L": "shift", "Shift_R": "shift",
             "Super_L": "win", "Super_R": "win", "Win_L": "win", "Win_R": "win",
             "Meta_L": "win", "Meta_R": "win", "space": "space",
             "Caps_Lock": "caps_lock", "Tab": "tab"}
        if keysym in m:
            return m[keysym]
        if len(keysym) == 1 and keysym.isalnum():
            return keysym.lower()
        if keysym[:1] in "Ff" and keysym[1:].isdigit():
            return keysym.lower()
        return None  # ignore keys we can't bind

    def _capture_hotkey(self, which):
        dlg = tk.Toplevel(self.win)
        dlg.overrideredirect(True)
        dlg.configure(bg=CARD)
        w, h = 400, 160
        x = self.win.winfo_x() + (self.win.winfo_width() - w) // 2
        y = self.win.winfo_y() + (self.win.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.attributes("-topmost", True)
        tk.Frame(dlg, bg=ACCENT, height=3).pack(fill="x")
        tk.Label(dlg, text="Press your shortcut", bg=CARD, fg=TEXT,
                 font=(_F, 13, "bold")).pack(pady=(22, 2))
        cur = tk.Label(dlg, text="…", bg=CARD, fg=ACCENT, font=(_F, 15, "bold"))
        cur.pack(pady=6)
        tk.Label(dlg, text="release to set  ·  Esc to cancel", bg=CARD, fg=MUTED,
                 font=(_F, 8)).pack(pady=(8, 0))
        state = {"held": set(), "best": set(), "done": False}

        def finish(s):
            if state["done"]:
                return
            state["done"] = True
            try:
                self.app.hk.suspended = False
                self.app.hk.pressed.clear()
            except Exception:
                pass
            self._safe(dlg.destroy)
            if s:
                combo = "+".join(self._order(s))
                if which == "ptt":
                    self.app.set_hotkey(ptt=combo)
                else:
                    self.app.set_hotkey(handsfree=combo)
            self._safe(lambda: self.show("Settings"))

        def on_press(e):
            if e.keysym == "Escape":
                finish(None)
                return
            t = self._tk_token(e.keysym)
            if t:
                state["held"].add(t)
                if len(state["held"]) > len(state["best"]):
                    state["best"] = set(state["held"])
            if state["best"]:
                cur.config(text=self._pretty("+".join(self._order(state["best"]))))

        def on_release(e):
            t = self._tk_token(e.keysym)
            if t:
                state["held"].discard(t)
            if not state["held"] and state["best"]:
                finish(state["best"])

        try:
            self.app.hk.suspended = True
        except Exception:
            pass
        dlg.bind("<KeyPress>", on_press)
        dlg.bind("<KeyRelease>", on_release)
        dlg.grab_set()
        dlg.focus_force()

    # ── Dictionary ──
    def _sec_dictionary(self):
        self._heading("Dictionary",
                      "Words the AI cleanup must always spell correctly.")
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="both", expand=True, padx=34, pady=4)
        lb = tk.Listbox(wrap, bg=CARD, fg=TEXT, selectbackground=ACCENT,
                        selectforeground="white", relief="flat",
                        highlightthickness=1, highlightbackground=CARD_BORDER,
                        font=(_F, 10), activestyle="none")
        lb.pack(side="left", fill="both", expand=True)
        for term in self.cfg.dictionary:
            lb.insert("end", term)
        self._dict_lb = lb
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", padx=34, pady=(8, 18))
        ent = tk.Entry(row, bg="#151924", fg=TEXT, insertbackground=TEXT,
                       relief="flat", font=(_F, 10))
        ent.pack(side="left", fill="x", expand=True, ipady=6, ipadx=8)
        self._dict_entry = ent
        ent.bind("<Return>", lambda e: self._dict_add())
        tk.Button(row, text="Add", command=self._dict_add, **_BTN
                  ).pack(side="left", padx=(8, 0))
        tk.Button(row, text="Remove", command=self._dict_remove, **_BTN_DANGER
                  ).pack(side="left", padx=6)

    def _dict_save(self):
        self.cfg.dictionary = list(self._dict_lb.get(0, "end"))
        self.cfg.save()
        if self.app.llm is not None:
            self.app.llm.terms = self.cfg.dictionary

    def _dict_add(self):
        term = self._dict_entry.get().strip()
        if term and term not in self._dict_lb.get(0, "end"):
            self._dict_lb.insert("end", term)
            self._dict_save()
        self._dict_entry.delete(0, "end")

    def _dict_remove(self):
        sel = self._dict_lb.curselection()
        if sel:
            self._dict_lb.delete(sel[0])
            self._dict_save()

    # ── About ──
    def _sec_about(self):
        self._heading("About")
        body = (
            "Plyrium Echo — Wispr-style push-to-talk dictation that runs "
            "100% on your machine.\n\n"
            "Your voice and your text never leave this computer. Transcription "
            "(Whisper) and the AI cleanup both run locally; the only time the "
            "network is touched is the one-time model download.\n\n"
            f"Hold  {self.cfg.hotkey}  to talk.   Tap  {self.cfg.handsfree_hotkey}  "
            "for hands-free.   Esc cancels.\n\n"
            "Part of the Plyrium family."
        )
        tk.Label(self.content, text=body, bg=BG, fg=TEXT, justify="left",
                 wraplength=640, font=(_F, 10)).pack(anchor="w", padx=36, pady=4)
