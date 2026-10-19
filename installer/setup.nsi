Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma

!include MUI2.nsh
!include LogicLib.nsh
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

!define APP_NAME "LexCrew PDF"
!define APP_DIR "LexCrew-PDF"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_DIR}"
!define APP_MUTEX "Local\LexCrew-PDF"
!define LEGACY_ARGS "-m lexcrew_pdf"
!define LEGACY_SUFFIX "\runtime\pythonw.exe"

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
!define MUI_WELCOMEPAGE_TEXT "LexCrew PDF を、今サインインしているユーザーにインストールします。管理者権限は不要です。$\r$\n$\r$\nインストール先は AppData\Local\Programs\LexCrew-PDF です。$\r$\n$\r$\n起動中の LexCrew PDF は終了します。以前のフォルダで動いているものも終了します。他の Python は止めません。以前のフォルダ自体は消しません。$\r$\n$\r$\nデスクトップの「LexCrew-PDF」は、このアプリが作ったショートカットだと確かめられたときだけ消します。$\r$\n$\r$\n入れ直しても、ダウンロードフォルダの LexCrew-PDF-Downloads にある証拠PDFと配置は残ります。"
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

!define MUI_UNCONFIRMPAGE_TEXT_TOP "LexCrew PDF をアンインストールします。$\r$\n$\r$\n消すのは、このアプリが入れたファイルです。ダウンロードフォルダの LexCrew-PDF-Downloads にある証拠PDFと、layout.json などの配置は消しません。以前のフォルダも消しません。"
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
Var UninstDir

; パスの末尾の \ を1つ取る。長さ3以下（C:\ など）はそのまま。
!macro NormalizeDir UN
Function ${UN}NormalizeDir
  Exch $0
  Push $1
  Push $2
  StrLen $1 $0
  ${If} $1 > 3
    StrCpy $2 $0 1 -1
    ${If} $2 == "\"
      IntOp $1 $1 - 1
      StrCpy $0 $0 $1
    ${EndIf}
  ${EndIf}
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

!macro CheckProtected UN raw
  Push "${raw}"
  Call ${UN}NormalizeDir
  Pop $1
  ${If} $1 != ""
  ${AndIf} $0 == $1
    StrCpy $2 "yes"
  ${EndIf}
!macroend

; スタックのパスが、消してはいけない場所なら yes。
!macro IsProtectedDir UN
Function ${UN}IsProtectedDir
  Exch $0
  Push $1
  Push $2
  Push $0
  Call ${UN}NormalizeDir
  Pop $0
  StrCpy $2 "no"
  StrLen $1 $0
  ${If} $1 <= 3
    StrCpy $2 "yes"
  ${Else}
    !insertmacro CheckProtected "${UN}" "$DESKTOP"
    !insertmacro CheckProtected "${UN}" "$DOCUMENTS"
    !insertmacro CheckProtected "${UN}" "$PROFILE"
    !insertmacro CheckProtected "${UN}" "$APPDATA"
    !insertmacro CheckProtected "${UN}" "$LOCALAPPDATA"
    !insertmacro CheckProtected "${UN}" "$LOCALAPPDATA\Programs"
    !insertmacro CheckProtected "${UN}" "$WINDIR"
    !insertmacro CheckProtected "${UN}" "$SYSDIR"
    !insertmacro CheckProtected "${UN}" "$PROGRAMFILES"
    !insertmacro CheckProtected "${UN}" "$PROGRAMFILES32"
    !insertmacro CheckProtected "${UN}" "$PROGRAMFILES64"
    !insertmacro CheckProtected "${UN}" "$TEMP"
    !insertmacro CheckProtected "${UN}" "$SMPROGRAMS"
    !insertmacro CheckProtected "${UN}" "$STARTMENU"
    !insertmacro CheckProtected "${UN}" "$SMSTARTUP"
    !insertmacro CheckProtected "${UN}" "$QUICKLAUNCH"
    !insertmacro CheckProtected "${UN}" "$PROFILE\Downloads"
  ${EndIf}
  StrCpy $0 $2
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

