# Plyrium Echo

**Wispr-style push-to-talk dictation that runs 100% on your machine.**

Hold a hotkey, speak, release — clean, punctuated text is typed into whatever
window you're in. Transcription (Whisper) and the optional AI cleanup both run
**locally**. Your voice and your text never leave your computer.

## Download

Grab the latest **`Plyrium-Echo-Setup.exe`** from
[Releases](../../releases/latest). It's a per-user install (no admin prompt).

> **Windows SmartScreen** may warn because the installer isn't code-signed yet.
> Click **More info → Run anyway**. (Verify the download with the SHA-256 in
> `SHA256SUMS.txt` on the release if you like.)

## How it works

- Hold **Ctrl+Win** and talk; release to insert the text. Tap **Ctrl+Win+Space**
  for hands-free. (All shortcuts are changeable in Settings.)
- A small waveform pill shows while you speak; other audio dips so the mic
  focuses on your voice.
- Right-click the tray icon or open the window for History, Settings, your
  custom Dictionary, and stats.

## First run

- On first launch it downloads the speech model once (small, fast — works on
  any CPU). Everything after that is offline.
- **NVIDIA GPU?** Pick the **Large** model and Echo automatically fetches CUDA
  and runs on your GPU — much faster, more accurate. AMD/Intel/no-GPU machines
  run great on CPU.
- **14-day free trial**, then a one-time license. Buy at **plyrium.com**.

## System requirements

- Windows 10 or 11 (64-bit)
- ~1 GB free disk (plus ~2 GB if you enable GPU acceleration)
- 8 GB RAM recommended
- NVIDIA GPU **optional** (auto-accelerated); not required

---

Part of the Plyrium family. © Plyrium.
