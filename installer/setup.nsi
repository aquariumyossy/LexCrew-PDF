Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma

!include MUI2.nsh
!include x64.nsh
!include FileFunc.nsh

!ifndef VERSION
  !error "VERSION is required"
!endif
!ifndef OUTFILE
  !error "OUTFILE is required"
!endif
!ifndef PAYLOAD
  !error "PAYLOAD is required"
!endif
!ifndef ICON
  !error "ICON is required"
!endif
!ifndef SHORTCUT
  !error "SHORTCUT is required"
!endif
!ifndef STOP
  !error "STOP is required"
!endif

!define APP_NAME "LexCrew PDF"
!define APP_DIR "LexCrew-PDF"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_DIR}"

Name "${APP_NAME}"
Caption "${APP_NAME} セットアップ"
BrandingText "${APP_NAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP_DIR}"
RequestExecutionLevel user

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "${APP_NAME} のインストール"
!define MUI_WELCOMEPAGE_TEXT "LexCrew PDF を、今サインインしているユーザーにインストールします。管理者権限は不要です。$\r$\n$\r$\nインストール先は AppData\Local\Programs\LexCrew-PDF です。$\r$\n$\r$\n入れ直しても、ダウンロードフォルダの LexCrew-PDF-Downloads にある証拠PDFと配置は残ります。起動中の LexCrew PDF は終了します。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES

; MUI は RUN のチェックを上に置き、完了時は RUN の関数を先に呼ぶ。
; ショートカットを作ってから起動するため、上をデスクトップ、下を起動にする。
!define MUI_FINISHPAGE_TITLE "インストールの完了"
!define MUI_FINISHPAGE_TEXT "LexCrew PDF をインストールしました。$\r$\n$\r$\nスタートメニューの「LexCrew PDF」から起動できます。"
!define MUI_FINISHPAGE_NOAUTOCLOSE
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "デスクトップにショートカットを作る"
!define MUI_FINISHPAGE_RUN_FUNCTION CreateDesktopShortcut
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "今すぐ起動"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION RunApp
!insertmacro MUI_PAGE_FINISH

!define MUI_UNCONFIRMPAGE_TEXT_TOP "LexCrew PDF をアンインストールします。$\r$\n$\r$\nダウンロードフォルダの LexCrew-PDF-Downloads にある証拠PDFと、layout.json などの配置は消しません。"
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "Japanese"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "FileDescription" "${APP_NAME} セットアップ"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright (C) 2026 吉田秀平"

Var PowerShell
Var LinkStrict

Function .onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "LexCrew PDF は 64 ビットの Windows が必要です。"
    Abort
  ${EndIf}
FunctionEnd

Function un.onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "LexCrew PDF は 64 ビットの Windows が必要です。"
    Abort
  ${EndIf}
FunctionEnd

Function FindPowerShell
  IfFileExists "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" ps_sysnative ps_system32
  ps_sysnative:
    StrCpy $PowerShell "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
    Return
  ps_system32:
    IfFileExists "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" ps_ok ps_missing
  ps_ok:
    StrCpy $PowerShell "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    Return
  ps_missing:
    MessageBox MB_ICONSTOP "PowerShell が見つかりません。LexCrew PDF は 64 ビットの Windows が必要です。"
    Abort
FunctionEnd

Function un.FindPowerShell
  IfFileExists "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" un_ps_sysnative un_ps_system32
  un_ps_sysnative:
    StrCpy $PowerShell "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
    Return
  un_ps_system32:
    IfFileExists "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" un_ps_ok un_ps_missing
  un_ps_ok:
    StrCpy $PowerShell "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    Return
  un_ps_missing:
    MessageBox MB_ICONSTOP "PowerShell が見つかりません。LexCrew PDF は 64 ビットの Windows が必要です。"
    Abort
FunctionEnd

Function CreateLink
  Pop $0
  ExecWait '"$PowerShell" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\Shortcut.ps1" -SkipUnblock -AppRoot "$INSTDIR" -LinkPath "$0"' $1
  ${If} $1 <> 0
    ${If} $LinkStrict == "yes"
      MessageBox MB_ICONSTOP "ショートカットを作れませんでした。"
      Abort
    ${Else}
      MessageBox MB_ICONEXCLAMATION "デスクトップのショートカットを作れませんでした。"
    ${EndIf}
  ${EndIf}
FunctionEnd

Function CreateDesktopShortcut
  StrCpy $LinkStrict "no"
  Push "$DESKTOP\${APP_NAME}.lnk"
  Call CreateLink
FunctionEnd

Function RunApp
  IfFileExists "$SMPROGRAMS\${APP_NAME}.lnk" 0 run_direct
    ExecShell "open" "$SMPROGRAMS\${APP_NAME}.lnk"
    Return
  run_direct:
    Exec '"$INSTDIR\runtime\pythonw.exe" -m lexcrew_pdf'
FunctionEnd

Section
  SetShellVarContext current
  Call FindPowerShell

  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "/oname=Stop-App.ps1" "${STOP}"
  File "/oname=Shortcut.ps1" "${SHORTCUT}"

  IfFileExists "$INSTDIR\runtime\pythonw.exe" 0 remove_old
    DetailPrint "起動中の LexCrew PDF を終了しています..."
    ExecWait '"$PowerShell" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\Stop-App.ps1" -AppRoot "$INSTDIR"' $0
    ${If} $0 <> 0
      MessageBox MB_ICONSTOP "LexCrew PDF を終了できません。閉じてから、もう一度インストールしてください。"
      Abort
    ${EndIf}
  remove_old:
  IfFileExists "$INSTDIR" 0 copy_files
    RMDir /r "$INSTDIR"
    IfFileExists "$INSTDIR" 0 copy_files
      MessageBox MB_ICONSTOP "インストール先のファイルを置き換えられません。LexCrew PDF を終了してから、もう一度実行してください。$\r$\n$\r$\n$INSTDIR"
      Abort
  copy_files:
  DetailPrint "ファイルをコピーしています..."
  SetOutPath "$INSTDIR"
  File /r /x "LexCrew-PDF.bat" /x "停止.bat" /x "Shortcut.ps1" "${PAYLOAD}\*.*"

  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "吉田秀平"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\LexCrew-PDF.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"

  DetailPrint "スタートメニューに登録しています..."
  StrCpy $LinkStrict "yes"
  Push "$SMPROGRAMS\${APP_NAME}.lnk"
  Call CreateLink
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ; 作業ディレクトリがインストール先のままだと、そのフォルダを消せない。
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  IfFileExists "$INSTDIR\runtime\pythonw.exe" 0 un_delete
    Call un.FindPowerShell
    File "/oname=Stop-App.ps1" "${STOP}"
    DetailPrint "起動中の LexCrew PDF を終了しています..."
    ExecWait '"$PowerShell" -NoProfile -ExecutionPolicy Bypass -File "$PLUGINSDIR\Stop-App.ps1" -AppRoot "$INSTDIR"' $0
    ${If} $0 <> 0
      MessageBox MB_ICONSTOP "LexCrew PDF を終了できません。閉じてから、もう一度アンインストールしてください。"
      Abort
    ${EndIf}
  un_delete:
  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$INSTDIR"
  IfFileExists "$INSTDIR" 0 un_registry
    MessageBox MB_ICONEXCLAMATION "一部のファイルが残っています。閉じてから、もう一度アンインストールしてください。$\r$\n$\r$\n$INSTDIR"
    Abort
  un_registry:
  DeleteRegKey HKCU "${UNINST_KEY}"
SectionEnd