; このアプリのインストール先なら yes。マーカーか、以前のセットアップの配置。
!macro IsOurInstall UN
Function ${UN}IsOurInstall
  Push $0
  Push $1
  Push $2
  Push $INSTDIR
  Call ${UN}IsProtectedDir
  Pop $0
  StrCpy $1 "no"
  ${If} $0 != "yes"
    ClearErrors
    FileOpen $0 "$INSTDIR\lexcrew-pdf.install" r
    ${IfNot} ${Errors}
      FileRead $0 $2 64
      FileClose $0
      ${If} $2 == "LexCrew-PDF"
      ${OrIf} $2 == "LexCrew-PDF$\r$\n"
      ${OrIf} $2 == "LexCrew-PDF$\r"
      ${OrIf} $2 == "LexCrew-PDF$\n"
        StrCpy $1 "yes"
      ${EndIf}
    ${EndIf}
    ${If} $1 != "yes"
      ${If} ${FileExists} "$INSTDIR\runtime\pythonw.exe"
      ${AndIf} ${FileExists} "$INSTDIR\src\lexcrew_pdf\__main__.py"
        StrCpy $1 "yes"
      ${EndIf}
    ${EndIf}
  ${EndIf}
  StrCpy $0 $1
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

; runtime / src / ui と、セットアップが置いたファイルだけ消す。
!macro RemovePayload UN
Function ${UN}RemovePayload
  Push $0
  Call ${UN}IsOurInstall
  Pop $0
  ${If} $0 != "yes"
    StrCpy $0 "foreign"
  ${Else}
    RMDir /r "$INSTDIR\runtime"
    RMDir /r "$INSTDIR\src"
    RMDir /r "$INSTDIR\ui"
    Delete "$INSTDIR\LexCrew-PDF.ico"
    Delete "$INSTDIR\使い方.txt"
    Delete "$INSTDIR\LICENSE"
    Delete "$INSTDIR\ライセンス.txt"
    Delete "$INSTDIR\lexcrew-pdf.install"
    StrCpy $0 "ok"
    ${If} ${FileExists} "$INSTDIR\runtime"
      StrCpy $0 "busy"
    ${EndIf}
    ${If} ${FileExists} "$INSTDIR\src"
      StrCpy $0 "busy"
    ${EndIf}
    ${If} ${FileExists} "$INSTDIR\ui"
      StrCpy $0 "busy"
    ${EndIf}
  ${EndIf}
  Exch $0
FunctionEnd
!macroend

; 隠しプロセス。起動できなければ "error"。終了コードは十進の文字列。
!macro ExecHidden UN
Function ${UN}ExecHidden
  Exch $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  StrCpy $1 "error"
  System::Alloc 68
  Pop $2
  System::Alloc 16
  Pop $3
  ${If} $2 <> 0
  ${AndIf} $3 <> 0
    System::Call '*$2(i 68)'
    System::Call 'kernel32::CreateProcessW(p 0, t r0, p 0, p 0, i 0, i 0x08000000, p 0, p 0, p r2, p r3) i .r4'
    ${If} $4 <> 0
      System::Call '*$3(p .r4, p .r5)'
      System::Call 'kernel32::WaitForSingleObject(p r4, i 0xFFFFFFFF)'
      System::Call 'kernel32::GetExitCodeProcess(p r4, *i .r1) i .r0'
      System::Call 'kernel32::CloseHandle(p r4)'
      System::Call 'kernel32::CloseHandle(p r5)'
    ${EndIf}
  ${EndIf}
  ${If} $2 <> 0
    System::Free $2
  ${EndIf}
  ${If} $3 <> 0
    System::Free $3
  ${EndIf}
  StrCpy $0 $1
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

!macro EndsWith UN
Function ${UN}EndsWith
  Exch $1
  Exch
  Exch $0
  Push $2
  Push $3
  Push $4
  Push $5
  StrLen $2 $0
  StrLen $3 $1
  StrCpy $4 "no"
  ${If} $3 <= $2
  ${AndIf} $3 > 0
    IntOp $5 $2 - $3
    StrCpy $2 $0 $3 $5
    ${If} $2 == $1
      StrCpy $4 "yes"
    ${EndIf}
  ${EndIf}
  StrCpy $0 $4
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

