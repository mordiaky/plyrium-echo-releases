# Plyrium Echo — one-time setup.
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
# Creates a local venv, installs dependencies, auto-detects an NVIDIA GPU and
# installs the CUDA wheels if present, then downloads the Whisper model once.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$python = "py"; $pyArgs = @("-3.12")
try { & $python $pyArgs --version | Out-Null } catch { $python = "python"; $pyArgs = @() }

if (-not (Test-Path ".\.venv")) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
    & $python @pyArgs -m venv .venv
}
$venvPy = ".\.venv\Scripts\python.exe"

Write-Host "Upgrading pip..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip | Out-Null

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $venvPy -m pip install -r requirements.txt

# GPU: if an NVIDIA card is present, install the CUDA 12 runtime wheels so
# faster-whisper can use it (no system CUDA toolkit needed).
$hasGpu = $false
try { & nvidia-smi | Out-Null; $hasGpu = $? } catch { $hasGpu = $false }
if ($hasGpu) {
    Write-Host "NVIDIA GPU detected — installing CUDA acceleration wheels..." -ForegroundColor Cyan
    & $venvPy -m pip install -r requirements-gpu.txt
} else {
    Write-Host "No NVIDIA GPU detected — running on CPU (still fast enough for dictation)." -ForegroundColor Yellow
}

# One-time online step: cache the Whisper model. The ONLY time the app uses the
# network. Degrades gracefully with no connection (re-run --download-model later).
Write-Host ""
Write-Host "Downloading the Whisper model (one-time, needs internet)..." -ForegroundColor Cyan
& $venvPy run.py --download-model

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Verify:        .\.venv\Scripts\python.exe run.py --check"
Write-Host "  Start (tray):  .\start.ps1"
Write-Host "  Run on login:  powershell -ExecutionPolicy Bypass -File .\install-autostart.ps1"
