"""Hotkey parsing tests.

Run with: .venv\\Scripts\\python.exe tests\\test_hotkey_bindings.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo.hotkey import parse_combo, parse_combo_list  # noqa: E402

cases = []


def check(name, got, want):
    ok = got == want
    cases.append(ok)
    flag = "ok " if ok else "FAIL"
    print(f"[{flag}] {name}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")


check("single modifier combo", parse_combo("ctrl"), frozenset({"ctrl"}))
check(
    "ordered aliases normalize",
    parse_combo("control + option + shift"),
    frozenset({"ctrl", "alt", "shift"}),
)
check(
    "comma separated combos",
    parse_combo_list("ctrl+win, alt+ctrl+shift"),
    (
        frozenset({"ctrl", "win"}),
        frozenset({"alt", "ctrl", "shift"}),
    ),
)
check(
    "list input dedupes",
    parse_combo_list(["ctrl", "ctrl", "f9"]),
    (frozenset({"ctrl"}), frozenset({"f9"})),
)

passed = sum(cases)
total = len(cases)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