!macro ProcessPath UN
Function ${UN}ProcessPath
  Exch $0
  Push $1
  Push $2
  Push $3
  Push $4
  StrCpy $4 ""
  System::Call 'kernel32::OpenProcess(i 0x1000, i 0, i r0) p .r1'
  ${If} $1 <> 0
    System::Alloc 4
    Pop $2
    System::Alloc 520
    Pop $3
    ${If} $2 <> 0
    ${AndIf} $3 <> 0
      System::Call '*$2(i 260)'
      System::Call 'kernel32::QueryFullProcessImageNameW(p r1, i 0, p r3, p r2) i .r0'
      ${If} $0 <> 0
        System::Call '*$3(&w260 .r4)'
      ${EndIf}
    ${EndIf}
    ${If} $2 <> 0
      System::Free $2
    ${EndIf}
    ${If} $3 <> 0
      System::Free $3
    ${EndIf}
    System::Call 'kernel32::CloseHandle(p r1)'
  ${EndIf}
  StrCpy $0 $4
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

!macro KillPid UN
Function ${UN}KillPid
  Exch $0
  Push $1
  Push $2
  ${If} $R8 != ""
    StrCpy $1 '"$R8" /PID $0 /T /F'
    Push $1
    Call ${UN}ExecHidden
    Pop $1
  ${Else}
    StrCpy $1 "error"
  ${EndIf}
  ${If} $1 != "0"
    System::Call 'kernel32::OpenProcess(i 1, i 0, i r0) p .r2'
    ${If} $2 <> 0
      System::Call 'kernel32::TerminateProcess(p r2, i 1)'
      System::Call 'kernel32::CloseHandle(p r2)'
    ${EndIf}
  ${EndIf}
  Pop $2
  Pop $1
  Pop $0
FunctionEnd
!macroend

; $R6 が kill なら一致したプロセスを止める。見つけたら $R7 を yes にする。
; イメージ名が python.exe / pythonw.exe で、パスが runtime 配下、隣にこのアプリの印があるものだけ。
!macro ScanLexCrew UN
Function ${UN}ScanLexCrew
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  Push $R0
  Push $R1
  Push $R3
  Push $R4
  Push $R5
  StrCpy $R7 "no"
  System::Call 'kernel32::CreateToolhelp32Snapshot(i 2, i 0) p .R0'
  ${If} $R0 == 0
    StrCpy $R7 "yes"
  ${Else}
    System::Alloc 556
    Pop $R1
    ${If} $R1 == 0
      System::Call 'kernel32::CloseHandle(p R0)'
      StrCpy $R7 "yes"
    ${Else}
      System::Call '*$R1(i 556)'
      System::Call 'kernel32::Process32FirstW(p R0, p R1) i .r0'
      ${While} $0 <> 0
        System::Call '*$R1(i, i, i .R3, i, i, i, i, i, i, &w260 .R4)'
        ${If} $R4 == "python.exe"
        ${OrIf} $R4 == "pythonw.exe"
          Push $R3
          Call ${UN}ProcessPath
          Pop $R5
          ${If} $R5 != ""
            Push $R5
            Push "\runtime\pythonw.exe"
            Call ${UN}EndsWith
            Pop $1
            StrLen $2 "\runtime\pythonw.exe"
            ${If} $1 != "yes"
              Push $R5
              Push "\runtime\python.exe"
              Call ${UN}EndsWith
              Pop $1
              StrLen $2 "\runtime\python.exe"
            ${EndIf}
            ${If} $1 == "yes"
              StrLen $3 $R5
              IntOp $3 $3 - $2
              StrCpy $4 $R5 $3
              ${If} ${FileExists} "$4\src\lexcrew_pdf\__main__.py"
              ${OrIf} ${FileExists} "$4\LexCrew-PDF.ico"
              ${OrIf} ${FileExists} "$4\lexcrew-pdf.install"
                StrCpy $R7 "yes"
                ${If} $R6 == "kill"
                  Push $R3
                  Call ${UN}KillPid
                ${EndIf}
              ${EndIf}
            ${EndIf}
          ${EndIf}
        ${EndIf}
        System::Call 'kernel32::Process32NextW(p R0, p R1) i .r0'
      ${EndWhile}
      System::Free $R1
      System::Call 'kernel32::CloseHandle(p R0)'
    ${EndIf}
  ${EndIf}
  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R1
  Pop $R0
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd
!macroend

