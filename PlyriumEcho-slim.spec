# PyInstaller spec for the SLIM, distributable Plyrium Echo.
#
# Build:  .\.venv\Scripts\pyinstaller.exe PlyriumEcho-slim.spec --noconfirm
# Output: dist\Plyrium Echo\Plyrium Echo.exe
#
# Differs from PlyriumEcho.spec (the full personal build) in two ways:
#   1. The Whisper model is NOT bundled — it's downloaded on first run
#      (ensure_model), keeping the installer small.
#   2. The ~2 GB of NVIDIA CUDA DLLs are EXCLUDED — the base runs on CPU, and
#      GPU users provision CUDA on demand (cuda_provision). CPU users never pay
#      the 2 GB.
# Result: a ~150-250 MB installer instead of 3.7 GB.

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

binaries += collect_dynamic_libs("ctranslate2")
binaries += collect_dynamic_libs("av")
binaries += collect_dynamic_libs("sounddevice")
binaries += collect_dynamic_libs("onnxruntime")

datas += collect_data_files("faster_whisper")
datas += collect_data_files("sounddevice")
datas += collect_data_files("av")
datas += collect_data_files("onnxruntime")
datas += collect_data_files("tokenizers")
# NOTE: no model bundled here (downloaded on first run).
datas += [("assets/echo.ico", "assets")]
datas += [("assets/brand", "assets/brand")]   # logo/mark/backdrop (window + tray)
datas += [("config.json", ".")]

hiddenimports += collect_submodules("plyrium_echo")
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += ["ctranslate2", "av", "sounddevice", "onnxruntime"]
hiddenimports += ["pystray._win32", "PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk"]
hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32"]
hiddenimports += collect_submodules("pycaw")
hiddenimports += ["comtypes", "comtypes.client"]
hiddenimports += ["cryptography", "_cffi_backend"]
# Qt UI (PySide6) - only the three modules we use.
hiddenimports += ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "shiboken6"]

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trim the heavy, definitely-unused PySide6 modules (we only use
    # QtCore/QtGui/QtWidgets). WebEngine/Qml/Quick/3D/Charts/Multimedia are the
    # big wins (hundreds of MB). Kept conservative to avoid breaking the build.
    excludes=["torch", "tensorflow", "matplotlib", "pandas", "scipy",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
              "PySide6.QtCharts", "PySide6.QtMultimedia",
              "PySide6.QtMultimediaWidgets", "PySide6.QtDataVisualization",
              "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQuick3DRuntimeRender",
              "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2"],
    noarchive=False,
)

# ── strip the CUDA libraries (the 2 GB) — provisioned on demand for GPU ──
_CUDA = ("cublas", "cudnn", "cudart", "cufft", "curand", "cusparse",
         "cusolver", "nvrtc", "nvblas")


def _is_cuda(entry):
    name = (entry[0] or "").lower()
    src = (entry[1] or "").lower()
    if any(p in name for p in _CUDA):
        return True
    if "\\nvidia\\" in src or "/nvidia/" in src:
        return True
    return False


a.binaries = [b for b in a.binaries if not _is_cuda(b)]

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
    console=False,
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
