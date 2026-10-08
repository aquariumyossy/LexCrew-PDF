@echo off
cd /d "%~dp0"
title LexCrew-PDF（開発）

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo 仮想環境が見つかりません。
  echo %PY%
  pause
  exit /b 1
)

set "RUNNING="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$py='%PY%'; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*lexcrew_pdf*' -and $_.CommandLine -like ('*' + $py + '*') } | ForEach-Object { $_.ProcessId }"`) do set "RUNNING=1"
if defined RUNNING (
  echo すでに起動しています。止めるときは 停止.bat を使ってください。
  pause
  exit /b 0
)

"%PY%" -u -m lexcrew_pdf
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo.
  echo 終了コード %CODE%
  pause
  exit /b %CODE%
)