; 止まらなければ busy。ミューテックスはすぐ閉じる。
!macro StopLexCrew UN
Function ${UN}StopLexCrew
  Push $0
  Push $1
  Push $2
  Push $R0
  Push $R6
  Push $R7
  Push $R8
  StrCpy $R8 ""
  ${If} ${FileExists} "$WINDIR\Sysnative\taskkill.exe"
    StrCpy $R8 "$WINDIR\Sysnative\taskkill.exe"
  ${ElseIf} ${FileExists} "$SYSDIR\taskkill.exe"
    StrCpy $R8 "$SYSDIR\taskkill.exe"
  ${EndIf}
  StrCpy $R6 "kill"
  Call ${UN}ScanLexCrew
  StrCpy $0 0
  StrCpy $1 "busy"
  ${Do}
    StrCpy $R6 "check"
    Call ${UN}ScanLexCrew
    System::Call 'kernel32::CreateMutexW(p 0, i 0, t "${APP_MUTEX}") p .R0 ?e'
    Pop $2
    ${If} $R0 <> 0
      System::Call 'kernel32::CloseHandle(p R0)'
    ${EndIf}
    ${If} $R7 != "yes"
    ${AndIf} $2 <> 183
      StrCpy $1 "ok"
      ${Break}
    ${EndIf}
    IntOp $0 $0 + 1
    ${If} $0 >= 20
      ${Break}
    ${EndIf}
    Sleep 250
  ${Loop}
  StrCpy $0 $1
  Pop $R8
  Pop $R7
  Pop $R6
  Pop $R0
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
!macroend

!insertmacro NormalizeDir ""
!insertmacro NormalizeDir "un."
!insertmacro IsProtectedDir ""
!insertmacro IsProtectedDir "un."
!insertmacro IsOurInstall ""
!insertmacro IsOurInstall "un."
!insertmacro RemovePayload ""
!insertmacro RemovePayload "un."
!insertmacro ExecHidden ""
!insertmacro ExecHidden "un."
!insertmacro EndsWith ""
!insertmacro EndsWith "un."
!insertmacro ProcessPath ""
!insertmacro ProcessPath "un."
!insertmacro KillPid ""
!insertmacro KillPid "un."
!insertmacro ScanLexCrew ""
!insertmacro ScanLexCrew "un."
!insertmacro StopLexCrew ""
!insertmacro StopLexCrew "un."

Function .onInit
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\${APP_DIR}"
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "LexCrew PDF は 64 ビットの Windows が必要です。" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function un.onInit
  SetShellVarContext current
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "LexCrew PDF は 64 ビットの Windows が必要です。" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function FindPowerShell
  StrCpy $PowerShell ""
  ${If} ${FileExists} "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
    StrCpy $PowerShell "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  ${ElseIf} ${FileExists} "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    StrCpy $PowerShell "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
  ${EndIf}
FunctionEnd

Function CreateLink
  Pop $0
  StrCpy $1 "error"
  ${If} $PowerShell != ""
  ${AndIf} ${FileExists} "$PLUGINSDIR\Shortcut.ps1"
    StrCpy $2 '"$PowerShell" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\Shortcut.ps1" -SkipUnblock -AppRoot "$INSTDIR" -LinkPath "$0"'
    Push $2
    Call ExecHidden
    Pop $1
  ${EndIf}
  ${If} $1 == "0"
  ${AndIfNot} ${FileExists} "$0"
    ; 起動はできたが、ショートカットが無い。作れなかったものとして戻す。
    StrCpy $1 "error"
  ${EndIf}
  ${If} $1 != "0"
    ClearErrors
    SetOutPath "$INSTDIR"
    CreateShortCut "$0" "$INSTDIR\runtime\pythonw.exe" "-m lexcrew_pdf" "$INSTDIR\LexCrew-PDF.ico" 0
    ${If} ${Errors}
      ${If} $LinkStrict == "yes"
        MessageBox MB_ICONSTOP "ショートカットを作れませんでした。" /SD IDOK
        Abort
      ${Else}
        MessageBox MB_ICONEXCLAMATION "デスクトップのショートカットを作れませんでした。" /SD IDOK
      ${EndIf}
    ${EndIf}
  ${EndIf}
