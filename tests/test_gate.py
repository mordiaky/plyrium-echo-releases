"""Unit tests for the noise gate (no model needed).

Run with: .venv\\Scripts\\python.exe tests\\test_gate.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo.gate import apply_gate  # noqa: E402

SR = 16000
cases = []


def check(name, cond):
    cases.append(cond)
    print(f"[{'ok ' if cond else 'FAIL'}] {name}")


def tone(freq, secs, amp):
    t = np.arange(int(SR * secs)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# A loud "voice" burst in the middle, quiet "bleed" everywhere else.
quiet_bleed = tone(220, 3.0, 0.01)          # ~ -40 dB background
loud_voice = tone(180, 1.0, 0.20)           # close-mic voice
clip = quiet_bleed.copy()
start = SR  # 1.0s in
clip[start:start + loud_voice.size] += loud_voice

gated = apply_gate(clip, SR, threshold=0.015)

# 1. Output keeps the loud middle region (energy preserved there)
mid_in = np.abs(clip[start:start + loud_voice.size]).mean()
mid_out = np.abs(gated[start:start + loud_voice.size]).mean()
check("voice region preserved", mid_out > 0.5 * mid_in)

# 2. The quiet edges are zeroed (background removed)
edge = np.abs(gated[:start // 2]).mean()
check("quiet bleed before voice removed", edge < 1e-4)

# 3. A clip that is ONLY quiet bleed returns empty (no hallucination feed)
only_bleed = apply_gate(quiet_bleed, SR, threshold=0.015)
check("pure background -> empty", only_bleed.size == 0)

# 4. Pure silence returns empty
check("silence -> empty", apply_gate(np.zeros(SR, dtype=np.float32), SR).size == 0)

# 5. A fully loud clip passes through (not over-gated)
loud_all = tone(180, 1.0, 0.2)
out_all = apply_gate(loud_all, SR, threshold=0.015)
check("loud speech passes", out_all.size > 0 and np.abs(out_all).mean() > 0.05)

# 6. Output length matches input length (when not emptied)
check("length preserved", gated.size == clip.size)

passed = sum(cases)
print(f"\n{passed}/{len(cases)} passed")
sys.exit(0 if passed == len(cases) else 1)
