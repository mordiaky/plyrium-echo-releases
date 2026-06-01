"""System-tray icon (Wispr-style) + full settings menu, built on pystray.

Everything is controllable from here — no editing config.json. Model size,
output mode, audio ducking, formatting, overlay, AI cleanup, and start-with-
Windows all live-apply and persist. The icon recolors by state (white idle,
red recording, amber transcribing, gray paused).

pystray runs detached on its own thread (``run_detached``) so the Tkinter
overlay can own the main thread.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

import pystray

from . import autostart
from .icon import tray_image

# Friendly label -> Whisper model id. English-only ids (.en) are the best
# accuracy/speed trade for English dictation; large-v3-turbo is multilingual.
MODELS = [
    ("Small — fastest (good on CPU)", "small.en"),
    ("Medium — balanced", "medium.en"),
    ("Large — most accurate (GPU)", "large-v3-turbo"),
]

# Audio-ducking presets: label -> dip fraction (None = off).
DUCK_LEVELS = [
    ("Off", None),
    ("Light (40%)", 0.40),
    ("Medium (25%)", 0.25),
    ("Strong (15%)", 0.15),
]


def build_tray(app) -> "pystray.Icon":
    def _notify(icon, msg: str) -> None:
        try:
            icon.notify(msg, "Plyrium Echo")
        except Exception:
            pass

    def _status_text(_item):
        t = app.transcriber
        state = "paused" if app.paused else "ready"
        lic = app.license.status_text()
        return (f"Plyrium Echo — {state} ({t.model_size}, "
                f"{t.device}/{t.compute_type}) · {lic}")

    def _toggle_pause(icon, item):
        app.toggle_pause()
        icon.icon = tray_image("paused" if app.paused else "idle")

    # ── model ──
    def _make_model_setter(size):
        def _set(icon, item):
            if size == app.cfg.model_size:
                return

            def work():
                app.reload_model(size, notify=lambda m: _notify(icon, m))
                try:
                    icon.update_menu()
                except Exception:
                    pass

            threading.Thread(target=work, daemon=True).start()
        return _set

    model_menu = pystray.Menu(*[
        pystray.MenuItem(label, _make_model_setter(size),
                         checked=(lambda s: (lambda item: app.cfg.model_size == s))(size),
                         radio=True)
        for label, size in MODELS
    ])

    # ── output mode ──
    def _make_mode_setter(mode):
        return lambda icon, item: app.set_output_mode(mode)

    output_menu = pystray.Menu(
        pystray.MenuItem("Paste (recommended)", _make_mode_setter("paste"),
                         checked=lambda i: app.cfg.output_mode == "paste", radio=True),
        pystray.MenuItem("Type", _make_mode_setter("type"),
                         checked=lambda i: app.cfg.output_mode == "type", radio=True),
        pystray.MenuItem("Clipboard only", _make_mode_setter("clipboard"),
                         checked=lambda i: app.cfg.output_mode == "clipboard", radio=True),
    )

    # ── audio ducking ──
    def _duck_checked(level):
        def _c(item):
            if level is None:
                return not app.cfg.duck_audio
            return app.cfg.duck_audio and abs(app.cfg.duck_level - level) < 0.001
        return _c

    def _make_duck_setter(level):
        return lambda icon, item: app.set_duck(level)

    duck_menu = pystray.Menu(*[
        pystray.MenuItem(label, _make_duck_setter(level),
                         checked=_duck_checked(level), radio=True)
        for label, level in DUCK_LEVELS
    ])

    # ── simple toggles ──
    def _toggle_smart(icon, item):
        app.set_smart_format(not app.cfg.smart_format)

    def _toggle_chat(icon, item):
        app.set_chat_period(not app.cfg.chat_apps_no_period)

    def _toggle_overlay(icon, item):
        app.set_overlay(not app.cfg.overlay)

    def _toggle_llm(icon, item):
        app.set_llm_cleanup(not app.cfg.llm_cleanup)

    def _llm_label(item):
        base = "AI cleanup (Ollama)"
        if app.cfg.llm_cleanup and not app.llm_available():
            return base + " — not found"
        return base

    def _toggle_autostart(icon, item):
        autostart.set_enabled(not autostart.is_enabled())

    def _open_data_folder(icon, item):
        from . import paths
        folder = str(paths.data_dir())
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606 (Windows shell open)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _about(icon, item):
        app.open_about()

    def _show_window(icon, item):
        app.open_window()

    def _quit(icon, item):
        app.shutdown()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(_status_text, None, enabled=False),
        pystray.Menu.SEPARATOR,
        # default=True → double-clicking the tray icon opens the window (like Wispr's "Show").
        pystray.MenuItem("Show Plyrium Echo", _show_window, default=True),
        pystray.MenuItem(lambda item: "Resume" if app.paused else "Pause",
                         _toggle_pause),
        pystray.MenuItem("Model", model_menu),
        pystray.MenuItem("Output mode", output_menu),
        pystray.MenuItem("Lower other audio while talking", duck_menu),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Smart formatting", _toggle_smart,
                         checked=lambda i: app.cfg.smart_format),
        pystray.MenuItem("Drop period in chat apps", _toggle_chat,
                         checked=lambda i: app.cfg.chat_apps_no_period),
        pystray.MenuItem("Show waveform overlay", _toggle_overlay,
                         checked=lambda i: app.cfg.overlay),
        pystray.MenuItem(_llm_label, _toggle_llm,
                         checked=lambda i: app.cfg.llm_cleanup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", _toggle_autostart,
                         checked=lambda i: autostart.is_enabled()),
        pystray.MenuItem("Open data folder", _open_data_folder),
        pystray.MenuItem("About", _about),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit),
    )

    icon = pystray.Icon("plyrium-echo", tray_image("idle"), "Plyrium Echo", menu)

    def _on_state(state: str) -> None:
        try:
            icon.icon = tray_image(state)
        except Exception:
            pass

    app.set_state_callback(_on_state)
    return icon