FunctionEnd

Function CreateDesktopShortcut
  StrCpy $LinkStrict "no"
  CreateDirectory "$DESKTOP"
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

; 旧 zip のデスクトップショートカットか。リンク先と引数が一致したときだけ yes。
Function LegacyLinkIsOurs
  Exch $R9
  Push $0
  Push $1
  Push $2
  Push $3
  Push $4
  Push $5
  Push $6
  Push $7
  Push $8
  Push $R0
  Push $R1
  Push $R2
  Push $R3
  Push $R4
  Push $R5
  Push $R6
  StrCpy $8 "no"
  StrCpy $R0 0
  StrCpy $6 0
  StrCpy $R6 ""
  ${IfNot} ${FileExists} "$R9"
    Goto leg_done
  ${EndIf}
  System::Call 'kernel32::CreateFileW(t R9, i 0x80000000, i 1, p 0, i 3, i 0, p 0) p .r6'
  ${If} $6 == 0
  ${OrIf} $6 == -1
  ${OrIf} $6 == 4294967295
    StrCpy $6 0
    Goto leg_done
  ${EndIf}
  System::Alloc 8192
  Pop $R0
  ${If} $R0 == 0
    Goto leg_done
  ${EndIf}
  System::Call 'kernel32::ReadFile(p r6, p R0, i 8192, *i .R1, p 0) i .r0'
  ${If} $0 == 0
    Goto leg_done
  ${EndIf}
  ${If} $R1 < 76
  ${OrIf} $R1 >= 8192
    Goto leg_done
  ${EndIf}
  System::Call '*$R0(&i4 .r0)'
  ${If} $0 != 76
    Goto leg_done
  ${EndIf}
  IntOp $0 $R0 + 20
  System::Call '*$0(&i4 .R2)'
  StrCpy $R3 76
  IntOp $0 $R2 & 1
  ${If} $0 != 0
    IntOp $0 $R0 + $R3
    ${If} $R3 > $R1
      Goto leg_done
    ${EndIf}
    System::Call '*$0(&i2 .r1)'
    ${If} $1 < 0
      Goto leg_done
    ${EndIf}
    IntOp $R3 $R3 + 2
    IntOp $R3 $R3 + $1
  ${EndIf}
  IntOp $0 $R2 & 2
  ${If} $0 == 0
    Goto leg_done
  ${EndIf}
  IntOp $1 $R3 + 28
  ${If} $1 > $R1
    Goto leg_done
  ${EndIf}
  IntOp $0 $R0 + $R3
  System::Call '*$0(&i4 .r1)'
  ${If} $1 < 28
    Goto leg_done
  ${EndIf}
  IntOp $4 $R3 + $1
  ${If} $4 > $R1
    Goto leg_done
  ${EndIf}
  IntOp $2 $0 + 4
  System::Call '*$2(&i4 .r3)'
  IntOp $2 $0 + 8
  System::Call '*$2(&i4 .r5)'
  StrCpy $R5 ""
  IntOp $2 $5 & 1
  ${If} $2 != 0
    ${If} $3 >= 36
      IntOp $2 $0 + 28
      System::Call '*$2(&i4 .r7)'
      ${If} $7 > 0
      ${AndIf} $7 < $1
        IntOp $2 $0 + $7
        System::Call '*$2(&w1024 .R5)'
      ${EndIf}
    ${EndIf}
    ${If} $R5 == ""
      IntOp $2 $0 + 16
      System::Call '*$2(&i4 .r7)'
      ${If} $7 > 0
      ${AndIf} $7 < $1
        IntOp $2 $0 + $7
        System::Call '*$2(&m1024 .R5)'
      ${EndIf}
    ${EndIf}
  ${EndIf}
  ${If} $R5 == ""
    Goto leg_done
  ${EndIf}
  Push $R5
  Push "${LEGACY_SUFFIX}"
  Call EndsWith
  Pop $2
  ${If} $2 != "yes"
    Goto leg_done
  ${EndIf}
  StrCpy $R3 $4
  IntOp $5 $R2 & 0x80
  ${If} $5 != 0
    StrCpy $R4 2
  ${Else}
    StrCpy $R4 1
  ${EndIf}
  StrCpy $7 0
  ${Do}
    ${If} $7 >= 5
      ${Break}
    ${EndIf}
    ${If} $7 == 0
      IntOp $5 $R2 & 4
    ${ElseIf} $7 == 1
      IntOp $5 $R2 & 8
    ${ElseIf} $7 == 2
      IntOp $5 $R2 & 16
    ${ElseIf} $7 == 3
      IntOp $5 $R2 & 32
    ${Else}
      IntOp $5 $R2 & 64
    ${EndIf}
    ${If} $5 != 0
      IntOp $4 $R3 + 2
      ${If} $4 > $R1
        Goto leg_done
      ${EndIf}
      IntOp $1 $R0 + $R3
      System::Call '*$1(&i2 .r5)'
      ${If} $5 < 0
      ${OrIf} $5 > 1023
        Goto leg_done
      ${EndIf}
      IntOp $3 $5 * $R4
      IntOp $4 $R3 + 2
      IntOp $4 $4 + $3
      ${If} $4 > $R1
        Goto leg_done
      ${EndIf}
      ${If} $7 == 3
        IntOp $1 $1 + 2
        System::Alloc 2048
        Pop $3
        ${If} $3 == 0
          Goto leg_done
        ${EndIf}
        IntOp $2 $5 + 1
        ${If} $R4 == 2
          System::Call 'kernel32::lstrcpynW(p r3, p r1, i r2)'
          System::Call '*$3(&w1024 .R6)'
        ${Else}
          System::Call 'kernel32::lstrcpynA(p r3, p r1, i r2)'
          System::Call '*$3(&m1024 .R6)'
        ${EndIf}
        System::Free $3
      ${EndIf}
      StrCpy $R3 $4
    ${EndIf}
    IntOp $7 $7 + 1
  ${Loop}
  ${If} $R6 == "${LEGACY_ARGS}"
    StrCpy $8 "yes"
  ${EndIf}
