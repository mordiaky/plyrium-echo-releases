"""Unit tests for Whisper runtime selection.

Run with: .venv\\Scripts\\python.exe tests\\test_model_runtime.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo.config import _migrate_multilingual_defaults, default_model_for_device  # noqa: E402
from plyrium_echo.model import resolve_runtime  # noqa: E402

cases = []


def check(name, got, want):
    ok = got == want
    cases.append(ok)
    flag = "ok " if ok else "FAIL"
    print(f"[{flag}] {name}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")


check("small auto uses CPU", resolve_runtime("small", "auto", "auto"), ("cpu", "int8"))
check("base auto uses CPU", resolve_runtime("base", "auto", "auto"), ("cpu", "int8"))
check("legacy small.en auto still uses CPU", resolve_runtime("small.en", "auto", "auto"), ("cpu", "int8"))
check("explicit CUDA respected", resolve_runtime("small", "cuda", "float16"), ("cuda", "float16"))
check("CPU default is multilingual", default_model_for_device() in {"small", "large-v3-turbo"}, True)
check(
    "legacy English-only config migrates",
    _migrate_multilingual_defaults({"model_size": "small.en", "language": "en"}),
    {"model_size": "small", "language": None},
)

passed = sum(cases)
total = len(cases)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
