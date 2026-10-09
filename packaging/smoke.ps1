param(
    [Parameter(Mandatory = $true)][string]$PackageRoot,
    [Parameter(Mandatory = $true)][string]$ZipPath
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if (-not ("LexCrew.Dpi" -as [type])) {
    Add-Type -TypeDefinition @"
using System.Runtime.InteropServices;
namespace LexCrew {
    public static class Dpi {
        [DllImport("user32.dll")]
        public static extern bool SetProcessDPIAware();
    }
}
"@
}
[void][LexCrew.Dpi]::SetProcessDPIAware()

if (-not ("LexCrew.SmokeWin" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
namespace LexCrew {
    public class SmokeWin {
        public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
        public static int Count;
        public static IntPtr First;
        [DllImport("user32.dll")]
        public static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
        [DllImport("user32.dll")]
        public static extern bool IsWindowVisible(IntPtr hWnd);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
        [DllImport("user32.dll")]
        public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern IntPtr FindWindow(string className, string windowName);
        public struct RECT {
            public int Left;
            public int Top;
            public int Right;
            public int Bottom;
        }
        public static bool CountLex(IntPtr hWnd, IntPtr lParam) {
            if (!IsWindowVisible(hWnd)) {
                return true;
            }
            var text = new StringBuilder(512);
            GetWindowText(hWnd, text, text.Capacity);
            if (text.ToString() == "LexCrew-PDF") {
                Count++;
            }
            return true;
        }
        public static bool FindFirst(IntPtr hWnd, IntPtr lParam) {
            if (First != IntPtr.Zero || !IsWindowVisible(hWnd)) {
                return true;
            }
            var text = new StringBuilder(512);
            GetWindowText(hWnd, text, text.Capacity);
            if (text.ToString() == "LexCrew-PDF") {
                First = hWnd;
            }
            return true;
        }
    }
}
"@
}

function Get-LexCrewWindowCount {
    [LexCrew.SmokeWin]::Count = 0
    $callback = [System.Delegate]::CreateDelegate([LexCrew.SmokeWin+EnumProc], [LexCrew.SmokeWin], "CountLex")
    [void][LexCrew.SmokeWin]::EnumWindows($callback, [IntPtr]::Zero)
    return [LexCrew.SmokeWin]::Count
}

function Get-Stamp {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return "missing"
    }
    return (Get-Item -LiteralPath $Path).LastWriteTimeUtc.Ticks.ToString()
}

$shellApp = New-Object -ComObject Shell.Application
$downloads = $shellApp.NameSpace("shell:Downloads").Self.Path
$layout = Join-Path $downloads "LexCrew-PDF-Downloads\layout.json"
$desktop = (New-Object -ComObject WScript.Shell).SpecialFolders("Desktop")
$desktopLink = Join-Path $desktop "LexCrew-PDF.lnk"
$beforeLayout = Get-Stamp $layout
$beforeDesktop = Get-Stamp $desktopLink

if ((Get-LexCrewWindowCount) -gt 0) {
    throw "すでに LexCrew-PDF が開いているので、確認を中止しました。"
}

$python = Join-Path $PackageRoot "runtime\python.exe"
$outside = Join-Path $env:TEMP ("lexcrew-cwd-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $outside | Out-Null
$check = Join-Path $outside "check_import.py"
[System.IO.File]::WriteAllText($check, @"
import sys
bad = [p for p in sys.path if "Roaming\\Python" in p or "Roaming/Python" in p]
if bad:
    raise SystemExit("user site is visible")
import fitz, webview, lexcrew_pdf
print("imports-ok")
"@)
$import = New-Object System.Diagnostics.ProcessStartInfo
$import.FileName = $python
$import.Arguments = "`"$check`""
$import.WorkingDirectory = $outside
$import.UseShellExecute = $false
$import.RedirectStandardOutput = $true
$import.RedirectStandardError = $true
if ($import.EnvironmentVariables.ContainsKey("PYTHONNOUSERSITE")) {
    [void]$import.EnvironmentVariables.Remove("PYTHONNOUSERSITE")
}
$importProc = [System.Diagnostics.Process]::Start($import)
$importErr = $importProc.StandardError.ReadToEndAsync()
$importOut = $importProc.StandardOutput.ReadToEnd()
$importProc.WaitForExit()
if ($importProc.ExitCode -ne 0 -or $importOut -notmatch "imports-ok") {
    throw "パッケージの外から import できません。`n$importOut`n$($importErr.Result)"
}

$folder = Join-Path $env:TEMP ("lexcrew-folder-" + [guid]::NewGuid().ToString("n"))
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$sync = [hashtable]::Synchronized(@{ lines = (New-Object System.Collections.ArrayList) })
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $python
$psi.Arguments = "-m lexcrew_pdf"
$psi.WorkingDirectory = $outside
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.EnvironmentVariables["LEXCREW_FOLDER"] = $folder
if ($psi.EnvironmentVariables.ContainsKey("PYTHONNOUSERSITE")) {
    [void]$psi.EnvironmentVariables.Remove("PYTHONNOUSERSITE")
}
$proc = New-Object System.Diagnostics.Process
$proc.StartInfo = $psi
$proc.EnableRaisingEvents = $true
try {
    Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived -MessageData $sync -Action {
        if ($EventArgs.Data) {
            [void]$Event.MessageData.lines.Add($EventArgs.Data)
        }
    } | Out-Null
    [void]$proc.Start()
    $proc.BeginOutputReadLine()
    Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived -Action { } | Out-Null
    $proc.BeginErrorReadLine()
    $deadline = (Get-Date).AddSeconds(90)
    $opened = $false
    while ((Get-Date) -lt $deadline) {
        $text = @($sync.lines) -join "`n"
        if ($text -match "cards-ready" -and (Get-LexCrewWindowCount) -ge 1) {
            $opened = $true
            break
        }
        if ($proc.HasExited) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $opened) {
        throw "窓が開きません。`n$(@($sync.lines) -join "`n")"
    }

    $secondInfo = New-Object System.Diagnostics.ProcessStartInfo
    $secondInfo.FileName = $python
    $secondInfo.Arguments = "-m lexcrew_pdf"
    $secondInfo.WorkingDirectory = $outside
    $secondInfo.UseShellExecute = $false
    $secondInfo.RedirectStandardOutput = $true
    $secondInfo.RedirectStandardError = $true
    $secondInfo.EnvironmentVariables["LEXCREW_FOLDER"] = $folder
    if ($secondInfo.EnvironmentVariables.ContainsKey("PYTHONNOUSERSITE")) {
        [void]$secondInfo.EnvironmentVariables.Remove("PYTHONNOUSERSITE")
    }
    $second = [System.Diagnostics.Process]::Start($secondInfo)
    $secondErr = $second.StandardError.ReadToEndAsync()
    $second.StandardOutput.ReadToEnd() | Out-Null
    if (-not $second.WaitForExit(20000)) {
        taskkill.exe /PID $second.Id /T /F | Out-Null
        throw "2つ目の起動が終わりません。"
    }
    if ($second.ExitCode -ne 0) {
        throw "2つ目の起動が失敗しました。`n$($secondErr.Result)"
    }
    Start-Sleep -Milliseconds 500
    $windows = Get-LexCrewWindowCount
    if ($windows -ne 1) {
        throw "窓の数が $windows です。"
    }

    try {
        Add-Type -AssemblyName System.Drawing
        Add-Type -AssemblyName System.Windows.Forms
        [LexCrew.SmokeWin]::First = [IntPtr]::Zero
        $find = [System.Delegate]::CreateDelegate([LexCrew.SmokeWin+EnumProc], [LexCrew.SmokeWin], "FindFirst")
        [void][LexCrew.SmokeWin]::EnumWindows($find, [IntPtr]::Zero)
        if ([LexCrew.SmokeWin]::First -ne [IntPtr]::Zero) {
            $rect = New-Object LexCrew.SmokeWin+RECT
            [void][LexCrew.SmokeWin]::GetWindowRect([LexCrew.SmokeWin]::First, [ref]$rect)
            $width = $rect.Right - $rect.Left
            $height = $rect.Bottom - $rect.Top
            if ($width -gt 0 -and $height -gt 0) {
                $shot = New-Object System.Drawing.Bitmap $width, $height
                $graphics = [System.Drawing.Graphics]::FromImage($shot)
                $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $shot.Size)
                $graphics.Dispose()
                $shot.Save((Join-Path $PSScriptRoot "cache\smoke-window.png"), [System.Drawing.Imaging.ImageFormat]::Png)
                $shot.Dispose()
            }
        }
        $tray = [LexCrew.SmokeWin]::FindWindow("Shell_TrayWnd", $null)
        if ($tray -ne [IntPtr]::Zero) {
            $trayRect = New-Object LexCrew.SmokeWin+RECT
            [void][LexCrew.SmokeWin]::GetWindowRect($tray, [ref]$trayRect)
            $trayWidth = $trayRect.Right - $trayRect.Left
            $trayHeight = $trayRect.Bottom - $trayRect.Top
            if ($trayWidth -gt 0 -and $trayHeight -gt 0) {
                $bar = New-Object System.Drawing.Bitmap $trayWidth, $trayHeight
                $barGraphics = [System.Drawing.Graphics]::FromImage($bar)
                $barGraphics.CopyFromScreen($trayRect.Left, $trayRect.Top, 0, 0, $bar.Size)
                $barGraphics.Dispose()
                $bar.Save((Join-Path $PSScriptRoot "cache\smoke-taskbar.png"), [System.Drawing.Imaging.ImageFormat]::Png)
                $bar.Dispose()
            }
        }
    } catch {
        [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot "cache\smoke-shot-error.txt"), "$_")
    }
} finally {
    if ($proc -and -not $proc.HasExited) {
        taskkill.exe /PID $proc.Id /T /F | Out-Null
        [void]$proc.WaitForExit(10000)
    }
    Get-EventSubscriber | Unregister-Event -ErrorAction SilentlyContinue
}

