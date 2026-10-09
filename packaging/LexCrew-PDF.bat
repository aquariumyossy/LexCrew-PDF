@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Shortcut.ps1" -AppRoot "%~dp0."
if errorlevel 1 (
  echo ショートカットを置けませんでした。
  pause
  exit /b 1
)
start "" "%~dp0runtime\pythonw.exe" -m lexcrew_pdf
