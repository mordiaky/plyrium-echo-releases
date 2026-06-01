; Plyrium Echo installer (NSIS, Modern UI 2).
; Build:  & "C:\Program Files (x86)\NSIS\makensis.exe" PlyriumEcho.nsi
; Output: dist\Plyrium-Echo-Setup.exe
;
; Per-user install (no admin / no UAC prompt) into %LOCALAPPDATA%\Programs.
; Packages the SLIM onedir build from dist\Plyrium Echo. User data (license,
; downloaded models, history) lives separately in %LOCALAPPDATA%\Plyrium Echo
; and is intentionally LEFT IN PLACE on uninstall so a reinstall keeps the
; paid license + models.

Unicode true
!include "MUI2.nsh"

!define APPNAME "Plyrium Echo"
!define COMPANY "Plyrium"
!define VERSION "1.0.5"
!define EXENAME "Plyrium Echo.exe"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlyriumEcho"

Name "${APPNAME}"
OutFile "dist\Plyrium-Echo-Setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "Software\${APPNAME}" "InstallDir"
SetCompressor /SOLID lzma

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "CompanyName" "${COMPANY}"
VIAddVersionKey "FileDescription" "${APPNAME} installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "© ${COMPANY}"

!define MUI_ICON "assets\echo.ico"
!define MUI_UNICON "assets\echo.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXENAME}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APPNAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  ; close a running copy so files aren't locked
  nsExec::Exec 'taskkill /F /IM "${EXENAME}"'
  Sleep 800

  SetOutPath "$INSTDIR"
  File /r "dist\Plyrium Echo\*"

  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\${EXENAME}" 0

  WriteRegStr HKCU "Software\${APPNAME}" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Add/Remove Programs (per-user)
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"       "${COMPANY}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\${EXENAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /F /IM "${EXENAME}"'
  Sleep 800
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  ; Note: we deliberately do NOT delete %LOCALAPPDATA%\${APPNAME}
  ; (license + downloaded models + history) so reinstalling keeps them.
SectionEnd
