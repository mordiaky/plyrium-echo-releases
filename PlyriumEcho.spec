# PyInstaller spec for Plyrium Echo — windowless system-tray dictation app.
#
# Build:  .\.venv\Scripts\pyinstaller.exe PlyriumEcho.spec --noconfirm
# Output: dist\Plyrium Echo\Plyrium Echo.exe  (onedir — exe + bundled libs)
#
# onedir (not onefile): the CUDA libraries are ~2 GB, so onefile would
# re-extract that to a temp dir on every launch (slow). onedir keeps the libs
# beside the exe; the installer later ships the whole folder to Program Files.

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

PROJECT = Path(SPECPATH)

binaries = []
datas = []
hiddenimports = []

# ── native libraries that PyInstaller won't find on its own ──
# CTranslate2 ships the engine + all the bundled/copied CUDA DLLs in its dir.
binaries += collect_dynamic_libs("ctranslate2")
# PyAV (audio decode) + sounddevice (PortAudio) native libs.
binaries += collect_dynamic_libs("av")
binaries += collect_dynamic_libs("sounddevice")
# onnxruntime backs faster-whisper's Silero VAD (vad_filter=True) — its DLLs
# must ship or the first transcribe crashes.
binaries += collect_dynamic_libs("onnxruntime")

# ── data files ──
# faster-whisper bundles the Silero VAD .onnx asset (we use vad_filter=True).
datas += collect_data_files("faster_whisper")
# sounddevice ships portaudio under _sounddevice_data.
datas += collect_data_files("sounddevice")
datas += collect_data_files("av")
datas += collect_data_files("onnxruntime")
# tokenizers / huggingface_hub occasionally need their metadata.
datas += collect_data_files("tokenizers")
# The bundled Whisper model (offline) and the app icon.
datas += [("models/large-v3-turbo", "models/large-v3-turbo")]
datas += [("assets/echo.ico", "assets")]
datas += [("assets/brand", "assets/brand")]   # logo/mark/backdrop (window + tray)
datas += [("config.json", ".")]

# ── hidden imports the analyzer misses ──
hiddenimports += collect_submodules("plyrium_echo")
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += ["ctranslate2", "av", "sounddevice", "onnxruntime"]
hiddenimports += ["pystray._win32", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk"]
hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32"]
# Audio ducking via Windows Core Audio (pycaw + comtypes).
hiddenimports += collect_submodules("pycaw")
hiddenimports += ["comtypes", "comtypes.client"]
# Offline license-key verification (Ed25519 via cryptography/cffi).
hiddenimports += ["cryptography", "_cffi_backend"]

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tensorflow", "matplotlib", "pandas", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Plyrium Echo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # windowless — tray only, no terminal
    icon="assets/echo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Plyrium Echo",
)
