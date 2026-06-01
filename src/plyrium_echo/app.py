"""Application controller — wires model, mic, hotkeys, output, overlay, tray.

Owns the record → transcribe → format → paste loop and the actions the tray menu
drives (pause, output mode, quit). There is no beep and no audio muting — the
visual pill is the only cue, and your other audio keeps playing untouched.
"""

from __future__ import annotations

import threading
import time
import sys

from .audio import MicRecorder
from .audioduck import AudioDucker
from .config import Config
from .format import polish_whisper
from .gate import apply_gate
from .history import HistoryStore
from .hotkey import HotkeyManager
from .licensing import License
from .llm import LLMCleaner
from .model import Transcriber, ensure_model
from .output import TextOutput
from .overlay import NullOverlay, Overlay
from .win_active import foreground_app, is_chat_app

_UNSET = object()  # "argument not provided" sentinel (so None can mean "disable")

# Models heavy enough to be worth auto-fetching the GPU pack for. The small
# models run fine on CPU, so we never pull ~1.9 GB just to run those.
_GPU_MODELS = {"large-v3-turbo", "large-v3", "medium.en", "medium"}


class App:
    def __init__(self, cfg: Config, use_overlay: bool | None = None):
        self.cfg = cfg
        self.paused = False
        self.icon = None
        self._state = "idle"
        self._on_state = None
        self._level_stop = threading.Event()
        self._busy = threading.Lock()
        self._reload_lock = threading.Lock()
        self._qt = None            # Qt UI controller (set via attach_qt)
        self._window = None        # the main window (created on demand)
        self._active_app = ""      # app you were focused on when recording began
        self._gpu_provisioning = False

        print(f"Loading Whisper ({cfg.model_size}) ...", flush=True)
        t0 = time.time()
        # First run on a slim install has no bundled model — fetch it once.
        # (No-op when the model is already bundled or downloaded.)
        try:
            ensure_model(cfg.model_size)
        except Exception as exc:
            print(f"[model] could not obtain '{cfg.model_size}': {exc}", flush=True)
        self.transcriber = Transcriber(
            model_size=cfg.model_size, device=cfg.device,
            compute_type=cfg.compute_type, language=cfg.language,
            beam_size=cfg.beam_size,
        )
        print(f"Model ready on {self.transcriber.device}/"
              f"{self.transcriber.compute_type} in {time.time() - t0:.1f}s.",
              flush=True)

        self.recorder = MicRecorder(sample_rate=16000, device=cfg.input_device)
        self.output = TextOutput(mode=cfg.output_mode, type_delay=cfg.type_delay)
        self.ducker = AudioDucker(enabled=cfg.duck_audio, level=cfg.duck_level)
        self.history = HistoryStore(enabled=cfg.history_enabled,
                                    max_entries=cfg.history_max_entries)
        self.license = License()
        print(f"License: {self.license.status_text()}", flush=True)
        # Always build a real Overlay for the tray path (its Tk mainloop owns the
        # main thread and keeps the process alive); cfg.overlay only controls
        # whether the pill is *visible*, which the tray can toggle live. Console
        # mode passes use_overlay=False and uses the no-op overlay.
        if use_overlay is False:
            self.overlay = NullOverlay()
        else:
            self.overlay = Overlay(enabled=True)
            self.overlay.set_visible(cfg.overlay)

        # LLM cleanup stage (Wispr-style 2nd pass via local Ollama). Optional —
        # if the service/model isn't there, _format falls back to deterministic.
        self.llm = None
        if cfg.llm_cleanup:
            self.llm = LLMCleaner(model=cfg.llm_model, terms=cfg.dictionary,
                                  keep_alive=cfg.llm_keep_alive)
            if self.llm.available():
                print(f"LLM cleanup ready ({cfg.llm_model}); warming ...", flush=True)
                threading.Thread(target=self.llm.warm, daemon=True).start()
            else:
                print("LLM cleanup on but Ollama/model not found — using "
                      "deterministic formatting.", flush=True)

        self.hk = HotkeyManager(
            ptt=cfg.hotkey, handsfree=cfg.handsfree_hotkey,
            on_start=self._on_start, on_stop=self._on_stop, on_cancel=self._on_cancel,
        )

        # If a heavy model is selected on an NVIDIA box that isn't accelerated
        # yet, fetch CUDA + switch to GPU in the background (non-blocking).
        self.auto_gpu_if_needed()

    # ── formatting ───────────────────────────────────────────────
    def _format(self, raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        chat = self.cfg.chat_apps_no_period and is_chat_app()
        # Prefer the LLM cleanup (proper nouns, punctuation, filler) when it's
        # available — that's what Wispr's LLM stage does. cleanup() returns None
        # when the result can't be trusted (rejected/errored), so fall through to
        # the deterministic formatter in that case instead of crashing on None.
        if self.llm is not None and self.llm.available():
            cleaned = self.llm.cleanup(raw)
            if cleaned:
                if chat:
                    import re
                    cleaned = re.sub(r"\.\s*$", "", cleaned)
                return cleaned.strip()
        if not self.cfg.smart_format:
            return raw
        return polish_whisper(raw, remove_fillers=True, chat_mode=chat)

    # ── state / icon ─────────────────────────────────────────────
    def _set_state(self, state: str) -> None:
        self._state = state
        if self._on_state:
            try:
                self._on_state(state)
            except Exception:
                pass

    def set_state_callback(self, fn) -> None:
        self._on_state = fn

    # ── hotkey callbacks ─────────────────────────────────────────
    def _on_start(self, mode: str) -> None:
        if self.paused:
            return
        if not self.license.active():
            self._license_block()
            return
        self._active_app = foreground_app()   # the app you're dictating into
        self.ducker.duck()           # dip other audio so the mic focuses on you
        self.recorder.start()
        self.overlay.show(mode)
        self._set_state("recording")
        tag = "hands-free (tap to stop)" if mode == "hf" else "hold"
        print(f"\n● recording [{tag}] ...", flush=True)
        self._level_stop.clear()
        threading.Thread(target=self._feed_levels, daemon=True).start()

    def _feed_levels(self) -> None:
        while not self._level_stop.is_set():
            self.overlay.set_level(self.recorder.level)
            time.sleep(0.03)

    def _on_stop(self) -> None:
        self._level_stop.set()
        audio = self.recorder.stop()
        self.ducker.restore()        # bring other audio back the instant you finish
        if audio is None:
            self.overlay.hide()
            self._set_state("idle")
            print("  (nothing captured)", flush=True)
            return
        self.overlay.transcribing()
        self._set_state("transcribing")
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio) -> None:
        with self._busy:
            try:
                seconds = audio.size / 16000
                if seconds < self.cfg.min_seconds:
                    print(f"  (too short: {seconds:.2f}s)", flush=True)
                    return
                if self.cfg.noise_gate:
                    audio = apply_gate(audio, sample_rate=16000,
                                       threshold=self.cfg.gate_threshold)
                    if audio.size == 0:
                        print("  (only background below the gate — nothing to "
                              "transcribe)", flush=True)
                        return
                print(f"  transcribing {audio.size / 16000:.1f}s ...", flush=True)
                raw = self.transcriber.transcribe(audio, sample_rate=16000)
                text = self._format(raw)
                if text:
                    print(f"  → {text}", flush=True)
                    self.output.deliver(text)
                    self.history.add(text, raw=raw, app=self._active_app,
                                     model=self.transcriber.model_size)
                    if self._window is not None:
                        self._refresh_window_history()
                else:
                    print("  (no speech detected)", flush=True)
            finally:
                self.overlay.hide()
                self._set_state("idle")

    def _on_cancel(self) -> None:
        self._level_stop.set()
        self.recorder.stop()
        self.ducker.restore()        # always un-dip, even on cancel
        self.overlay.hide()
        self._set_state("idle")
        print("  (cancelled)", flush=True)

    # ── tray actions ─────────────────────────────────────────────
    def _refresh_tray(self) -> None:
        """Rebuild the tray menu so its label/radios/checks reflect current
        state — needed when a change comes from the window, not the tray."""
        try:
            if self.icon is not None:
                self.icon.update_menu()
        except Exception:
            pass

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self._set_state("paused" if self.paused else "idle")
        print(f"[{'paused' if self.paused else 'active'}]", flush=True)
        self._refresh_tray()

    def set_output_mode(self, mode: str) -> None:
        self.cfg.output_mode = mode
        self.output.mode = mode
        self.cfg.save()
        self._refresh_tray()

    # ── live settings (all persist via cfg.save) ─────────────────
    def set_duck(self, level: float | None) -> None:
        """level=None turns ducking off; otherwise sets the dip fraction."""
        if level is None:
            self.cfg.duck_audio = False
            self.ducker.enabled = False
            self.ducker.restore()
        else:
            self.cfg.duck_audio = True
            self.cfg.duck_level = level
            self.ducker.level = level
            self.ducker.enabled = self.ducker._vol is not None
        self.cfg.save()
        self._refresh_tray()

    def set_smart_format(self, on: bool) -> None:
        self.cfg.smart_format = on
        self.cfg.save()
        self._refresh_tray()

    def set_chat_period(self, on: bool) -> None:
        self.cfg.chat_apps_no_period = on
        self.cfg.save()
        self._refresh_tray()

    def set_overlay(self, on: bool) -> None:
        self.cfg.overlay = on
        try:
            self.overlay.set_visible(on)
        except Exception:
            pass
        self.cfg.save()
        self._refresh_tray()

    def set_llm_cleanup(self, on: bool) -> None:
        self.cfg.llm_cleanup = on
        if on and self.llm is None:
            self.llm = LLMCleaner(model=self.cfg.llm_model, terms=self.cfg.dictionary,
                                  keep_alive=self.cfg.llm_keep_alive)
            if self.llm.available():
                threading.Thread(target=self.llm.warm, daemon=True).start()
        elif not on:
            self.llm = None
        self.cfg.save()
        self._refresh_tray()

    def llm_available(self) -> bool:
        return self.llm is not None and self.llm.available()

    def _license_block(self) -> None:
        print("  (trial ended — activate to keep dictating)", flush=True)
        try:
            if self.icon:
                self.icon.notify("Your trial has ended. Enter your license key in "
                                 "Settings to keep using Plyrium Echo.",
                                 "Plyrium Echo")
        except Exception:
            pass
        self.open_window()

    def activate_license(self, key: str) -> tuple[bool, str]:
        return self.license.activate(key)

    def set_history_enabled(self, on: bool) -> None:
        self.cfg.history_enabled = on
        if self.history is not None:
            self.history.enabled = on
        self.cfg.save()
        self._refresh_tray()

    def set_hotkey(self, ptt=_UNSET, handsfree=_UNSET) -> None:
        """Change the push-to-talk and/or hands-free combo and rebind live.

        Pass ``handsfree=None`` (or "") to disable the hands-free toggle.
        """
        if ptt is not _UNSET and ptt:
            self.cfg.hotkey = ptt
        if handsfree is not _UNSET:
            self.cfg.handsfree_hotkey = handsfree or None
        self.cfg.save()
        self._restart_hotkeys()

    def _restart_hotkeys(self) -> None:
        try:
            if self.hk._listener:
                self.hk._listener.stop()
        except Exception:
            pass
        self.hk = HotkeyManager(
            ptt=self.cfg.hotkey, handsfree=self.cfg.handsfree_hotkey,
            on_start=self._on_start, on_stop=self._on_stop,
            on_cancel=self._on_cancel,
        )
        self.hk.start()
        print(f"[hotkey] rebound: hold={self.cfg.hotkey} "
              f"hands-free={self.cfg.handsfree_hotkey}", flush=True)

    # ── main window (opened from the tray) ───────────────────────
    def attach_qt(self, controller) -> None:
        """Wire the Qt UI controller (owns the window + overlay event loop)."""
        self._qt = controller

    def open_window(self) -> None:
        """Open (or focus) the main window (thread-safe via the Qt controller)."""
        qt = getattr(self, "_qt", None)
        if qt is not None:
            qt.open_window()

    def open_about(self) -> None:
        """Open the main window directly to About."""
        qt = getattr(self, "_qt", None)
        if qt is not None and hasattr(qt, "open_window_section"):
            qt.open_window_section("About")
        else:
            self.open_window()

    def check_for_updates(self):
        from . import updater

        return updater.latest_release()

    def install_update(self, release, progress=None) -> str:
        from . import updater

        package = updater.download_release_asset(release, progress=progress)
        message = updater.launch_installer(package, release)
        if sys.platform == "win32":
            self.shutdown()
        return message

    def _refresh_window_history(self) -> None:
        w = self._window
        if w is None:
            return
        try:
            w.on_new_entry()   # Qt window: emits a queued signal (thread-safe)
        except Exception:
            pass

    def provision_gpu(self, notify=None) -> bool:
        """Download the CUDA GPU pack, then reload the current model on the GPU."""
        from . import cuda_provision
        ok = cuda_provision.provision(progress=notify)
        if ok:
            self.reload_model(self.cfg.model_size, notify=notify, force=True)
        return ok

    def _wants_gpu(self, size: str) -> bool:
        return size in _GPU_MODELS

    def _notify(self, msg: str, title: str = "Plyrium Echo") -> None:
        try:
            if self.icon:
                self.icon.notify(msg, title)
        except Exception:
            pass

    def _gpu_progress(self, msg: str) -> None:
        print(f"[gpu] {msg}", flush=True)
        w = self._window
        if w is not None:
            try:
                w.set_gpu_status(msg)   # Qt window: queued signal (thread-safe)
            except Exception:
                pass

    def auto_gpu_if_needed(self) -> None:
        """Non-blocking: if a heavy model is selected on an NVIDIA machine and
        CUDA isn't usable yet, download the GPU pack and switch to GPU. AMD /
        Intel / no-GPU machines are left on CPU (no pointless download)."""
        if not getattr(self.cfg, "auto_gpu", True) or self._gpu_provisioning:
            return
        try:
            from .model import _cuda_available, cuda_usable
        except Exception:
            return
        if cuda_usable() or not _cuda_available():
            return
        if not self._wants_gpu(self.cfg.model_size):
            return
        self._gpu_provisioning = True

        def work():
            from . import cuda_provision
            try:
                self._notify("Setting up GPU acceleration — one-time ~1.9 GB "
                             "download. Dictation works while it downloads.")
                ok = cuda_provision.provision(progress=self._gpu_progress)
                if ok:
                    self.reload_model(self.cfg.model_size,
                                      notify=self._gpu_progress, force=True)
                    dev = self.transcriber.device
                    self._gpu_progress(f"GPU acceleration active ({dev}).")
                    self._notify(
                        f"GPU acceleration is on — now running "
                        f"{self.cfg.model_size} on your GPU ({dev}).")
                else:
                    self._notify("GPU setup didn't finish — staying on CPU. "
                                 "You can retry from Settings.")
            finally:
                self._gpu_provisioning = False

        threading.Thread(target=work, daemon=True).start()

    def reload_model(self, size: str, notify=None, force: bool = False) -> None:
        """Switch the active Whisper model, downloading it first if needed.

        ``force`` reloads even when the size is unchanged (used after GPU
        provisioning to move the same model from CPU onto the GPU). Slow
        (download + ~4s load) — call from a background thread. On any failure
        the previous model stays active and the error is reported.
        """
        with self._reload_lock:
            if size == self.cfg.model_size and not force:
                return
            from .model import Transcriber, ensure_model

            try:
                ensure_model(size, progress=notify)
            except Exception as exc:
                if notify:
                    notify(f"Couldn't download {size}: {exc}")
                return
            if notify:
                notify(f"Loading {size} …")
            try:
                new = Transcriber(
                    model_size=size, device=self.cfg.device,
                    compute_type=self.cfg.compute_type, language=self.cfg.language,
                    beam_size=self.cfg.beam_size,
                )
            except Exception as exc:
                if notify:
                    notify(f"Failed to load {size}: {exc}")
                return
            with self._busy:  # don't swap mid-dictation
                self.transcriber = new
            self.cfg.model_size = size
            self.cfg.save()
            self._refresh_tray()
            if notify:
                notify(f"Now using {size} on {new.device}.")
        # Outside the reload lock: if a heavy model just loaded on CPU and an
        # NVIDIA GPU is available, fetch CUDA + switch to GPU in the background.
        self.auto_gpu_if_needed()

    def start_hotkeys(self) -> None:
        self.hk.start()

    def shutdown(self) -> None:
        self._level_stop.set()
        try:
            self.ducker.restore()    # never leave the volume dipped on exit
        except Exception:
            pass
        try:
            self.overlay.stop()
        except Exception:
            pass
        try:
            if self.hk._listener:
                self.hk._listener.stop()
        except Exception:
            pass
