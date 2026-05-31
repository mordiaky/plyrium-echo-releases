"""Microphone capture for push-to-talk.

Records 16 kHz mono float32 audio (the format Whisper expects) into an
in-memory buffer between ``start()`` and ``stop()``.

Device selection (the "it captured my YouTube" / "won't record" fix)
-------------------------------------------------------------------
Two real problems collided here:
  1. The legacy **MME** "Microphone Array" endpoint on this Realtek driver hands
     back a stream that includes desktop audio (transcribes whatever's playing).
  2. **WASAPI** is the clean endpoint Wispr uses, but PortAudio (what sounddevice
     wraps) *cannot open* WASAPI on this machine ("Unanticipated host error").

So picking a single device is fragile. Instead we build an ORDERED list of
candidate devices and, at record time, open the FIRST one that actually starts a
stream — preferring host APIs that bind the real mic (WASAPI, DirectSound, WDM-KS)
over MME. An explicit ``input_device`` in config always wins and is tried first.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1

_DEBUG = os.environ.get("PLYRIUM_ECHO_DEBUG") == "1"
_LOGPATH = Path(tempfile.gettempdir()) / "plyrium-echo-audio.log"


def _audio_dbg(msg: str) -> None:
    if not _DEBUG:
        return
    try:
        with open(_LOGPATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')}  {msg}\n")
    except Exception:
        pass

# Host-API preference: real-mic-binding APIs first, MME (mixes/bleeds) last.
_HOSTAPI_RANK = {"Windows WASAPI": 0, "Windows DirectSound": 1,
                 "Windows WDM-KS": 2, "MME": 9}
_MIC_HINTS = ("microphone", "mic")
_SKIP_HINTS = ("stereo mix", "what u hear", "wave out", "loopback",
               "sound mapper", "primary sound")


def _normalize_gain(audio: np.ndarray, target_peak: float = 0.95,
                    floor: float = 0.002, max_gain: float = 30.0) -> np.ndarray:
    """Boost quiet mic audio so Whisper hears it clearly (helps laptop mics).

    Built-in mic arrays (especially via DirectSound) often capture at a low
    level; Whisper transcribes loud, clear speech far better than faint speech.
    We scale the peak up toward ``target_peak`` — but only when there's real
    signal (peak above ``floor``), so we don't amplify near-silence into noise
    that Whisper would hallucinate words from. Gain is capped so a faint clip
    isn't blown up absurdly.
    """
    if audio.size == 0:
        return audio
    peak = float(np.abs(audio).max())
    if peak < floor:
        return audio  # essentially silence — leave it; VAD will drop it
    gain = min(target_peak / peak, max_gain)
    if gain <= 1.0:
        return audio  # already loud enough
    return np.clip(audio * gain, -1.0, 1.0).astype(np.float32)


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Linear resample mono float32 from ``src`` to ``dst`` Hz."""
    if src == dst or audio.size == 0:
        return audio.astype(np.float32)
    n_dst = int(round(audio.shape[0] * dst / src))
    if n_dst <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, num=audio.shape[0], endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_dst, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def _default_input_device():
    """Return PortAudio's current default input device index, if usable."""
    try:
        default = sd.default.device
        idx = default[0] if isinstance(default, (list, tuple)) else default
        if idx is None or int(idx) < 0:
            return None
        d = sd.query_devices(int(idx))
        if d.get("max_input_channels", 0) <= 0:
            return None
        return int(idx)
    except Exception:
        return None


def candidate_devices(explicit=None) -> list:
    """Ordered list of input device indices to try, best first.

    Explicit config device is always first. Then the current Windows/PortAudio
    default input, then real microphones ranked by host API (WASAPI >
    DirectSound > WDM-KS > MME), skipping loopback/mapper pseudo-devices.
    start() opens the first that actually works.
    """
    order: list = []
    if explicit is not None:
        order.append(explicit)
    default = _default_input_device()
    if default is not None and default not in order:
        order.append(default)

    rows = []
    try:
        devs = sd.query_devices()
    except Exception:
        return order
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) <= 0:
            continue
        name = d["name"].lower()
        if any(h in name for h in _SKIP_HINTS):
            continue
        try:
            host = sd.query_hostapis(d["hostapi"])["name"]
        except Exception:
            host = ""
        rank = _HOSTAPI_RANK.get(host, 5)
        is_mic = any(h in name for h in _MIC_HINTS)
        # sort key: host-api rank, then prefer things named "microphone"
        rows.append((rank, 0 if is_mic else 1, i))
    rows.sort()
    for _, _, i in rows:
        if i not in order:
            order.append(i)
    return order


def resolve_input_device(device=None, prefer_wasapi: bool = True):
    """First-choice device (kept for callers that want a single index)."""
    cands = candidate_devices(device)
    return cands[0] if cands else None


def describe_device(device) -> str:
    try:
        idx = device if device is not None else sd.default.device[0]
        d = sd.query_devices(idx)
        host = sd.query_hostapis(d["hostapi"])["name"]
        return f"[{d['index']}] {d['name']} ({host})"
    except Exception:
        return f"device={device}"


