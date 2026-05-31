# Remove Plyrium Echo from Windows login startup.
$startup = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startup "Plyrium Echo.lnk"
if (Test-Path $lnkPath) {
    Remove-Item $lnkPath -Force
    Write-Host "Removed autostart shortcut." -ForegroundColor Green
} else {
    Write-Host "No autostart shortcut found (nothing to remove)." -ForegroundColor Yellow
}
