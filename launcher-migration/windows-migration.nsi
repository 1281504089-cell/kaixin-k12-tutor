; Launcher-only migration. SOURCE is the already stripped, final packaged app.
; Required: SOURCE, OUTFILE, ICON, VERSION, FILEVERSION.
; The audited helper and payload manifest are already inside SOURCE.
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef APPNAME
  !define APPNAME "开心动力超级学霸"
!endif
!define EXE "${APPNAME}.exe"
!define REG "Software\${APPNAME}"

Name "${APPNAME} 启动器修复"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "${REG}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID zlib
BrandingText "${APPNAME} 启动器修复 ${VERSION}"
VIProductVersion "${FILEVERSION}"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} 启动器修复 ${VERSION}"
VIAddVersionKey "CompanyName" "开心动力"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${FILEVERSION}"
!define MUI_ICON "${ICON}"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "SimpChinese"

Var ProfileDir
Var ExpectedDir
Var StageDir
Var RollbackDir
Var CheckRoot
Var CheckReport
Var CheckExit
Var SavedElectronMode

Function .onInit
  SetShellVarContext current
  StrCpy $LANGUAGE ${LANG_SIMPCHINESE}
  StrCpy $ProfileDir "$LOCALAPPDATA\${APPNAME}"
!ifdef TEST_MODE
  ReadEnvStr $ProfileDir "OPEN_DEEPTUTOR_TEST_HOME"
  ${If} $ProfileDir == ""
    MessageBox MB_ICONSTOP "隔离验收必须设置 OPEN_DEEPTUTOR_TEST_HOME。" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  GetFullPathName $ProfileDir "$ProfileDir"
  ${If} $ProfileDir == "$LOCALAPPDATA\${APPNAME}"
    MessageBox MB_ICONSTOP "隔离验收不能使用正式学习目录。" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
!else
  ReadRegStr $ExpectedDir HKCU "${REG}" "InstallDir"
  ${If} $ExpectedDir == ""
    StrCpy $ExpectedDir "$LOCALAPPDATA\Programs\${APPNAME}"
  ${EndIf}
  GetFullPathName $ExpectedDir "$ExpectedDir"
  GetFullPathName $INSTDIR "$INSTDIR"
  ${If} $INSTDIR != $ExpectedDir
    MessageBox MB_ICONSTOP "请修复已有固定安装目录，不能用此更新包迁移到其他目录。" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
!endif
  StrCpy $StageDir "$INSTDIR.launcher-${VERSION}.stage"
  StrCpy $RollbackDir "$INSTDIR.launcher-${VERSION}.rollback"
FunctionEnd

; The checker receives only paths. It must reject an unverified profile, unsafe
; paths, unrelated old app directories and running app/backend processes.
Function CheckMigration
  ReadEnvStr $SavedElectronMode "ELECTRON_RUN_AS_NODE"
  ClearErrors
  System::Call 'kernel32::SetEnvironmentVariableW(w "ELECTRON_RUN_AS_NODE", w "1") i .r0'
  StrCpy $CheckExit "error"
!ifdef TEST_MODE
  ExecWait '"$CheckRoot\${EXE}" "$CheckRoot\resources\app\launcher-migration-check.mjs" --profile "$ProfileDir" --install-dir "$INSTDIR" --target windows-x64 --report-file "$CheckReport" --require-isolated' $CheckExit
!else
  ExecWait '"$CheckRoot\${EXE}" "$CheckRoot\resources\app\launcher-migration-check.mjs" --profile "$ProfileDir" --install-dir "$INSTDIR" --target windows-x64 --report-file "$CheckReport"' $CheckExit
