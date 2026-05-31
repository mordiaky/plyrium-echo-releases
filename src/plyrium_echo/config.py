"""Configuration loading.

In a dev checkout, settings live in ``config.json`` at the project root. When
distributed (frozen exe), the live config lives in the user-writable data dir
(``%LOCALAPPDATA%\\Plyrium Echo\\config.json``) because the install dir is
read-only; the ``config.json`` shipped inside the exe seeds the defaults on
first run. An optional ``config.local.json`` (dev only) overrides on top.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULTS: dict = {
    # Whisper model. "large-v3-turbo" = best accuracy, fast on GPU (the local
    # closest to Wispr). "medium.en"/"small.en"/"base.en"/"tiny.en" are smaller
    # & lighter. On CPU prefer small.en.
    "model_size": "large-v3-turbo",
    # Beam search width. 5 = more accurate word choices (negligible cost on GPU);
    # 1 = greedy/fastest.
    "beam_size": 5,
    # auto | cuda | cpu  (auto = GPU when available, else CPU)
    "device": "auto",
    # auto | float16 | int8 | int8_float16  (auto picks per device)
    "compute_type": "auto",
    "language": "en",
    # Hold-to-talk combo, and tap-to-toggle hands-free combo (null to disable).
    "hotkey": "ctrl+win",
    "handsfree_hotkey": "ctrl+win+space",
    # paste | type | clipboard | both
    "output_mode": "paste",
    "type_delay": 0.0,
    # Wispr-style cleanup on top of Whisper: filler removal + backtrack.
    "smart_format": True,
    # Drop the trailing period in chat apps (Slack/Discord/etc.), like Wispr.
    "chat_apps_no_period": True,
    # Floating "echo" pill indicator.
    "overlay": True,
    # Noise gate: drop low-volume background before transcription. Keys on
    # loudness, not source — helps quiet bleed, NOT equally-loud system audio.
    "noise_gate": True,
    "gate_threshold": 0.015,
    "input_device": None,
    "min_seconds": 0.3,
    # Dip other system audio while you hold the key so the mic focuses on your
    # voice (Wispr does this; it mutes, we dip). Restored exactly on release.
    "duck_audio": True,
    # Output volume while dictating, as a fraction (0.25 = 25%). Not a mute.
    "duck_level": 0.25,
    # LLM cleanup (Wispr-style 2nd pass via local Ollama). Fixes proper nouns
    # from context, punctuation, filler. Falls back to deterministic format if
    # Ollama/model isn't available. 100% offline once the model is pulled.
    "llm_cleanup": True,
    "llm_model": "qwen2.5:3b",
    # How long Ollama keeps the model in VRAM after a dictation. "5m" keeps it
    # warm for bursts of dictation, then frees the GPU.
    "llm_keep_alive": "5m",
    # Proper nouns / vocab the LLM must spell correctly (your dictionary).
    "dictionary": ["Plyrium", "Forge", "Plyrium Echo", "Plyrium Forge"],
    # Local dictation history (text only, stored on this machine, never sent
    # anywhere). Off = nothing is ever written. Capped to the newest N entries.
    "history_enabled": True,
    "history_max_entries": 500,
    # Where the "Buy a license" button points (your Stripe Payment Link / site).
    "buy_url": "https://buy.stripe.com/28EfZiaUn4NvaK3e0GdfG00",
    # Auto-detect an NVIDIA GPU and fetch+load CUDA on demand for the heavy
    # models (one-time download). Off = stay on CPU / manual enable only.
    "auto_gpu": True,
}


@dataclass
class Config:
    model_size: str
    beam_size: int
    device: str
    compute_type: str
    language: str
    hotkey: str
    handsfree_hotkey: object
    output_mode: str
    type_delay: float
    smart_format: bool
    chat_apps_no_period: bool
    overlay: bool
    noise_gate: bool
    gate_threshold: float
    input_device: object
    min_seconds: float
    duck_audio: bool
    duck_level: float
    llm_cleanup: bool
    llm_model: str
    llm_keep_alive: str
    dictionary: list
    history_enabled: bool
    history_max_entries: int
    buy_url: str
    auto_gpu: bool
    _raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        data = dict(DEFAULTS)
        # Defaults shipped inside the exe (read-only) seed first.
        for root in paths.bundled_roots():
            seed = root / "config.json"
            if seed.exists():
                data.update(_read_json(seed))
                break
        # The user's live, writable config wins.
        main = path or paths.config_path()
        first_run = not main.exists()
        if main.exists():
            data.update(_read_json(main))
        # Dev-only machine override.
        if not getattr(sys, "frozen", False):
            local = PROJECT_ROOT / "config.local.json"
            if local.exists():
                data.update(_read_json(local))
        # Fresh install with no model chosen yet: pick a sane default for the
        # detected hardware (big/accurate on GPU, small/fast on CPU).
        if first_run and getattr(sys, "frozen", False):
            data["model_size"] = default_model_for_device()
        known = {k: data.get(k, DEFAULTS[k]) for k in DEFAULTS}
        return cls(**known, _raw=data)

    def save(self, path: Path | None = None) -> None:
        """Persist current values to the user-writable config (tray menu uses this)."""
        target = path or paths.config_path()
        out = {k: getattr(self, k) for k in DEFAULTS}
        try:
            target.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"[config] could not save settings: {exc}", flush=True)


def default_model_for_device() -> str:
    """Best default for the hardware: large only when CUDA can truly RUN,
    otherwise the fast small model (CPU, or NVIDIA before the GPU pack is
    provisioned, or AMD/Intel/no-GPU)."""
    try:
        from .model import cuda_usable

        return "large-v3-turbo" if cuda_usable() else "small.en"
    except Exception:
        return "small.en"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to read config {path}: {exc}")
