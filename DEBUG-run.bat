@echo off
REM Launches Plyrium Echo with FULL debug logging (hotkey + audio).
REM Logs land in:  %TEMP%\plyrium-echo-hotkey.log  and  plyrium-echo-audio.log
setlocal
set PLYRIUM_ECHO_DEBUG=1
del "%TEMP%\plyrium-echo-hotkey.log" 2>nul
del "%TEMP%\plyrium-echo-audio.log" 2>nul
echo Starting Plyrium Echo (debug mode)...
echo.
echo 1) Wait ~10s for the tray icon.
echo 2) Click into Notepad, HOLD Ctrl+Win ~1s and release. Do it 2-3 times.
echo 3) Right-click the tray icon - Quit.
echo 4) Tell Claude "done".
echo.
start "" "%~dp0dist\Plyrium Echo\Plyrium Echo.exe"
