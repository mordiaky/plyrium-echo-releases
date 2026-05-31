# Cross-platform PyInstaller spec for GitHub Actions builds.
#
# Windows still uses PlyriumEcho.nsi to wrap this onedir output into the
# public installer. macOS/Linux publish the onedir output as zipped artifacts
# first; we can promote those to DMG/AppImage/deb once the platform smoke tests
# are green.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

PROJECT = Path(SPECPATH)
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

binaries = []
datas = []
hiddenimports = []

for pkg in ("ctranslate2", "av", "sounddevice", "onnxruntime"):
    binaries += collect_dynamic_libs(pkg)

for pkg in ("faster_whisper", "sounddevice", "av", "onnxruntime", "tokenizers"):
    datas += collect_data_files(pkg)

# NOTE: no model bundled here; slim releases download the model on first run.
datas += [("assets/echo.ico", "assets")]
datas += [("assets/brand", "assets/brand")]
datas += [("config.json", ".")]

hiddenimports += collect_submodules("plyrium_echo")
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += ["ctranslate2", "av", "sounddevice", "onnxruntime"]
hiddenimports += ["PIL", "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk"]
hiddenimports += ["cryptography", "_cffi_backend"]
hiddenimports += ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "shiboken6"]

if IS_WINDOWS:
    hiddenimports += ["pystray._win32", "pynput.keyboard._win32", "pynput.mouse._win32"]
    hiddenimports += collect_submodules("pycaw")
    hiddenimports += ["comtypes", "comtypes.client"]
elif IS_MAC:
    hiddenimports += ["pystray._darwin", "pynput.keyboard._darwin", "pynput.mouse._darwin"]
elif IS_LINUX:
    hiddenimports += ["pystray._gtk", "pynput.keyboard._xorg", "pynput.mouse._xorg"]

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch", "tensorflow", "matplotlib", "pandas", "scipy",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
        "PySide6.QtCharts", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtDataVisualization",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQuick3DRuntimeRender",
        "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
    ],
    noarchive=False,
)

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


# All CI release artifacts are slim. GPU acceleration remains optional and
# provisioned outside the base app.
a.binaries = [b for b in a.binaries if not _is_cuda(b)]

pyz = PYZ(a.pure)

exe_kwargs = {
    "name": "Plyrium Echo",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": False,
    "console": False,
}
if IS_WINDOWS:
    exe_kwargs["icon"] = "assets/echo.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    **exe_kwargs,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Plyrium Echo",
)

