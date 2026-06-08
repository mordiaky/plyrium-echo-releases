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
    def __init__(self, hostapis=None, devices=None, default_input=1):
        self.hostapis = hostapis or [
            {"name": "Windows WASAPI", "default_input_device": default_input},
        ]
        self.default = FakeDefault(1)
        self.default.device = (default_input, None)
        self.devices = devices or [
            {"index": 0, "name": "Speakers", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
            {"index": 1, "name": "Old Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
            {"index": 2, "name": "New Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
        ]
        self._device_by_index = {int(d["index"]): d for d in self.devices}

    def query_devices(self, idx=None):
        if idx is None:
            return self.devices
        return self._device_by_index[int(idx)]

    def query_hostapis(self, idx=None):
        if idx is None:
            return self.hostapis
        return self.hostapis[int(idx)]


real_sd = audio.sd
fake_sd = FakeSD()
audio.sd = fake_sd
try:
    check("current default input is first in auto candidates",
          audio.candidate_devices(None)[0] == 1)

    fake_sd.default.device = (2, None)
    fake_sd.hostapis[0]["default_input_device"] = 2
    check("changed default input is picked without recreating module",
          audio.candidate_devices(None)[0] == 2)

    rec = audio.MicRecorder()
    fake_sd.default.device = (1, None)
    fake_sd.hostapis[0]["default_input_device"] = 1
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
    fake_sd.hostapis[0]["default_input_device"] = 2
    rec.start()
    check("same recorder follows later default switch", opened[-1] == 2)
    rec.stop()
finally:
    audio.sd = real_sd


mac_sd = FakeSD(
    hostapis=[
        {"name": "Core Audio", "default_input_device": 2},
    ],
    devices=[
        {"index": 0, "name": "MacBook Pro Speakers", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
        {"index": 1, "name": "BlackHole 2ch", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 48000},
        {"index": 2, "name": "MacBook Pro Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
        {"index": 3, "name": "USB Microphone", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48000},
    ],
    default_input=2,
)
audio.sd = mac_sd
try:
    check("macOS Core Audio default mic stays first",
          audio.candidate_devices(None)[0] == 2)
    check("macOS virtual loopback is skipped",
          1 not in audio.candidate_devices(None))
finally:
    audio.sd = real_sd


linux_sd = FakeSD(
    hostapis=[
        {"name": "ALSA", "default_input_device": 1},
        {"name": "PulseAudio", "default_input_device": 3},
    ],
    devices=[
        {"index": 0, "name": "HDMI Output", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48000},
        {"index": 1, "name": "hw:0,0", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 48000},
        {"index": 2, "name": "Monitor of Built-in Audio Analog Stereo", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000},
        {"index": 3, "name": "Built-in Audio Analog Stereo", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000},
    ],
    default_input=3,
)
audio.sd = linux_sd
try:
    cands = audio.candidate_devices(None)
    check("Linux PulseAudio default input is kept first",
          cands[0] == 3)
    check("Linux monitor loopback is skipped",
          2 not in cands)
finally:
    audio.sd = real_sd


windows_sd = FakeSD(
    hostapis=[
        {"name": "MME", "default_input_device": 1},
        {"name": "Windows DirectSound", "default_input_device": 8},
        {"name": "Windows WASAPI", "default_input_device": 18},
        {"name": "Windows WDM-KS", "default_input_device": 27},
    ],
    devices=[
        {"index": 1, "name": "Microphone Array (Realtek(R) Au", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 44100},
        {"index": 8, "name": "Microphone Array (Realtek(R) Audio)", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 44100},
        {"index": 17, "name": "Desktop Microphone (Wireless GO II RX)", "max_input_channels": 2, "hostapi": 2, "default_samplerate": 48000},
        {"index": 18, "name": "Microphone Array (Realtek(R) Audio)", "max_input_channels": 2, "hostapi": 2, "default_samplerate": 48000},
        {"index": 22, "name": "PC Speaker (Realtek HD Audio output with SST)", "max_input_channels": 2, "hostapi": 3, "default_samplerate": 48000},
        {"index": 27, "name": "Microphone Array (Realtek HD Audio Mic Array input)", "max_input_channels": 2, "hostapi": 3, "default_samplerate": 48000},
    ],
    default_input=1,
)
audio.sd = windows_sd
try:
    cands = audio.candidate_devices(None)
    check("Windows WASAPI Settings default beats another connected WASAPI mic",
          cands[0] == 18)
    check("Windows PC Speaker pseudo-input is skipped",
          22 not in cands)
    check("explicit configured device still wins",
          audio.candidate_devices(17)[0] == 17)
finally:
    audio.sd = real_sd

passed = sum(cases)
print(f"\n{passed}/{len(cases)} passed")
sys.exit(0 if passed == len(cases) else 1)
