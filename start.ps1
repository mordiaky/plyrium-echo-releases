# Launch Plyrium Echo as a windowless tray app (no console window).
# Uses pythonw.exe so it runs in the background with just the tray icon.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPyw = Join-Path $here ".venv\Scripts\pythonw.exe"
$venvPy = Join-Path $here ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "No .venv found. Run setup first:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File .\setup.ps1"
    exit 1
}
$exe = if (Test-Path $venvPyw) { $venvPyw } else { $venvPy }
Start-Process -FilePath $exe -ArgumentList (Join-Path $here "run.py") -WorkingDirectory $here
Write-Host "Plyrium Echo started in the system tray." -ForegroundColor Green
Write-Host "(Hotkeys work because YOU launched it — a process started by another app can't see your keyboard.)" -ForegroundColor DarkGray
