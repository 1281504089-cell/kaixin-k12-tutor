; 开心动力超级学霸（Windows） installer. Built by package.mjs, which defines
; SOURCE (packaged app folder), OUTFILE, ICON, VERSION and FILEVERSION.
; Installs for the current user only, so no administrator prompt.

Unicode true
!include "MUI2.nsh"

!define APP "开心动力超级学霸"
!define EXE "开心动力超级学霸.exe"
!define REG "Software\开心动力超级学霸"
!define UNINSTALL "Software\Microsoft\Windows\CurrentVersion\Uninstall\开心动力超级学霸"

Name "${APP}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${REG}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "开心动力超级学霸（Windows） v${VERSION}"

VIProductVersion "${FILEVERSION}"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "FileDescription" "开心动力超级学霸（Windows） v${VERSION} Setup"
VIAddVersionKey "CompanyName" "开心动力"
VIAddVersionKey "LegalCopyright" "Copyright HKUDS. Licensed under Apache-2.0."
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${FILEVERSION}"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

; The app's own files, never the whole folder: the user may have chosen a
; folder that holds other things. Learning data lives in
; %LOCALAPPDATA%\开心动力超级学霸 and survives upgrades and uninstalls.
!macro RemoveAppFiles
  RMDir /r "$INSTDIR\resources"
  RMDir /r "$INSTDIR\locales"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\d3dcompiler_47.dll"
  Delete "$INSTDIR\dxcompiler.dll"
  Delete "$INSTDIR\electron_wer.dll"
  Delete "$INSTDIR\ffmpeg.dll"
  Delete "$INSTDIR\vk_swiftshader.dll"
  Delete "$INSTDIR\vulkan-1.dll"
  Delete "$INSTDIR\chrome_100_percent.pak"
  Delete "$INSTDIR\chrome_200_percent.pak"
  Delete "$INSTDIR\resources.pak"
  Delete "$INSTDIR\snapshot_blob.bin"
  Delete "$INSTDIR\v8_context_snapshot.bin"
  Delete "$INSTDIR\icudtl.dat"
  Delete "$INSTDIR\vk_swiftshader_icd.json"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\LICENSES.chromium.html"
  Delete "$INSTDIR\version"
!macroend

Section
  ; Validate the external payload before replacing any installed app files.
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=parts.json "${PARTS_MANIFEST}"
  File /oname=join-payload.ps1 "join-payload.ps1"
  CreateDirectory "$INSTDIR"
  GetTempFileName $R0 "$INSTDIR"
  DetailPrint "正在校验本机运行资源，请稍候……"
  System::Call 'kernel32::SetEnvironmentVariableW(w "KX_PARTS_MANIFEST", w "$PLUGINSDIR\parts.json") i .r0'
  System::Call 'kernel32::SetEnvironmentVariableW(w "KX_PARTS_DIRECTORY", w "$EXEDIR") i .r0'
  System::Call 'kernel32::SetEnvironmentVariableW(w "KX_PAYLOAD_OUTPUT", w "$R0") i .r0'
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -InputFormat None -ExecutionPolicy Bypass -File "$PLUGINSDIR\join-payload.ps1"'
  Pop $0
  Pop $1
  StrCmp $0 "0" payload_verified
    Delete "$R0"
    MessageBox MB_ICONSTOP "请将全部 Runtime 分卷与安装程序放在同一文件夹，并确认磁盘空间充足。资源校验失败，原安装未改动。" /SD IDOK
    Abort
  payload_verified:
  SetOutPath "$INSTDIR"
  ; Replaces the previous version, including its bundled core.
  !insertmacro RemoveAppFiles
  File /r /x seed "${SOURCE}\*"
  SetOutPath "$INSTDIR\resources\seed"
  File /oname=runtime.json "${SOURCE}\resources\seed\runtime.json"
  Rename "$R0" "$INSTDIR\resources\seed\${ARCHIVE_NAME}"
  IfErrors 0 +4
    Delete "$R0"
    MessageBox MB_ICONSTOP "运行资源复制失败。请检查磁盘空间后重新安装；学习数据保留。" /SD IDOK
    Abort
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall ${APP}.exe"
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${EXE}"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${REG}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayName" "开心动力超级学霸（Windows）"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL}" "Publisher" "开心动力"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${UNINSTALL}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL}" "UninstallString" '"$INSTDIR\Uninstall ${APP}.exe"'
  WriteRegDWORD HKCU "${UNINSTALL}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  !insertmacro RemoveAppFiles
  Delete "$INSTDIR\Uninstall ${APP}.exe"
  RMDir "$INSTDIR"
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKCU "${UNINSTALL}"
  DeleteRegKey HKCU "${REG}"
SectionEnd
