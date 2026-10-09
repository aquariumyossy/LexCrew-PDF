param(
    [Parameter(Mandatory = $true)][string]$SourcePng,
    [Parameter(Mandatory = $true)][string]$DestinationIco
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

function Copy-Pixels {
    param($Bitmap)
    $rect = New-Object System.Drawing.Rectangle 0, 0, $Bitmap.Width, $Bitmap.Height
    $data = $Bitmap.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        $raw = New-Object byte[] ($data.Stride * $Bitmap.Height)
        [System.Runtime.InteropServices.Marshal]::Copy($data.Scan0, $raw, 0, $raw.Length)
        return @{ Bytes = $raw; Stride = $data.Stride; Width = $Bitmap.Width; Height = $Bitmap.Height }
    } finally {
        $Bitmap.UnlockBits($data)
    }
}

function Write-Pixels {
    param($Bitmap, $Bytes, $Stride)
    $rect = New-Object System.Drawing.Rectangle 0, 0, $Bitmap.Width, $Bitmap.Height
    $data = $Bitmap.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::WriteOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    try {
        [System.Runtime.InteropServices.Marshal]::Copy($Bytes, 0, $data.Scan0, $Stride * $Bitmap.Height)
    } finally {
        $Bitmap.UnlockBits($data)
    }
}

function Convert-CircleToVermillion {
    param($Bitmap)
    $locked = Copy-Pixels $Bitmap
    $bytes = $locked.Bytes
    $stride = $locked.Stride
    $den = [double](253 * 253 + 164 * 164 + 104 * 104)
    for ($y = 0; $y -lt $locked.Height; $y++) {
        $row = $y * $stride
        for ($x = 0; $x -lt $locked.Width; $x++) {
            $i = $row + ($x * 4)
            $b = [int]$bytes[$i]
            $g = [int]$bytes[$i + 1]
            $r = [int]$bytes[$i + 2]
            $a = [int]$bytes[$i + 3]
            if ($a -eq 0) {
                continue
            }
            $num = (($r - 2) * 253) + (($g - 91) * 164) + (($b - 151) * 104)
            $t = $num / $den
            if ($t -lt 0) { $t = 0 }
            if ($t -gt 1) { $t = 1 }
            $bytes[$i] = [byte][Math]::Round(1 + ($t * 254))
            $bytes[$i + 1] = [byte][Math]::Round(97 + ($t * 158))
            $bytes[$i + 2] = [byte][Math]::Round(235 + ($t * 20))
            $bytes[$i + 3] = [byte]$a
        }
    }
    Write-Pixels $Bitmap $bytes $stride
}

function New-SquareBitmap {
    param($Source, [int]$Size)
    $square = New-Object System.Drawing.Bitmap $Size, $Size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($square)
    try {
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.Clear([System.Drawing.Color]::Transparent)
        $graphics.DrawImage($Source, 0, 0, $Size, $Size)
    } finally {
        $graphics.Dispose()
    }
    return $square
}

function Get-Dib32 {
    param($Bitmap)
    $locked = Copy-Pixels $Bitmap
    $width = $locked.Width
    $height = $locked.Height
    $xor = New-Object byte[] ($width * $height * 4)
    $cursor = 0
    for ($y = $height - 1; $y -ge 0; $y--) {
        $row = $y * $locked.Stride
        for ($x = 0; $x -lt $width; $x++) {
            $i = $row + ($x * 4)
            $xor[$cursor] = $locked.Bytes[$i]
            $xor[$cursor + 1] = $locked.Bytes[$i + 1]
            $xor[$cursor + 2] = $locked.Bytes[$i + 2]
            $xor[$cursor + 3] = $locked.Bytes[$i + 3]
            $cursor += 4
        }
    }
    $maskRow = [int]([Math]::Floor(($width + 31) / 32) * 4)
    $mask = New-Object byte[] ($maskRow * $height)
    $stream = New-Object System.IO.MemoryStream
    $writer = New-Object System.IO.BinaryWriter $stream
    $writer.Write([int]40)
    $writer.Write([int]$width)
    $writer.Write([int]($height * 2))
    $writer.Write([uint16]1)
    $writer.Write([uint16]32)
    $writer.Write([int]0)
    $writer.Write([int]($xor.Length + $mask.Length))
    $writer.Write([int]0)
    $writer.Write([int]0)
    $writer.Write([int]0)
    $writer.Write([int]0)
    $writer.Write($xor)
    $writer.Write($mask)
    $writer.Flush()
    return $stream.ToArray()
}

function Write-Ico {
    param($Bitmaps, [string]$Path)
    $images = New-Object System.Collections.Generic.List[byte[]]
    foreach ($bitmap in $Bitmaps) {
        $images.Add((Get-Dib32 $bitmap))
    }
    $count = $images.Count
    $offset = 6 + (16 * $count)
    $stream = New-Object System.IO.MemoryStream
    $writer = New-Object System.IO.BinaryWriter $stream
    $writer.Write([uint16]0)
    $writer.Write([uint16]1)
    $writer.Write([uint16]$count)
    foreach ($image in $images) {
        $side = 0
        if ($image.Length -gt 0) {
            $side = [BitConverter]::ToInt32($image, 4)
        }
        $stored = 0
        if ($side -gt 0 -and $side -lt 256) { $stored = $side }
        $writer.Write([byte]$stored)
        $writer.Write([byte]$stored)
        $writer.Write([byte]0)
        $writer.Write([byte]0)
        $writer.Write([uint16]1)
        $writer.Write([uint16]32)
        $writer.Write([int]$image.Length)
        $writer.Write([int]$offset)
        $offset += $image.Length
    }
    foreach ($image in $images) {
        $writer.Write($image)
    }
    $writer.Flush()
    [System.IO.File]::WriteAllBytes($Path, $stream.ToArray())
}

$loaded = New-Object System.Drawing.Bitmap $SourcePng
$canvas = New-Object System.Drawing.Bitmap $loaded.Width, $loaded.Height, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$graphics = [System.Drawing.Graphics]::FromImage($canvas)
try {
    $graphics.DrawImage($loaded, 0, 0, $loaded.Width, $loaded.Height)
} finally {
    $graphics.Dispose()
    $loaded.Dispose()
}
Convert-CircleToVermillion $canvas

$circle = $canvas.GetPixel(256, 40)
$center = $canvas.GetPixel(256, 256)
$corner = $canvas.GetPixel(0, 0)
if ($circle.A -ne 255 -or $circle.R -ne 235 -or $circle.G -ne 97 -or $circle.B -ne 1) {
    throw "円の色が朱色ではありません。"
}
if ($center.A -ne 255 -or $center.R -ne 255 -or $center.G -ne 255 -or $center.B -ne 255) {
    throw "中央の人物が白ではありません。"
}
if ($corner.A -ne 0) {
    throw "四隅が透明ではありません。"
}

$sizes = @(16, 32, 48, 256)
$scaled = @()
foreach ($size in $sizes) {
    $scaled += New-SquareBitmap $canvas $size
}
$canvas.Dispose()
Write-Ico -Bitmaps $scaled -Path $DestinationIco
foreach ($bitmap in $scaled) {
    $bitmap.Dispose()
}

$icon = New-Object System.Drawing.Icon $DestinationIco
try {
    if ($icon.Width -le 0 -or $icon.Height -le 0) {
        throw "アイコンを開けません。"
    }
    $preview = $icon.ToBitmap()
    $preview.Dispose()
} finally {
    $icon.Dispose()
}
