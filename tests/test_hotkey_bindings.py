"""Hotkey parsing tests.

Run with: .venv\\Scripts\\python.exe tests\\test_hotkey_bindings.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo import hotkey  # noqa: E402
from plyrium_echo.hotkey import HotkeyManager, parse_combo, parse_combo_list  # noqa: E402

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


def check_true(name, cond):
    cases.append(bool(cond))
    print(f"[{'ok ' if cond else 'FAIL'}] {name}")


started = []
stopped = []
manager = HotkeyManager(
    ptt="ctrl+win",
    handsfree=None,
    on_start=lambda mode: started.append(mode),
    on_stop=lambda: stopped.append(True),
)

real_norm = hotkey._norm
real_physical = hotkey._physical_modifier_down
try:
    # Simulate Windows swallowing Win release: Echo still thinks win is down,
    # but the physical keyboard state says it is not. Pressing Ctrl alone must
    # not satisfy ctrl+win.
    manager.pressed = {"win"}
    physical = {"ctrl": True, "win": False, "alt": False, "shift": False}
    hotkey._norm = lambda key: key
    hotkey._physical_modifier_down = lambda name: physical.get(name, None)
    manager._press("ctrl")
    check_true("stale win is removed on ctrl press", "win" not in manager.pressed)
    check_true("ctrl alone does not start ptt after stale win", not started)

    physical["win"] = True
    manager._press("win")
    check_true("ctrl+win still starts ptt", started == ["ptt"])

    physical["win"] = False
    manager._release("win")
    check_true("ptt stops when win is physically released", stopped == [True])
finally:
    hotkey._norm = real_norm
    hotkey._physical_modifier_down = real_physical

passed = sum(cases)
total = len(cases)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
