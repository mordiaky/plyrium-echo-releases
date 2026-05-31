"""Deliver transcribed text to the user.

Default mode pastes the text into whatever window currently has focus — fast and
reliable, the way Wispr Flow does it: stash the current clipboard, set it to the
transcript, send Ctrl+V, then restore the previous clipboard. Typing
character-by-character is kept as a fallback for apps that mishandle paste.
"""

from __future__ import annotations

import time

from pynput.keyboard import Controller, Key


class TextOutput:
    def __init__(self, mode: str = "paste", type_delay: float = 0.0,
                 restore_delay: float = 0.15):
        """``mode``: ``paste`` | ``type`` | ``clipboard`` | ``both``.

        ``restore_delay`` is how long to wait after Ctrl+V before restoring the
        previous clipboard — too short and the target app pastes the old value.
        """
        self.mode = mode
        self.type_delay = type_delay
        self.restore_delay = restore_delay
        self._kbd = Controller()

    def deliver(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        out = text + " "  # trailing space so consecutive dictations don't merge
        if self.mode == "type":
            self._type(out)
        elif self.mode == "clipboard":
            self._set_clipboard(out)
        elif self.mode == "both":
            self._set_clipboard(out)
            self._type(out)
        else:  # "paste" (default)
            self._paste(out)

    def _paste(self, text: str) -> None:
        try:
            import pyperclip
        except Exception as exc:  # pragma: no cover
            print(f"[output] clipboard unavailable ({exc}); typing instead", flush=True)
            self._type(text)
            return
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = ""
        pyperclip.copy(text)
        # Small beat so the clipboard write lands before we paste.
        time.sleep(0.02)
        with self._kbd.pressed(Key.ctrl):
            self._kbd.press("v")
            self._kbd.release("v")
        time.sleep(self.restore_delay)
        try:
            pyperclip.copy(previous)
        except Exception:
            pass

    def _type(self, text: str) -> None:
        if self.type_delay > 0:
            for ch in text:
                self._kbd.type(ch)
                time.sleep(self.type_delay)
        else:
            self._kbd.type(text)

    @staticmethod
    def _set_clipboard(text: str) -> None:
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception as exc:  # pragma: no cover
            print(f"[output] clipboard unavailable: {exc}", flush=True)