class MicRecorder:
    """Captures mic audio while a push-to-talk key is held.

    Usage::

        rec = MicRecorder()
        rec.start()          # begins buffering frames
        ...                  # user speaks
        audio = rec.stop()   # returns float32 ndarray at 16 kHz, or None
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, device: int | str | None = None,
                 prefer_wasapi: bool = True):
        self.sample_rate = sample_rate            # target rate Whisper wants (16 kHz)
        self._explicit_device = device
        self._candidates = candidate_devices(device)  # refreshed on every start()
        self.device = self._candidates[0] if self._candidates else None
        self.capture_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._recording = False
        self.level = 0.0  # live RMS (0..1) of the most recent frame, for the overlay

    @staticmethod
    def _native_rate(device, target: int) -> int:
        """Return a rate the device will actually open at, preferring ``target``."""
        try:
            sd.check_input_settings(device=device, samplerate=target,
                                    channels=CHANNELS, dtype="float32")
            return target  # device accepts 16 kHz directly (e.g. MME resamples)
        except Exception:
            pass
        try:
            dr = int(round(sd.query_devices(device if device is not None
                                            else sd.default.device[0])
                           ["default_samplerate"]))
            if dr > 0:
                return dr
        except Exception:
            pass
        return 48000  # safe WASAPI default

    def _callback(self, indata, frames, time_info, status):  # noqa: ANN001
        if status:
            # Overflows etc. — not fatal, just note on stderr.
            print(f"[audio] {status}", flush=True)
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())
        # RMS for the waveform; scaled so normal speech lands near the top.
        try:
            rms = float(np.sqrt(np.mean(np.square(indata, dtype=np.float64))))
            self.level = min(1.0, rms * 8.0)
        except Exception:
            pass

    def _is_wasapi(self, device) -> bool:
        try:
            host = sd.query_hostapis(sd.query_devices(device)["hostapi"])["name"]
            return "WASAPI" in host
        except Exception:
            return False

    def _attempts(self, device):
        """Yield (label, samplerate, extra_settings) open strategies for a device.

        WASAPI shared mode needs auto_convert to accept 16 kHz / mono — this is
        the native-style path. We try that first, then plain native rate, then
        plain 16 kHz, so the best-quality clean open wins.
        """
        try:
            nr = int(round(sd.query_devices(device)["default_samplerate"])) or 48000
        except Exception:
            nr = 48000
        if self._is_wasapi(device):
            auto = None
            try:
                auto = sd.WasapiSettings(auto_convert=True)
            except Exception:
                auto = None
            if auto is not None:
                yield ("wasapi+autoconvert 16k", self.sample_rate, auto)
            yield ("wasapi native", nr, None)
        else:
            yield ("plain 16k", self.sample_rate, None)
            if nr != self.sample_rate:
                yield ("plain native", nr, None)

    def _open_stream(self, device):
        """Open ``device`` via its strategies; return capture rate or raise."""
        last = None
        for label, sr, extra in self._attempts(device):
            try:
                stream = sd.InputStream(
                    samplerate=sr, channels=CHANNELS, dtype="float32",
                    device=device, callback=self._callback, extra_settings=extra,
                )
                stream.start()
                self._stream = stream
                _audio_dbg(f"OPEN ok  {describe_device(device)} [{label}] @ {sr}Hz")
                return sr
            except Exception as exc:
                last = exc
                _audio_dbg(f"OPEN FAIL {describe_device(device)} [{label}] "
                           f"@ {sr}Hz -> {exc!r}")
        raise last if last else RuntimeError("no strategy worked")

    def start(self) -> None:
        if self._recording:
            return
        with self._lock:
            self._frames = []
            self._recording = True
        # Audio devices can change while Echo stays open. Refresh every
        # recording so switching the Windows default mic does not require a
        # relaunch, while still trying an explicit configured device first.
        self._candidates = candidate_devices(self._explicit_device)
        # Try each candidate device until one actually opens. Full per-attempt
        # detail goes to the debug log (PLYRIUM_ECHO_DEBUG=1).
        errors = []
        for dev in self._candidates or [None]:
            try:
                self.capture_rate = self._open_stream(dev)
                self.device = dev
                _audio_dbg(f"RECORDING on {describe_device(dev)} @ {self.capture_rate}Hz")
                return
            except Exception as exc:
                errors.append(f"{describe_device(dev)}: {exc!r}")
        with self._lock:
            self._recording = False
        msg = "no input device could be opened -> " + " | ".join(errors)
        _audio_dbg("START FAILED: " + msg)
        raise RuntimeError(msg)

    def stop(self) -> np.ndarray | None:
        """Stop recording and return the captured mono float32 audio.

        Returns ``None`` if nothing usable was recorded.
        """
        if not self._recording:
            return None
        with self._lock:
            self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return None
        audio = np.concatenate(frames, axis=0).reshape(-1).astype(np.float32)
        if audio.size == 0:
            return None
        if self.capture_rate != self.sample_rate:
            audio = _resample(audio, self.capture_rate, self.sample_rate)
        audio = _normalize_gain(audio)
        return audio

    @staticmethod
    def list_devices() -> str:
        return str(sd.query_devices())


def load_wav_16k_mono(path: str) -> np.ndarray:
    """Read a WAV file and return mono float32 samples at 16 kHz.

    Handles 8/16/32-bit PCM, downmixes to mono, and linearly resamples to
    16 kHz if needed. Used by ``run.py --file`` for mic-free transcription.
    """
    import wave

    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sampwidth} bytes")

    if n_channels > 1:
        data = data.reshape(-1, n_channels).mean(axis=1)

    if rate != SAMPLE_RATE and data.size:
        duration = data.shape[0] / float(rate)
        new_len = int(round(duration * SAMPLE_RATE))
        if new_len > 0:
            x_old = np.linspace(0.0, duration, num=data.shape[0], endpoint=False)
            x_new = np.linspace(0.0, duration, num=new_len, endpoint=False)
            data = np.interp(x_new, x_old, data)
    return data.astype(np.float32)
