# Plyrium Echo

Standalone **system-tray push-to-talk dictation** for Windows — a local, fully
**offline** alternative to [Wispr Flow](https://wisprflow.ai). It lives in your
system tray. Hold a hotkey, speak, release, and clean punctuated text is pasted
into whatever window has focus. **No audio or transcript ever leaves the
machine.**

> Despite the name (kept from the original build), speech recognition is now
> **Whisper** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper) —
> **one model** that transcribes *and* punctuates/capitalizes. No second model,
> no PyTorch.

## What it does (like Wispr Flow)

```
mic → Whisper (faster-whisper)  ── transcription + punctuation + capitalization, one shot
    → light cleanup             ── filler removal ("um/uh") + backtrack ("scratch that", "2 actually 3")
    → app-aware                 ── drops the trailing period in chat apps (Slack/Discord/…)
    → paste into focused window (restores your clipboard)
```

| Wispr Flow feature | plyrium-echo | Notes |
|---|---|---|
| Lives in the system tray | ✅ | rendered "echo" icon, recolors by state: idle / recording / transcribing / paused |
| Floating indicator pill | ✅ | dark rounded pill, bottom-center, minimal sonar-pulse (no busy bars) |
| Ducks other audio while recording | ✅ | mutes system output when you talk, restores on stop (like Wispr) |
| Hold-to-talk | ✅ | `Ctrl+Win` (Wispr's Windows default), with a key-release watchdog so the pill never sticks |
| Hands-free toggle | ✅ | tap `Ctrl+Win+Space`, talk, tap to stop |
| Paste + clipboard restore | ✅ | |
| Punctuation + capitalization | ✅ | native to Whisper |
| Filler removal / backtrack | ✅ | added on top of Whisper |
| App-aware formatting | ✅ | chat apps lose the trailing period |
| Run on Windows login | ✅ | `install-autostart.ps1` |
| GPU acceleration | ✅ | auto-detected; ~34× realtime on your RTX 5080 |
| Command Mode (voice-edit selection) | ❌ | needs a cloud LLM — out of scope for offline |
| Custom dictionary / snippets | ❌ | not yet (easy add — ask) |

## Install

```powershell
cd C:\Users\Mordiaky\Projects\plyrium-echo
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` creates the venv, installs dependencies, **auto-detects your NVIDIA
GPU** and adds the CUDA wheels, then downloads the Whisper model once (the only
time the network is used). Verify:

```powershell
.\.venv\Scripts\python.exe run.py --check    # engine: whisper · device: cuda/float16
```

## Run

```powershell
.\start.ps1
```

This launches it **windowless** — just the tray icon appears (no console). Then:

- **Hold `Ctrl+Win`**, speak, release → text is pasted into the focused window.
- **Tap `Ctrl+Win+Space`** to start hands-free; talk; tap again to stop.
- **`Esc`** cancels an in-progress recording.
- **Right-click the tray icon** → Pause/Resume, Output mode (Paste/Type/Clipboard), Quit.

### Start automatically on login (like Wispr)

```powershell
powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1     # enable
powershell -ExecutionPolicy Bypass -File .\uninstall-autostart.ps1   # disable
```

### Other commands

```powershell
.\.venv\Scripts\python.exe run.py --console        # run with a console (debugging)
.\.venv\Scripts\python.exe run.py --file clip.wav  # transcribe a WAV through the pipeline
.\.venv\Scripts\python.exe run.py --devices        # list microphones
.\.venv\Scripts\python.exe run.py --download-model # (re)cache the Whisper model
```

## 100% offline

The app makes **zero network calls at runtime.** The Whisper model is fetched
once (`--download-model`, run for you by `setup.ps1`) into the local cache; at
startup `run.py` forces `HF_HUB_OFFLINE` so it loads from disk only — no update
checks, no telemetry. After setup you can pull the network cable and it works
identically. (`PLYRIUM_ECHO_ALLOW_NET=1` opts out if you ever want update checks.)

## Configuration (`config.json`)

| Key                  | Default          | Meaning |
|----------------------|------------------|---------|
| `model_size`         | `small`          | `tiny` · `base` · `small` · `medium` · `large-v3-turbo` (multilingual; bigger = more accurate, slower) |
| `language`           | `null`           | `null` = auto-detect spoken language; set a language code only when you want to force one |
| `device`             | `auto`           | `auto` (GPU if present) · `cuda` · `cpu` |
| `compute_type`       | `auto`           | `auto` · `float16` · `int8` · `int8_float16` |
| `hotkey`             | `ctrl+win`       | Hold-to-talk combo |
| `handsfree_hotkey`   | `ctrl+win+space` | Tap-to-toggle, or `null` to disable |
| `output_mode`        | `paste`          | `paste` · `type` · `clipboard` · `both` |
| `smart_format`       | `true`           | Filler removal + backtrack |
| `chat_apps_no_period`| `true`           | Drop trailing period in Slack/Discord/etc. |
| `overlay`            | `true`           | Floating sonar-pulse pill |
| `duck_audio`         | `true`           | Mute other system audio while recording |
| `input_device`       | `null`           | Mic index/name (`--devices`) or default |

Use `config.local.json` to override without touching the committed file. The
tray's Output-mode menu writes changes back to `config.json` for you.

## Project layout

```
plyrium-echo/
├─ run.py                  entry (tray default; --console/--file/--check/--devices/--download-model)
├─ start.ps1               windowless tray launcher
├─ setup.ps1               venv + deps + GPU wheels + model download
├─ install-autostart.ps1   run on Windows login   (uninstall-autostart.ps1 to remove)
├─ requirements.txt        core deps (no torch)   requirements-gpu.txt = CUDA wheels
├─ config.json
├─ tests/test_format.py    17 formatting unit tests (no model needed)
└─ src/plyrium_echo/
   ├─ app.py               record→transcribe→format→paste controller + tray actions
   ├─ model.py             faster-whisper (GPU/CPU auto) + CUDA-DLL shim
   ├─ format.py            filler removal, backtrack, capitalization, lists
   ├─ audio.py             16 kHz mic capture + live level
   ├─ hotkey.py            hold-to-talk + hands-free toggle
   ├─ output.py            paste-with-clipboard-restore / type
   ├─ overlay.py           floating waveform pill (tkinter)
   ├─ tray.py              system-tray icon + menu (pystray)
   ├─ win_active.py        focused-app detection (chat-app awareness)
   └─ config.py            settings load/save
```

## How it compares to Wispr Flow

Same loop and feel — tray icon, floating waveform pill, hold-or-handsfree,
paste + clipboard restore, app-aware formatting, autostart. The difference is
**where it runs**: Wispr streams audio to the cloud and uses an LLM for editing
and Command Mode; this does everything locally with Whisper, so it's private and
free, but has no LLM Command Mode.

## Troubleshooting

- **`--check` shows `cpu` but you have a GPU** — run `setup.ps1` again (installs
  the CUDA wheels), or `pip install -r requirements-gpu.txt`. The app still runs
  fine on CPU.
- **Tray icon missing** — make sure you ran `start.ps1` (not `--console`); check
  the Windows "hidden icons" tray overflow.
- **Hotkey ignored in an elevated app** — run the launcher as Administrator
  (Windows blocks input hooks from lower-integrity processes).
- **Characters dropped in `type` mode** — use `paste` (default).
- **First launch slow** — it loads the model (~3 s on GPU); subsequent
  dictations are sub-second.
