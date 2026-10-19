param(
    [Parameter(Mandatory = $true)][string]$AppRoot
)

$ErrorActionPreference = "Stop"

$runtime = Join-Path $AppRoot "runtime"
if (-not (Test-Path -LiteralPath $runtime)) {
    exit 0
}
$prefix = $runtime.TrimEnd("\") + "\"

function Get-AppProcessId {
    @(Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
        $_.ExecutablePath -and
        $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
    } | Select-Object -ExpandProperty ProcessId)
}

foreach ($id in @(Get-AppProcessId)) {
    & taskkill.exe /PID $id /T /F | Out-Null
}

$deadline = (Get-Date).AddSeconds(15)
while ((Get-Date) -lt $deadline) {
    if (-not @(Get-AppProcessId)) {
        exit 0
    }
    Start-Sleep -Milliseconds 200
}

Write-Error "LexCrew PDF is still running."
exit 1