if ((Get-Stamp $layout) -ne $beforeLayout) {
    throw "本物の layout.json が変わりました。"
}
if ((Get-Stamp $desktopLink) -ne $beforeDesktop) {
    throw "本物のデスクトップのショートカットが変わりました。"
}

$again = Join-Path $outside "LexCrew-PDF.ico"
& (Join-Path $PSScriptRoot "New-LexCrewIcon.ps1") -SourcePng (Join-Path $PSScriptRoot "h-crew.png") -DestinationIco $again
$shipped = Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PackageRoot "LexCrew-PDF.ico")
$rebuilt = Get-FileHash -Algorithm SHA256 -LiteralPath $again
if ($shipped.Hash -ne $rebuilt.Hash) {
    throw "配布した ico が元画像から作ったものと一致しません。"
}

$link = Join-Path $outside "LexCrew-PDF.lnk"
& (Join-Path $PackageRoot "Shortcut.ps1") -AppRoot $PackageRoot -LinkPath $link
$linkShell = New-Object -ComObject WScript.Shell
$loadedLink = $linkShell.CreateShortcut($link)
$expectedPythonw = (Resolve-Path -LiteralPath (Join-Path $PackageRoot "runtime\pythonw.exe")).Path
$actualTarget = [string]$loadedLink.TargetPath
if ($actualTarget -ne $expectedPythonw) {
    throw "ショートカットのリンク先が pythonw ではありません。 actual=[$actualTarget] expected=[$expectedPythonw]"
}
if ([string]$loadedLink.Arguments -ne "-m lexcrew_pdf") {
    throw "ショートカットの引数が違います。"
}
if ([string]$loadedLink.IconLocation -ne ((Join-Path $PackageRoot "LexCrew-PDF.ico") + ",0")) {
    throw "ショートカットのアイコンが違います。"
}
$appId = & (Join-Path $PackageRoot "Shortcut.ps1") -AppRoot $PackageRoot -LinkPath $link -Read
if ($appId.Trim() -ne "LexCrew.PDF") {
    throw "AppUserModelID が LexCrew.PDF ではありません。"
}

$extract = Join-Path $outside "unzipped"
New-Item -ItemType Directory -Force -Path $extract | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $extract)
$usage = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter "使い方.txt")
$stop = @(Get-ChildItem -LiteralPath $extract -Recurse -Filter "停止.bat")
if ($usage.Count -ne 1 -or $stop.Count -ne 1) {
    throw "日本語のファイル名が残っていません。"
}

Remove-Item -LiteralPath $outside -Recurse -Force
Remove-Item -LiteralPath $folder -Recurse -Force
Write-Output "smoke-ok"
