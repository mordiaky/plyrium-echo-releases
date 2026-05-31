"""Audio ducking — gently lower OTHER audio while you dictate (like Wispr).

When recording starts, the system output volume dips to ``level`` (e.g. 25%) so
your speakers' audio doesn't compete with your voice; on stop it's restored to
the EXACT level it was before. It's a dip, not a mute — Wispr's Windows default
mutes, but the user wants the gentler dip.

Hard-won lesson: the earlier *mute* version once failed to restore and left
audio stuck. This version is built so restore is bulletproof:
  - The pre-dip volume is captured ONCE per dip (re-ducking while already
    ducked won't overwrite the saved value with an already-dipped one).
  - ``restore()`` is idempotent and always safe to call — on stop, on cancel,
    on shutdown, even after an error.
  - Every COM call is wrapped; audio control can never break dictation.
  - It's a dip, so the worst conceivable failure is "a bit quieter," never
    "silent forever."
"""

from __future__ import annotations

import threading


class AudioDucker:
    def __init__(self, enabled: bool = True, level: float = 0.25):
        self.enabled = enabled
        self.level = max(0.0, min(1.0, level))
        self._saved: float | None = None   # pre-dip volume; None = not ducking
        self._lock = threading.Lock()
        self._vol = None
        if enabled:
            try:
                from pycaw.pycaw import AudioUtilities

                self._vol = AudioUtilities.GetSpeakers().EndpointVolume
            except Exception as exc:  # pragma: no cover - no audio endpoint
                print(f"[duck] volume control unavailable: {exc}", flush=True)
                self.enabled = False

    def duck(self) -> None:
        if not self.enabled or self._vol is None:
            return
        with self._lock:
            if self._saved is not None:
                return  # already ducking; don't recapture the dipped level
            try:
                cur = float(self._vol.GetMasterVolumeLevelScalar())
            except Exception:
                return
            # Only dip if current is above the target (don't *raise* quiet audio).
            if cur <= self.level:
                self._saved = None
                return
            self._saved = cur
            try:
                self._vol.SetMasterVolumeLevelScalar(self.level, None)
            except Exception:
                self._saved = None  # couldn't dip — nothing to restore

    def restore(self) -> None:
        if self._vol is None:
            return
        with self._lock:
            if self._saved is None:
                return
            try:
                self._vol.SetMasterVolumeLevelScalar(self._saved, None)
            except Exception:
                pass
            finally:
                self._saved = None
