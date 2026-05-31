"""Unit tests for the offline smart-formatting layer (no model needed).

Run with: .venv\\Scripts\\python.exe tests\\test_format.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo.format import (  # noqa: E402
    apply_spoken_punctuation,
    fix_capitalization,
    format_lists,
    format_offline,
    polish_whisper,
    pre_clean,
    smart_format,
)

cases = []


def check(name, got, want):
    ok = got == want
    cases.append(ok)
    flag = "ok " if ok else "FAIL"
    print(f"[{flag}] {name}")
    if not ok:
        print(f"        got : {got!r}")
        print(f"        want: {want!r}")


# ── pre_clean: filler removal ──
check("filler removal",
      pre_clean("um so i was uh thinking about it"),
      "so i was thinking about it")

# ── pre_clean: backtrack "scratch that" keeps what follows ──
check("scratch that (mid-sentence)",
      pre_clean("send it to bob scratch that send it to alice"),
      "send it to alice")

# ── backtrack: nothing before trigger retracts the PREVIOUS sentence ──
check("scratch that (previous sentence)",
      polish_whisper("Ship the report today. Scratch that. Ship it tomorrow."),
      "Ship it tomorrow.")

# ── backtrack: mid-sentence retraction leaves earlier sentences intact ──
check("scratch that (keeps earlier sentence)",
      polish_whisper("I love this. Send to Bob, scratch that, send to Alice."),
      "I love this. Send to Alice.")

# ── polish_whisper: filler removal on cased Whisper output ──
check("polish filler",
      polish_whisper("Um, so I was thinking we should ship it"),
      "So I was thinking we should ship it.")

# ── pre_clean: numeric correction ──
check("numeric correction",
      pre_clean("coffee at 2 actually 3"),
      "coffee at 3")

# ── pre_clean: non-numeric 'actually' is left alone ──
check("actually left alone",
      pre_clean("i actually love this"),
      "i actually love this")

# ── spoken punctuation ──
check("spoken punctuation",
      apply_spoken_punctuation("i cannot wait exclamation point this is great period"),
      "i cannot wait! this is great.")

check("spoken comma",
      apply_spoken_punctuation("first comma second comma third"),
      "first, second, third")

# ── capitalization + i->I ──
check("capitalization",
      fix_capitalization("hello world. this is me. i am here."),
      "Hello world. This is me. I am here.")

check("i contraction",
      fix_capitalization("i'm sure i'll be fine"),
      "I'm sure I'll be fine")

# ── numbered lists ──
check("numbered list",
      format_lists("my goals are one finish report two send slides"),
      "my goals are:\n1. Finish report\n2. Send slides")

check("no false list",
      format_lists("i have one dog and a cat"),
      "i have one dog and a cat")

# ── deterministic fallback end-to-end ──
check("offline fallback",
      format_offline("hello there my name is joshua"),
      "Hello there my name is joshua.")

# ── full pipeline, deterministic (punctuate_fn=None) ──
check("smart_format offline",
      smart_format("um my goals are one ship it two tell joshua", punctuate_fn=None),
      "My goals are:\n1. Ship it\n2. Tell joshua")

# ── full pipeline with a fake neural punctuator ──
def fake_punct(t):
    # pretend the model produced casing + a period
    return "My name is Joshua, I run Plyrium."

check("smart_format with model",
      smart_format("my name is joshua i run plyrium", punctuate_fn=fake_punct),
      "My name is Joshua, I run Plyrium.")

check("chat mode drops trailing period",
      smart_format("my name is joshua i run plyrium",
                   punctuate_fn=fake_punct, chat_mode=True),
      "My name is Joshua, I run Plyrium")


passed = sum(cases)
total = len(cases)
print(f"\n{passed}/{total} passed")
sys.exit(0 if passed == total else 1)
