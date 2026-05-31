# Register Plyrium Echo to launch (windowless tray) when you log in to Windows.
# Creates a shortcut in the user's Startup folder. Remove it any time with
# uninstall-autostart.ps1 (or delete the shortcut from shell:startup).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPyw = Join-Path $here ".venv\Scripts\pythonw.exe"
$venvPy = Join-Path $here ".venv\Scripts\python.exe"
$exe = if (Test-Path $venvPyw) { $venvPyw } else { $venvPy }
if (-not (Test-Path $exe)) {
    Write-Host "No .venv found. Run setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

$startup = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startup "Plyrium Echo.lnk"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnkPath)
$sc.TargetPath = $exe
$sc.Arguments = "`"$(Join-Path $here 'run.py')`""
$sc.WorkingDirectory = $here
$sc.WindowStyle = 7   # minimized
$sc.Description = "Plyrium Echo — offline voice dictation"
$sc.Save()

Write-Host "Installed. Plyrium Echo will start on login." -ForegroundColor Green
Write-Host "  Shortcut: $lnkPath"
Write-Host "  Remove with: powershell -ExecutionPolicy Bypass -File .\uninstall-autostart.ps1"
