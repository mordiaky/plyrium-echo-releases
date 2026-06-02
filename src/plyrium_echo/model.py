"""Speech-to-text via faster-whisper (Whisper, one model, offline).

One model does the whole job: Whisper transcribes AND outputs punctuation,
capitalization, and sentence spacing natively — no separate punctuation model,
no PyTorch. Inference runs on CTranslate2:

  - GPU (CUDA, float16) when an NVIDIA card + the CUDA pip wheels are present.
    Measured ~34x realtime on an RTX 5080.
  - CPU (int8) otherwise. Measured ~6x realtime — still well under a second for a
    short dictation.

Offline: the model is downloaded from HuggingFace once (run.py --download-model,
also run by setup.ps1), then loaded from the local cache. run.py forces
HF_HUB_OFFLINE so nothing touches the network at runtime.

Windows CUDA quirk: CTranslate2 loads cublas/cudnn at the C level, which ignores
Python's DLL search path. ``_ensure_cuda_dlls`` copies the CUDA DLLs from the
nvidia-*-cu12 wheels into CTranslate2's own package dir (where its loader looks),
so GPU works with zero system-wide CUDA install. It's a copy-if-missing no-op
once done.
"""

from __future__ import annotations

import glob
import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_MODEL = "small.en"
CPU_PREFERRED_MODELS = {"tiny", "tiny.en", "base", "base.en", "small", "small.en"}


@dataclass
class ModelInfo:
    kind: str  # "whisper" | "unknown"
    model_size: str = ""
    device: str = ""
    compute_type: str = ""
    note: str = ""


def _ensure_cuda_dlls() -> None:
    """Make CUDA DLLs loadable: add the on-demand GPU pack to the search path
    (slim build), and in the full/dev build copy the nvidia-wheel DLLs next to
    CTranslate2's loader."""
    try:
        from . import cuda_provision
        cuda_provision.activate()      # slim build: provisioned GPU pack on PATH
    except Exception:
        pass
    try:
        spec = importlib.util.find_spec("ctranslate2")
        if not spec or not spec.origin:
            return
        ct2_dir = Path(spec.origin).parent
        if (ct2_dir / "cublas64_12.dll").exists():
            return  # already done
        nvidia = ct2_dir.parent / "nvidia"
        if not nvidia.exists():
            return  # CPU-only install; nothing to copy
        for dll in glob.glob(str(nvidia / "*" / "bin" / "*.dll")):
            dst = ct2_dir / Path(dll).name
            if not dst.exists():
                try:
                    shutil.copy2(dll, dst)
                except Exception:
                    pass
    except Exception:
        pass


