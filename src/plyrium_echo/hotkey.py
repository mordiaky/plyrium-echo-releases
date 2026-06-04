"""Global hotkeys: hold-to-talk plus a hands-free toggle.

Dead simple and robust: it relies entirely on pynput's press/release events
(proven to deliver reliably in the user's session) — no GetAsyncKeyState
watchdog, no background polling threads. An earlier watchdog meant to catch a
swallowed Win-key-up introduced a lock race that silently killed recording in
the packaged exe; removing it is the fix.

  push-to-talk : hold the combo (default Ctrl+Win) -> record; release -> stop.
  hands-free   : tap the toggle combo (default Ctrl+Win+Space) -> start; tap
                 again -> stop.
  Esc          : cancel an in-progress recording.

Set PLYRIUM_ECHO_DEBUG=1 to log every key event + decision to
plyrium-echo-hotkey.log in the temp dir — used to diagnose the real app live.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

try:
    from pynput import keyboard
except Exception:  # pragma: no cover - Linux CI may not have an X display.
    keyboard = None

_DEBUG = os.environ.get("PLYRIUM_ECHO_DEBUG") == "1"
_LOGPATH = Path(tempfile.gettempdir()) / "plyrium-echo-hotkey.log"


def _dbg(msg: str) -> None:
    if not _DEBUG:
        return
    try:
        with open(_LOGPATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except Exception:
        pass


def _norm(key) -> Optional[str]:
    """Normalize a pynput key to a canonical name (left/right merged)."""
    if keyboard is None:
        return None
    if isinstance(key, keyboard.KeyCode):
        return key.char.lower() if key.char else None
    name = getattr(key, "name", None)
    if name is None:
        return None
    if name.startswith("ctrl"):
        return "ctrl"
    if name.startswith("alt"):
        return "alt"
    if name.startswith("shift"):
        return "shift"
    if name in ("cmd", "cmd_l", "cmd_r"):
        return "win"
    return name


_ALIASES = {"win": "win", "cmd": "win", "super": "win", "meta": "win",
            "control": "ctrl", "option": "alt"}


def parse_combo(spec: str) -> frozenset[str]:
    """'ctrl+win' -> frozenset({'ctrl','win'}); 'f9' -> frozenset({'f9'})."""
    keys = set()
    for part in (spec or "").lower().replace(" ", "").split("+"):
        if part:
            keys.add(_ALIASES.get(part, part))
    return frozenset(keys)


def parse_combo_list(spec: str | Iterable[str] | None) -> tuple[frozenset[str], ...]:
    """Accept one combo, comma/semicolon separated combos, or a list of combos."""
    if spec is None:
        return tuple()
    if isinstance(spec, str):
        raw = spec.replace(";", ",").split(",")
    else:
        raw = list(spec)
    combos = []
    seen = set()
    for item in raw:
        combo = parse_combo(str(item))
        if combo and combo not in seen:
            combos.append(combo)
            seen.add(combo)
    return tuple(combos)


class HotkeyManager:
    def __init__(
        self,
        ptt: str | Iterable[str],
        handsfree: str | Iterable[str] | None,
        on_start: Callable[[str], None],
        on_stop: Callable[[], None],
        on_cancel: Callable[[], None] | None = None,
    ):
        self.ptt_combos = parse_combo_list(ptt)
        self.hf_combos = parse_combo_list(handsfree)
        self.ptt_keys = self.ptt_combos[0] if self.ptt_combos else frozenset()
        self.hf_keys = self.hf_combos[0] if self.hf_combos else frozenset()
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_cancel = on_cancel

        self.pressed: set[str] = set()
        self.recording = False
        self.suspended = False            # paused while the user records a new combo
        self.mode: str | None = None      # "ptt" | "hf"
        self._hf_held = False             # HF combo currently fully down (edge detect)
        self._listener: keyboard.Listener | None = None
        _dbg(f"INIT ptt={list(map(set, self.ptt_combos))} "
             f"hf={list(map(set, self.hf_combos))}")

    # ── event handling ───────────────────────────────────────────
    def _press(self, key) -> None:
        if self.suspended:
            return
        n = _norm(key)
        if n is None:
            return
        if n == "esc" and self.recording:
            _dbg("ESC -> cancel")
            self.recording = False
            self.mode = None
            self._safe(self._on_cancel) if self._on_cancel else None
            return
        self.pressed.add(n)
        _dbg(f"PRESS {n}  held={sorted(self.pressed)}")
        self._evaluate()

    def _release(self, key) -> None:
        if self.suspended:
            return
        n = _norm(key)
        if n is None:
            return
        self.pressed.discard(n)
        _dbg(f"REL   {n}  held={sorted(self.pressed)}")
        self._evaluate()

    def _evaluate(self) -> None:
        hf_now = self._any_combo_down(self.hf_combos)
        ptt_now = self._any_combo_down(self.ptt_combos)

        # Hands-free: toggle on the rising edge of its combo.
        if hf_now and not self._hf_held:
            self._hf_held = True
            self._toggle_handsfree()
            return
        if not hf_now:
            self._hf_held = False

        # Push-to-talk: active while the combo is held (and not in HF mode).
        ptt_active = ptt_now and not hf_now and self.mode != "hf"
        if ptt_active and not self.recording:
            self.recording = True
            self.mode = "ptt"
            _dbg(">>> START ptt")
            self._safe(self._on_start, "ptt")
        elif self.recording and self.mode == "ptt" and not ptt_active:
            self.recording = False
            self.mode = None
            _dbg(">>> STOP ptt")
            self._safe(self._on_stop)

    def _toggle_handsfree(self) -> None:
        if self.recording and self.mode == "ptt":
            self.mode = "hf"            # seamless PTT -> hands-free
            _dbg("PTT -> HF")
        elif self.recording and self.mode == "hf":
            self.recording = False
            self.mode = None
            _dbg(">>> STOP hf")
            self._safe(self._on_stop)
        else:
            self.recording = True
            self.mode = "hf"
            _dbg(">>> START hf")
            self._safe(self._on_start, "hf")

    def _any_combo_down(self, combos: tuple[frozenset[str], ...]) -> bool:
        return any(combo <= self.pressed for combo in combos)

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except Exception as exc:  # pragma: no cover
            _dbg(f"CALLBACK ERROR: {exc!r}")
            print(f"[hotkey] callback error: {exc}", flush=True)

    # ── lifecycle ────────────────────────────────────────────────
    def run(self) -> None:
        if keyboard is None:
            raise RuntimeError("pynput keyboard backend is unavailable")
        with keyboard.Listener(on_press=self._press, on_release=self._release) as ll:
            self._listener = ll
            ll.join()

    def start(self) -> keyboard.Listener:
        if keyboard is None:
            raise RuntimeError("pynput keyboard backend is unavailable")
        self._listener = keyboard.Listener(on_press=self._press,
                                           on_release=self._release)
        self._listener.start()
        _dbg("LISTENER started")
        return self._listener
