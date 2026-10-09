@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "ROOT=%~dp0runtime"
set "COUNT=0"
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "$root='%ROOT%'; $prefix=$root.TrimEnd('\') + '\'; Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { $_.ProcessId }"`) do (
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