def _cuda_available() -> bool:
    """An NVIDIA device is visible (driver present). Does NOT mean usable."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _cublas_present() -> bool:
    """Is the CUDA runtime (cuBLAS) actually loadable? A visible device isn't
    enough — without cuBLAS/cuDNN, a cuda load fails and falls back to CPU. We
    check the places the DLL can live: bundled (full build), provisioned dir
    (GPU pack), or the normal DLL search path."""
    import ctypes
    import importlib.util
    from pathlib import Path

    try:
        spec = importlib.util.find_spec("ctranslate2")
        if spec and spec.origin and (Path(spec.origin).parent / "cublas64_12.dll").exists():
            return True
    except Exception:
        pass
    try:
        from . import paths
        if (paths.data_dir() / "cuda" / "cublas64_12.dll").exists():
            return True
    except Exception:
        pass
    try:
        ctypes.WinDLL("cublas64_12.dll")   # searches PATH + added dll dirs
        return True
    except Exception:
        return False


def cuda_usable() -> bool:
    """True only when CUDA can actually RUN (device present AND cuBLAS loadable)."""
    return _cuda_available() and _cublas_present()


def _resolve(device: str, compute_type: str) -> tuple[str, str]:
    dev = device
    if dev == "auto":
        dev = "cuda" if cuda_usable() else "cpu"
    comp = compute_type
    if comp == "auto":
        comp = "float16" if dev == "cuda" else "int8"
    return dev, comp


def resolve_runtime(model_size: str, device: str, compute_type: str) -> tuple[str, str]:
    """Resolve the runtime for a model.

    Small Whisper variants are selected for CPU speed/low overhead. Keeping
    them on CPU also frees the GPU for local cleanup models and avoids the UI
    saying "small" while the status badge still reads CUDA.
    """
    if (model_size or "").lower() in CPU_PREFERRED_MODELS and device == "auto":
        return "cpu", "int8" if compute_type == "auto" else compute_type
    return _resolve(device, compute_type)


def resolve_model(model_size: str) -> str:
    """Return a bundled model DIRECTORY when one exists, else the size string.

    faster-whisper's WhisperModel accepts either a known size name (which it
    fetches/loads from the HF cache) OR a path to a directory containing
    model.bin + config. When frozen into an .exe we ship the model under
    ``models/<size>/`` so there's zero network and zero HF cache dependency.
    Search order: PyInstaller bundle (sys._MEIPASS) -> next to the exe ->
    project root. Fall back to the bare size name for the dev venv.
    """
    import sys

    from . import paths

    roots = list(paths.bundled_roots())               # inside the exe
    roots.append(paths.models_dir().parent)           # user data dir (downloads)
    roots.append(Path(__file__).resolve().parents[2])  # project root (dev)

    for root in roots:
        cand = root / "models" / model_size
        if (cand / "model.bin").exists():
            return str(cand)
    return model_size  # dev fallback: load by name from the HF cache


def is_model_present(model_size: str) -> bool:
    """True if the model is already on disk (bundled or downloaded)."""
    return resolve_model(model_size) != model_size


def ensure_model(model_size: str, progress=None) -> str:
    """Return a local model dir, downloading it into the user data dir if absent.

    Download is explicit (user picked this size in the tray) and is the ONLY
    time the network is touched — runtime stays offline otherwise. Raises on
    failure so the caller can keep the previous model and report the error.
    """
    found = resolve_model(model_size)
    if found != model_size:
        return found  # already present

    from . import paths

    dest = paths.models_dir() / model_size
    if (dest / "model.bin").exists():
        return str(dest)

    if progress:
        progress(f"Downloading {model_size} model …")

    import os

    from faster_whisper import download_model

    saved = {k: os.environ.pop(k, None)
             for k in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
    try:
        download_model(model_size, output_dir=str(dest))
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    if not (dest / "model.bin").exists():
        raise RuntimeError(f"download did not produce model.bin for {model_size}")
    return str(dest)


def probe(model_size: str = DEFAULT_MODEL, device: str = "auto",
          compute_type: str = "auto") -> ModelInfo:
    if importlib.util.find_spec("faster_whisper") is None:
        return ModelInfo(kind="unknown", note="faster-whisper not installed")
    dev, comp = resolve_runtime(model_size, device, compute_type)
    return ModelInfo(kind="whisper", model_size=model_size, device=dev,
                     compute_type=comp)


class Transcriber:
    def __init__(
        self,
        model_size: str = DEFAULT_MODEL,
        device: str = "auto",
        compute_type: str = "auto",
        download_root: str | None = None,
        language: str = "en",
        beam_size: int = 1,
    ):
        _ensure_cuda_dlls()
        from faster_whisper import WhisperModel

        self.language = language
        self.beam_size = beam_size
        dev, comp = resolve_runtime(model_size, device, compute_type)
        model_ref = resolve_model(model_size)  # bundled dir when frozen

        try:
            self._model = WhisperModel(model_ref, device=dev, compute_type=comp,
                                       download_root=download_root)
            self.device, self.compute_type = dev, comp
            self._warmup()
        except Exception as exc:
            if dev == "cuda":
                # GPU path unusable (missing DLLs / unsupported) — fall back to CPU.
                print(f"[model] GPU unavailable ({exc}); using CPU.", flush=True)
                self._model = WhisperModel(model_ref, device="cpu",
                                           compute_type="int8",
                                           download_root=download_root)
                self.device, self.compute_type = "cpu", "int8"
                self._warmup()
            else:
                raise
        self.model_size = model_size
        self.files = ModelInfo(kind="whisper", model_size=model_size,
                               device=self.device, compute_type=self.compute_type)

    def _warmup(self) -> None:
        """Prime the model (and surface any GPU DLL failure now, not mid-speech)."""
        silence = np.zeros(16000, dtype=np.float32)
        segs, _ = self._model.transcribe(silence, language=self.language,
                                         beam_size=self.beam_size)
        list(segs)

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if audio is None or np.asarray(audio).size == 0:
            return ""
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=True,  # Silero VAD trims silence/noise → cleaner output
        )
        return " ".join(s.text.strip() for s in segments).strip()
