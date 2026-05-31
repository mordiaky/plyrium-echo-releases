"""Unit tests for live microphone device selection (no real mic needed).

Run with: .venv\\Scripts\\python.exe tests\\test_audio_devices.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from plyrium_echo import audio  # noqa: E402

cases = []


def check(name, cond):
    cases.append(cond)
    print(f"[{'ok ' if cond else 'FAIL'}] {name}")


class FakeDefault:
    def __init__(self, input_device):
        self.device = (input_device, None)


class FakeSD:
    def __init__(self):
        self.default = FakeDefault(1)
        self.devices = [
            {"index": 0, "name": "Speakers", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
            {"index": 1, "name": "Old Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
            {"index": 2, "name": "New Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
        ]

    def query_devices(self, idx=None):
        if idx is None:
            return self.devices
        return self.devices[int(idx)]

    def query_hostapis(self, idx):
        return {"name": "Windows WASAPI"}


real_sd = audio.sd
fake_sd = FakeSD()
audio.sd = fake_sd
try:
    check("current default input is first in auto candidates",
          audio.candidate_devices(None)[0] == 1)

    fake_sd.default.device = (2, None)
    check("changed default input is picked without recreating module",
          audio.candidate_devices(None)[0] == 2)

    rec = audio.MicRecorder()
    fake_sd.default.device = (1, None)
    rec._candidates = [2]  # stale list from an earlier default
    opened = []

    def fake_open_stream(device):
        opened.append(device)
        return rec.sample_rate

    rec._open_stream = fake_open_stream
    rec.start()
    check("recorder refreshes stale candidates on start", opened[0] == 1)
    rec.stop()

    fake_sd.default.device = (2, None)
    rec.start()
    check("same recorder follows later default switch", opened[-1] == 2)
    rec.stop()
finally:
    audio.sd = real_sd

passed = sum(cases)
print(f"\n{passed}/{len(cases)} passed")
sys.exit(0 if passed == len(cases) else 1)