!endif
  IfErrors 0 checker_returned
  StrCpy $CheckExit "error"
  checker_returned:
  ${If} $SavedElectronMode == ""
    System::Call 'kernel32::SetEnvironmentVariableW(w "ELECTRON_RUN_AS_NODE", p 0) i .r0'
  ${Else}
    System::Call 'kernel32::SetEnvironmentVariableW(w "ELECTRON_RUN_AS_NODE", w "$SavedElectronMode") i .r0'
  ${EndIf}
  ${If} $CheckExit == 0
    ; A zero exit from an incorrectly launched GUI is not a completed check.
    IfFileExists "$CheckReport" 0 checker_failed
    Return
  ${EndIf}
  checker_failed:
  MessageBox MB_ICONSTOP "迁移检查未通过。请退出软件并确认已有完整运行环境；原程序和学习数据未改动。" /SD IDOK
  SetErrorLevel 3
  Abort
FunctionEnd

Section "启动器修复"
  IfFileExists "$ProfileDir\active.json" 0 preflight_failed
  IfFileExists "$ProfileDir\runtimes\." 0 preflight_failed
  IfFileExists "$INSTDIR\${EXE}" 0 preflight_failed
  IfFileExists "$INSTDIR\resources\app\package.json" 0 preflight_failed
  ; Never overwrite a previous rollback or an interrupted staging directory.
  IfFileExists "$StageDir\." preflight_failed
  IfFileExists "$RollbackDir\." preflight_failed
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${SOURCE}\*"
  SetOutPath "$PLUGINSDIR"
  StrCpy $CheckRoot "$PLUGINSDIR\payload"
  StrCpy $CheckReport "$PLUGINSDIR\migration-check-payload.json"
  Call CheckMigration

  ClearErrors
  CreateDirectory "$StageDir"
  IfErrors staging_failed
  CopyFiles /SILENT "$PLUGINSDIR\payload\*.*" "$StageDir"
  IfErrors staging_failed
  ; Verify the copied payload and reject an app reopened during copying.
  StrCpy $CheckRoot "$StageDir"
  StrCpy $CheckReport "$PLUGINSDIR\migration-check-staged.json"
  Call CheckMigration
  ; The existing uninstall registration continues pointing to its original file.
  IfFileExists "$INSTDIR\Uninstall ${APPNAME}.exe" 0 uninstaller_preserved
  CopyFiles /SILENT /FILESONLY "$INSTDIR\Uninstall ${APPNAME}.exe" "$StageDir"
  IfErrors staging_failed
  uninstaller_preserved:
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  Rename "$INSTDIR" "$RollbackDir"
  IfErrors staging_failed
  ClearErrors
  Rename "$StageDir" "$INSTDIR"
  IfErrors restore_old_app

!ifndef TEST_MODE
  ClearErrors
  CreateShortcut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${EXE}"
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${REG}" "InstallDir" "$INSTDIR"
  IfErrors restore_after_activation
!endif
  DetailPrint "启动器修复完成；旧程序保留在 $RollbackDir。"
  SetErrorLevel 0
  Goto done

  restore_after_activation:
    ClearErrors
    Rename "$INSTDIR" "$StageDir"
    IfErrors rollback_failed
  restore_old_app:
    ClearErrors
    Rename "$RollbackDir" "$INSTDIR"
    IfErrors rollback_failed
    MessageBox MB_ICONSTOP "启动器安装未完成，已恢复原程序。新程序保留在暂存目录，学习数据未改动。" /SD IDOK
    SetErrorLevel 4
    Abort
  rollback_failed:
    MessageBox MB_ICONSTOP "程序目录恢复未完成。请保留暂存与 rollback 目录并联系维护人员；学习目录未改动。" /SD IDOK
    SetErrorLevel 5
    Abort
  staging_failed:
    MessageBox MB_ICONSTOP "启动器复制失败，原程序未替换。请保留暂存目录并检查磁盘空间。" /SD IDOK
    SetErrorLevel 4
    Abort
  preflight_failed:
    MessageBox MB_ICONSTOP "找不到已有完整安装，或发现上次迁移备份。请核对原固定安装位置；此修复包不能用于首次安装。" /SD IDOK
    SetErrorLevel 2
    Abort
  done:
SectionEnd
