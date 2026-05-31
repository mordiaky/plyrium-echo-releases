"""Noise gate — drop low-volume background bleed before transcription.

Push-to-talk already limits *when* we record; the gate limits *what* counts as
speech within that window. It keys on short-frame RMS energy: frames quieter
than a threshold are treated as background (speaker bleed, room noise, silence)
and zeroed, so Whisper sees mostly your voice — which, held close to the mic, is
markedly louder than audio leaking from the speakers.

Honest limits: a gate keys on *loudness*, not *source*. It reliably removes
quiet bleed and dead air, but it cannot separate your voice from speaker audio
that is just as loud. For that, headphones are the only true fix. The gate plus
Whisper's built-in VAD is the best a speaker setup can do.

Design:
  - 20 ms analysis frames at 16 kHz.
  - Adaptive threshold: noise floor estimated from the quietest frames, with a
    fixed floor and a margin above it, so it self-tunes to the room.
  - Hangover: once open, the gate stays open for a short tail so word endings
    and between-word gaps aren't chopped.
  - If almost everything is gated out (you were quiet, or only bleed was
    present), return empty so the app reports "no speech" instead of feeding
    Whisper a near-silent clip that it may hallucinate words from.
"""

from __future__ import annotations

import numpy as np

_FRAME_MS = 20


def apply_gate(
    audio: np.ndarray,
    sample_rate: int = 16000,
    threshold: float = 0.015,
    margin_db: float = 9.0,
    hangover_ms: int = 200,
    min_voiced_ratio: float = 0.04,
) -> np.ndarray:
    """Return ``audio`` with sub-threshold frames zeroed.

    threshold        : absolute RMS floor (0..1). Frames below max(threshold,
                       adaptive floor) are gated. Raise to be more aggressive.
    margin_db        : how far above the estimated noise floor a frame must be
                       to count as voice.
    hangover_ms      : keep the gate open this long after the last voiced frame.
    min_voiced_ratio : if fewer than this fraction of frames pass, return empty
                       (treat the whole clip as background / no speech).
    """
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    n = audio.shape[0]
    if n == 0:
        return audio

    fl = max(1, int(sample_rate * _FRAME_MS / 1000))
    n_frames = (n + fl - 1) // fl
    pad = n_frames * fl - n
    if pad:
        audio = np.concatenate([audio, np.zeros(pad, dtype=np.float32)])
    frames = audio.reshape(n_frames, fl)

    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)) + 1e-9

    # Adaptive noise floor: 20th percentile of frame energy (the quiet frames),
    # lifted by the margin. Capped at half the median frame energy so a clip
    # that is *uniformly* loud (continuous close speech) isn't gated to nothing.
    floor = float(np.percentile(rms, 20))
    median = float(np.percentile(rms, 50))
    adaptive = min(floor * (10.0 ** (margin_db / 20.0)), 0.5 * median)
    thr = max(threshold, adaptive)

    voiced = rms >= thr

    # Hangover: extend each voiced run forward so tails aren't clipped.
    hang = max(1, int(hangover_ms / _FRAME_MS))
    out_mask = voiced.copy()
    countdown = 0
    for i in range(n_frames):
        if voiced[i]:
            countdown = hang
        elif countdown > 0:
            out_mask[i] = True
            countdown -= 1

    if out_mask.mean() < min_voiced_ratio:
        return np.zeros(0, dtype=np.float32)  # essentially nothing above the floor

    gated = frames * out_mask[:, None]
    return gated.reshape(-1)[:n].astype(np.float32)