leg_done:
  ${If} $6 <> 0
    System::Call 'kernel32::CloseHandle(p r6)'
  ${EndIf}
  ${If} $R0 <> 0
    System::Free $R0
  ${EndIf}
  StrCpy $R9 $8
  Pop $R6
  Pop $R5
  Pop $R4
  Pop $R3
  Pop $R2
  Pop $R1
  Pop $R0
  Pop $8
  Pop $7
  Pop $6
  Pop $5
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Pop $0
  Exch $R9
FunctionEnd

Function RemoveLegacyShortcut
  Push "$DESKTOP\LexCrew-PDF.lnk"
  Call LegacyLinkIsOurs
  Pop $0
  ${If} $0 == "yes"
    Delete "$DESKTOP\LexCrew-PDF.lnk"
  ${EndIf}
FunctionEnd

Section
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\${APP_DIR}"
  Push $INSTDIR
  Call IsProtectedDir
  Pop $0
  ${If} $0 == "yes"
    MessageBox MB_ICONSTOP "インストール先が安全でないため、ファイルは消さずに中止しました。$\r$\n$\r$\n$INSTDIR" /SD IDOK
    Abort
  ${EndIf}

  Call FindPowerShell
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "/oname=Shortcut.ps1" "${SHORTCUT}"

  DetailPrint "起動中の LexCrew PDF を確認しています..."
  Call StopLexCrew
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_ICONSTOP "LexCrew PDF を終了できません。閉じてから、もう一度インストールしてください。" /SD IDOK
    Abort
  ${EndIf}

  Call RemoveLegacyShortcut

  ${If} ${FileExists} "$INSTDIR"
    Call IsOurInstall
    Pop $1
    ${If} $1 == "yes"
      Call RemovePayload
      Pop $1
      ${If} $1 != "ok"
        MessageBox MB_ICONSTOP "インストール先のファイルを置き換えられません。LexCrew PDF を終了してから、もう一度実行してください。$\r$\n$\r$\n$INSTDIR" /SD IDOK
        Abort
      ${EndIf}
    ${Else}
      ; 自分のファイルではない runtime や src があるときは、消さずに中止する。
      ; notes.txt のように置いただけのファイルは残し、その横へ入れる。
      ${If} ${FileExists} "$INSTDIR\runtime"
      ${OrIf} ${FileExists} "$INSTDIR\src"
      ${OrIf} ${FileExists} "$INSTDIR\ui"
      ${OrIf} ${FileExists} "$INSTDIR\uninstall.exe"
        MessageBox MB_ICONSTOP "インストール先に、このアプリ以外のファイルがあります。消さずに中止しました。$\r$\n$\r$\n$INSTDIR" /SD IDOK
        Abort
      ${EndIf}
    ${EndIf}
  ${EndIf}

  DetailPrint "ファイルをコピーしています..."
  SetOutPath "$INSTDIR"
  File /r /x "LexCrew-PDF.bat" /x "停止.bat" /x "Shortcut.ps1" "${PAYLOAD}\*.*"
  ClearErrors
  FileOpen $0 "$INSTDIR\lexcrew-pdf.install" w
  ${IfNot} ${Errors}
    FileWrite $0 "LexCrew-PDF$\r$\n"
    FileClose $0
  ${EndIf}

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
  CreateDirectory "$SMPROGRAMS"
  StrCpy $LinkStrict "yes"
  Push "$SMPROGRAMS\${APP_NAME}.lnk"
  Call CreateLink
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  ; セクションに入ると $INSTDIR は uninstall.exe のフォルダに戻る。
  ; 登録先がこのアプリのときだけそちらを使い、違う場所なら exe のフォルダに戻す。
  StrCpy $UninstDir $INSTDIR
  ReadRegStr $0 HKCU "${UNINST_KEY}" "InstallLocation"
  ${If} $0 != ""
    StrCpy $INSTDIR $0
    Push $INSTDIR
    Call un.NormalizeDir
    Pop $INSTDIR
    Call un.IsOurInstall
    Pop $1
    ${If} $1 != "yes"
      StrCpy $INSTDIR $UninstDir
      Push $INSTDIR
      Call un.NormalizeDir
      Pop $INSTDIR
    ${EndIf}
  ${EndIf}
  ; 作業ディレクトリがインストール先のままだと、そのフォルダを消せない。
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"

  DetailPrint "起動中の LexCrew PDF を確認しています..."
  Call un.StopLexCrew
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_ICONSTOP "LexCrew PDF を終了できません。閉じてから、もう一度アンインストールしてください。" /SD IDOK
    Abort
  ${EndIf}

  ${If} ${FileExists} "$INSTDIR"
    Call un.IsOurInstall
    Pop $0
    ${If} $0 != "yes"
      MessageBox MB_ICONSTOP "インストール先が LexCrew PDF のフォルダだと確認できないため、ファイルは消さずに中止しました。$\r$\n$\r$\n$INSTDIR" /SD IDOK
      Abort
    ${EndIf}
    Call un.RemovePayload
    Pop $0
    ${If} $0 != "ok"
      MessageBox MB_ICONSTOP "一部のファイルが残っています。閉じてから、もう一度アンインストールしてください。$\r$\n$\r$\n$INSTDIR" /SD IDOK
      Abort
    ${EndIf}
  ${EndIf}

  Delete "$SMPROGRAMS\${APP_NAME}.lnk"
  Delete "$DESKTOP\${APP_NAME}.lnk"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ${If} ${FileExists} "$INSTDIR"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"
  ${EndIf}
SectionEnd
