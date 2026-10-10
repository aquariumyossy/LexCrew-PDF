$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:PYTHONNOUSERSITE = "1"

$repo = Split-Path -Parent $PSScriptRoot
$cache = Join-Path $PSScriptRoot "cache"
$embedName = "python-3.13.14-embed-amd64.zip"
$embedUrl = "https://www.python.org/ftp/python/3.13.14/$embedName"
$embedHash = "90B4E5B9898B72D744650524BFF92377C367F44BD5FBD09E3148656C080AD907"
$dest = Join-Path $repo "dist\LexCrew-PDF"
$zipPath = Join-Path $repo "dist\LexCrew-PDF-1.2.0-win64.zip"

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
}

$pyproject = Get-Content -LiteralPath (Join-Path $repo "pyproject.toml") -Raw -Encoding UTF8
if ($pyproject -notmatch 'version = "1.2.0"') {
    throw "版が 1.2.0 ではありません。"
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null
$embed = Join-Path $cache $embedName
if (-not (Test-Path -LiteralPath $embed) -or (Get-Sha256 $embed) -ne $embedHash) {
    Invoke-WebRequest -Uri $embedUrl -OutFile $embed
}
if ((Get-Sha256 $embed) -ne $embedHash) {
    throw "埋め込み Python のハッシュが一致しません。"
}

$venv = Join-Path $repo ".venv\Scripts\python.exe"
$versions = & $venv -c "import importlib.metadata as m; print(m.version('pymupdf')); print(m.version('pywebview'))"
if ($LASTEXITCODE -ne 0) {
    throw "依存の版を読めません。"
}
$pymupdf = $versions[0].Trim()
$pywebview = $versions[1].Trim()

if (Test-Path -LiteralPath $dest) {
    Remove-Item -LiteralPath $dest -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $repo "dist") | Out-Null
$runtime = Join-Path $dest "runtime"
Expand-Archive -LiteralPath $embed -DestinationPath $runtime -Force

$pth = Get-ChildItem -LiteralPath $runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) {
    throw "python._pth がありません。"
}
$kept = New-Object System.Collections.Generic.List[string]
foreach ($line in @(Get-Content -LiteralPath $pth.FullName)) {
    if ($line -match '^\s*#\s*import site\s*$') { continue }
    if ($line -eq "Lib\site-packages" -or $line -eq "..\src" -or $line -match '^\s*import site\s*$') { continue }
    $kept.Add($line)
}
$kept.Add("Lib\site-packages")
$kept.Add("..\src")
$kept.Add("import site")
$ascii = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($pth.FullName, $kept.ToArray(), $ascii)

$python = Join-Path $runtime "python.exe"
$getPip = Join-Path $cache "get-pip.py"
if (-not (Test-Path -LiteralPath $getPip)) {
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip
}
& $python $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) {
    throw "pip を入れられません。"
}
& $python -m pip install --disable-pip-version-check setuptools wheel
if ($LASTEXITCODE -ne 0) {
    throw "ビルド用の部品を入れられません。"
}
& $python -m pip install --disable-pip-version-check --no-build-isolation "pymupdf==$pymupdf" "pywebview==$pywebview"
if ($LASTEXITCODE -ne 0) {
    throw "依存を入れられません。"
}
$siteCustom = @"
import site
import sys

def _drop_user_site():
    # ._pth の import site は、isolated でもユーザー site を足す。
    # ショートカットは pythonw を直接起動するので、環境変数は渡せない。
    try:
        user = site.getusersitepackages()
    except Exception:
        return
    if not isinstance(user, str) or not user:
        return
    prefix = user.rstrip("\\/").lower()
    sys.path[:] = [item for item in sys.path if not str(item).lower().startswith(prefix)]

_drop_user_site()
"@
$siteDir = Join-Path $runtime "Lib\site-packages"
New-Item -ItemType Directory -Force -Path $siteDir | Out-Null
[System.IO.File]::WriteAllText((Join-Path $siteDir "sitecustomize.py"), $siteCustom, $ascii)

$package = Join-Path $dest "src\lexcrew_pdf"
New-Item -ItemType Directory -Force -Path $package | Out-Null
Copy-Item -Path (Join-Path $repo "src\lexcrew_pdf\*.py") -Destination $package
New-Item -ItemType Directory -Force -Path (Join-Path $dest "ui") | Out-Null
Copy-Item -Path (Join-Path $repo "ui\*") -Destination (Join-Path $dest "ui")

& (Join-Path $PSScriptRoot "New-LexCrewIcon.ps1") -SourcePng (Join-Path $PSScriptRoot "h-crew.png") -DestinationIco (Join-Path $dest "LexCrew-PDF.ico")
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "LexCrew-PDF.bat") -Destination $dest
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "停止.bat") -Destination $dest
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Shortcut.ps1") -Destination $dest
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "使い方.txt") -Destination $dest
Copy-Item -LiteralPath (Join-Path $repo "LICENSE") -Destination (Join-Path $dest "LICENSE")

$license = @"
LexCrew-PDF
Copyright (C) 2026 吉田秀平

このプログラムは自由ソフトウェアです。GNU Affero General Public License バージョン 3 の条件で再配布、改変できます。
ライセンスの全文は、このフォルダの LICENSE です。
https://www.gnu.org/licenses/agpl-3.0.html

保証はありません。商品性や特定目的への適合性についても保証しません。詳細は LICENSE を見てください。

このフォルダの PyMuPDF $pymupdf は、GNU AGPL 3.0 の版です。改変していません。Artifex の商用ライセンスは含みません。
ソースは https://github.com/pymupdf/PyMuPDF の $pymupdf です。
原文は runtime\Lib\site-packages の中の PyMuPDF の dist-info にあります。

pywebview $pywebview は BSD 3-Clause License です。
Copyright (c) 2014-2017, Roman Sirokov
原文は runtime\Lib\site-packages の中の pywebview の dist-info にあります。
ソースで再配布するときは、著作権表示、条件、免責を残します。バイナリで再配布するときは、同じ表記を同梱物に残します。著作権者の名前を、書面の許可なく宣伝に使いません。

LexCrew-PDF のソースは、このフォルダの src と ui にあります。
"@
$utf8 = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText((Join-Path $dest "ライセンス.txt"), $license.Trim() + "`r`n", $utf8)

Add-Type -AssemblyName System.IO.Compression.FileSystem
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $dest,
    $zipPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
)

& (Join-Path $PSScriptRoot "smoke.ps1") -PackageRoot $dest -ZipPath $zipPath
Write-Output $zipPath
