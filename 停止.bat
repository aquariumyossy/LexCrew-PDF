@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "COUNT=0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$py='%PY%'; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*lexcrew_pdf*' -and $_.CommandLine -like ('*' + $py + '*') } | ForEach-Object { $_.ProcessId }"`) do (
  taskkill /PID %%I /T /F >nul 2>&1
  set /a COUNT+=1
)

if "!COUNT!"=="0" (
  echo ‹N“®‚µ‚Ä‚¢‚Ü‚¹‚ñB
) else (
  echo ’â~‚µ‚Ü‚µ‚½B
)
pause
endlocal
