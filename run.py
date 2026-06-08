"""Plyrium Echo — Wispr-style local push-to-talk dictation (offline).

    python run.py                 # start the tray app (default)
    python run.py --console       # run in the console (no tray), same hotkeys
    python run.py --file WAV      # transcribe a WAV file through the full pipeline
    python run.py --devices       # list microphone input devices
    python run.py --download-model# one-time online fetch of the Whisper model
    python run.py --check         # report model + device, then exit

Hold Ctrl+Win (or tap Ctrl+Win+Space for hands-free), speak, release — the
transcript is cleaned and pasted into whatever window has focus. One model
(Whisper) does transcription + punctuation. Everything runs offline.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# 100% offline by default — force HuggingFace into cache-only mode before any
# import can reach it (Whisper loads from the local cache, no network). The
# one-time downloader lifts this for its single run. PLYRIUM_ECHO_ALLOW_NET=1 opts out.
if os.environ.get("PLYRIUM_ECHO_ALLOW_NET") != "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# Windows consoles default to cp1252, which can't encode the glyphs we print.
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream is not None:
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from plyrium_echo.config import Config  # noqa: E402


def cmd_devices() -> int:
    from plyrium_echo.audio import MicRecorder

    print(MicRecorder.list_devices())
    return 0


def cmd_check(cfg: Config) -> int:
    from plyrium_echo.model import probe

    info = probe(cfg.model_size, cfg.device, cfg.compute_type)
    print(f"engine    : {info.kind}")
    print(f"model     : {info.model_size}")
    print(f"device    : {info.device}/{info.compute_type}")
    if info.note:
        print(f"note      : {info.note}")
    return 0 if info.kind == "whisper" else 1


def cmd_mictest(cfg: Config, seconds: float = 5.0) -> int:
    """Record from the configured input device and report EXACTLY what it captured.

    This is the definitive test for "is my mic capturing system audio?":
    play something (YouTube, a game) and STAY SILENT, then run this. If the
    transcript below contains what was playing, the input device is digitally
    capturing system output (a Windows routing/driver setting) — not your voice.
    If it comes back empty/quiet while audio plays, the capture is mic-only.
    """
    import time

    import numpy as np

    from plyrium_echo.audio import MicRecorder, describe_device
    from plyrium_echo.model import Transcriber

    # Use the REAL capture path the app uses (WASAPI device + resample to 16k).
    rec = MicRecorder(sample_rate=16000, device=cfg.input_device)
    print(f"input device : {describe_device(rec.device)}", flush=True)
    print(f"capture rate : {rec.capture_rate} Hz -> 16000 Hz", flush=True)
    print(f"recording {seconds:.0f}s NOW — to test for system-audio capture, "
          f"play audio and stay silent ...", flush=True)
    rec.start()
    time.sleep(seconds)
    audio = rec.stop()
    if audio is None:
        audio = np.zeros(0, dtype=np.float32)

    peak = float(np.abs(audio).max()) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    print(f"captured     : peak={peak:.3f}  rms={rms:.4f}  "
          f"({'silent' if rms < 0.005 else 'has signal'})", flush=True)

    print("transcribing what was captured ...", flush=True)
    tr = Transcriber(model_size=cfg.model_size, device=cfg.device,
                     compute_type=cfg.compute_type, language=cfg.language)
    print(f"RAW   : {tr.transcribe(audio)!r}", flush=True)
    return 0


def cmd_probe_mics(cfg: Config, seconds: float = 4.0) -> int:
    """Record from EVERY input device and report which ones capture system audio.

    THE TEST FOR "my mic grabs my YouTube/game audio":
      1. Start playing audio (YouTube, a game) and leave it playing.
      2. STAY SILENT — don't talk during the ~30s this takes.
      3. Read the table. A device with HIGH level is pulling in system audio
         (bad). A device that stays QUIET while audio plays is your true mic —
         put its index in config.json as "input_device".
    """
    import numpy as np
    import sounddevice as sd

    print("Play your audio now and STAY SILENT. Testing each input device "
          f"for {seconds:.0f}s ...\n", flush=True)

    default_in = sd.default.device[0]
    seen = set()
    rows = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        host = sd.query_hostapis(d["hostapi"])["name"]
        key = (d["name"], host)
        if key in seen:
            continue
        seen.add(key)
        try:
            rec = sd.rec(int(seconds * 16000), samplerate=16000, channels=1,
                         dtype="float32", device=i)
            sd.wait()
            rms = float(np.sqrt(np.mean(rec.reshape(-1) ** 2)))
        except Exception as exc:
            print(f"[{i:2}] (could not open) {d['name'][:34]:34} ({host}) — "
                  f"{str(exc)[:40]}", flush=True)
            continue
        verdict = "CAPTURES SYSTEM AUDIO" if rms > 0.005 else "quiet — likely true mic"
        star = " *default" if i == default_in else ""
        rows.append((rms, i, d["name"], host, verdict, star))
        print(f"[{i:2}] level={rms:.4f}  {d['name'][:32]:32} ({host}){star}"
              f"  <-- {verdict}", flush=True)

    quiet = [r for r in rows if r[0] <= 0.005]
    print("\n" + "=" * 60, flush=True)
    if quiet:
        best = min(quiet, key=lambda r: r[0])
        print(f"RECOMMENDED clean mic: index {best[1]}  ({best[2]} / {best[3]})",
              flush=True)
        print(f'Set it: edit config.json  "input_device": {best[1]}', flush=True)
        print("Then re-run this with audio playing to confirm it stays quiet.",
              flush=True)
    else:
        print("Every device captured audio. That means it's either acoustic "
              "(mic hears speakers — use headphones) OR a Windows/Realtek "
              "loopback setting. See the README 'system audio' section.", flush=True)
    return 0


def cmd_download_model(cfg: Config) -> int:
    """One-time online fetch of the Whisper model. The ONLY network use."""
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ.pop(var, None)
    from plyrium_echo.model import Transcriber

    print(f"Downloading Whisper '{cfg.model_size}' (one-time, needs internet) ...",
          flush=True)
    try:
        Transcriber(model_size=cfg.model_size, device="cpu", compute_type="int8",
                    language=cfg.language)
        print("Done. Cached. Every future run is 100% offline.", flush=True)
        return 0
    except Exception as exc:
        print(f"Download failed: {exc}", flush=True)
        return 1


def cmd_file(cfg: Config, wav_path: str) -> int:
    from plyrium_echo.audio import load_wav_16k_mono
    from plyrium_echo.format import polish_whisper
    from plyrium_echo.gate import apply_gate
    from plyrium_echo.model import Transcriber

    print(f"Loading Whisper ({cfg.model_size}) ...", flush=True)
    tr = Transcriber(model_size=cfg.model_size, device=cfg.device,
                     compute_type=cfg.compute_type, language=cfg.language)
    print(f"Device: {tr.device}/{tr.compute_type}", flush=True)
    audio = load_wav_16k_mono(wav_path)
    if cfg.noise_gate:
        audio = apply_gate(audio, sample_rate=16000, threshold=cfg.gate_threshold)
    print(f"Transcribing {audio.size / 16000:.1f}s ...", flush=True)
    raw = tr.transcribe(audio)
    out = polish_whisper(raw) if cfg.smart_format else raw
    print(f"raw : {raw}", flush=True)
    print(f"→   : {out}", flush=True)
    return 0


def run_console(cfg: Config) -> int:
    from plyrium_echo.app import App

    app = App(cfg, use_overlay=False)
    app.start_hotkeys()
    hf = f" / tap [{cfg.handsfree_hotkey}] hands-free" if cfg.handsfree_hotkey else ""
    print(f"\nReady (console). Hold [{cfg.hotkey}]{hf}. Esc cancels. Ctrl+C quits.",
          flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        app.shutdown()
        print("\nBye.", flush=True)
    return 0


def run_tray(cfg: Config) -> int:
    from plyrium_echo.app import App
    from plyrium_echo.qtui import QtController
    from plyrium_echo.tray import build_tray

    # Qt owns the GUI (window + overlay) on the main thread; the App provides no
    # overlay of its own (the Qt controller supplies a thread-safe facade).
    app = App(cfg, use_overlay=False)
    ctrl = QtController(app)
    app.overlay = ctrl.overlay
    app.attach_qt(ctrl)
    app.start_hotkeys()
    icon = build_tray(app)
    app.icon = icon

    hf = f" / tap [{cfg.handsfree_hotkey}] hands-free" if cfg.handsfree_hotkey else ""
    print(f"\nTray ready. Hold [{cfg.hotkey}]{hf}. Right-click the tray icon for "
          "options.", flush=True)

    icon.run_detached()   # tray on its own thread
    ctrl.run()            # Qt event loop owns the main thread
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Plyrium Echo — offline Wispr-style dictation")
    p.add_argument("--console", action="store_true", help="run without the tray icon")
    p.add_argument("--file", metavar="WAV", help="transcribe a WAV file and exit")
    p.add_argument("--devices", action="store_true", help="list microphones and exit")
    p.add_argument("--download-model", action="store_true",
                   help="one-time online fetch of the Whisper model")
    p.add_argument("--check", action="store_true", help="report model+device and exit")
    p.add_argument("--provision-gpu", action="store_true",
                   help="download NVIDIA CUDA libraries for GPU acceleration")
    p.add_argument("--mictest", nargs="?", type=float, const=5.0, metavar="SECONDS",
                   help="record from the current mic and report what it captured")
    p.add_argument("--probe-mics", nargs="?", type=float, const=4.0, metavar="SECONDS",
                   help="test every input device for system-audio capture (play "
                        "audio + stay silent while it runs)")
    args = p.parse_args()

    cfg = Config.load()
    if args.devices:
        return cmd_devices()
    if args.check:
        return cmd_check(cfg)
    if args.provision_gpu:
        from plyrium_echo import cuda_provision
        ok = cuda_provision.provision(progress=lambda m: print(m, flush=True))
        return 0 if ok else 1
    if args.probe_mics is not None:
        return cmd_probe_mics(cfg, args.probe_mics)
    if args.mictest is not None:
        return cmd_mictest(cfg, args.mictest)
    if args.download_model:
        return cmd_download_model(cfg)
    if args.file:
        return cmd_file(cfg, args.file)
    if args.console:
        return run_console(cfg)
    return run_tray(cfg)


if __name__ == "__main__":
    # PyInstaller-frozen macOS builds can spawn Python's multiprocessing
    # resource tracker using internal flags such as "-B -S -I -c ...". Without
    # freeze_support(), those helper invocations fall through to argparse below
    # and open extra Terminal windows with "unrecognized arguments" errors.
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
