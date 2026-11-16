#requires -Version 7.0
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing.Common
$assetDir = Join-Path $PSScriptRoot '../Desktop/assets'
[IO.Directory]::CreateDirectory($assetDir) | Out-Null

function New-IconFrame([int]$Size) {
    $scale = 3
    $source = [Drawing.Bitmap]::new($Size * $scale, $Size * $scale)
    $frame = [Drawing.Bitmap]::new($Size, $Size)
    $canvas = [Drawing.Graphics]::FromImage($source)
    $path = [Drawing.Drawing2D.GraphicsPath]::new()
    $navy = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(22, 49, 79))
    $paper = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(247, 251, 255))
    $fold = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(176, 208, 231))
    $wave = [Drawing.Pen]::new([Drawing.Color]::FromArgb(0, 121, 136), 11)
    $resize = [Drawing.Graphics]::FromImage($frame)
    try {
        $canvas.SmoothingMode = 'AntiAlias'
        $ratio = [single]($Size * $scale / 128)
        $canvas.ScaleTransform($ratio, $ratio)
        $path.AddArc(5, 5, 47, 47, 180, 90)
        $path.AddArc(76, 5, 47, 47, 270, 90)
        $path.AddArc(76, 76, 47, 47, 0, 90)
        $path.AddArc(5, 76, 47, 47, 90, 90)
        $path.CloseFigure()
        $canvas.FillPath($navy, $path)
        $canvas.FillPolygon($paper, [Drawing.Point[]]@(
            [Drawing.Point]::new(30, 22), [Drawing.Point]::new(75, 22), [Drawing.Point]::new(98, 45),
            [Drawing.Point]::new(98, 104), [Drawing.Point]::new(30, 104)))
        $canvas.FillPolygon($fold, [Drawing.Point[]]@(
            [Drawing.Point]::new(75, 22), [Drawing.Point]::new(98, 45), [Drawing.Point]::new(75, 45)))
        $wave.StartCap = 'Round'
        $wave.EndCap = 'Round'
        $wave.LineJoin = 'Round'
        $canvas.DrawLines($wave, [Drawing.Point[]]@(
            [Drawing.Point]::new(41, 69), [Drawing.Point]::new(49, 69), [Drawing.Point]::new(57, 55),
            [Drawing.Point]::new(68, 85), [Drawing.Point]::new(77, 63), [Drawing.Point]::new(87, 69)))
        $resize.InterpolationMode = 'HighQualityBicubic'
        $resize.PixelOffsetMode = 'HighQuality'
        $resize.DrawImage($source, 0, 0, $Size, $Size)
        return $frame
    } finally {
        $resize.Dispose()
        $wave.Dispose()
        $fold.Dispose()
        $paper.Dispose()
        $navy.Dispose()
        $path.Dispose()
        $canvas.Dispose()
        $source.Dispose()
    }
}

$sizes = @(16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
$frames = @(
    foreach ($size in $sizes) {
        $frame = New-IconFrame $size
        $buffer = [IO.MemoryStream]::new()
        $entry = [IO.BinaryWriter]::new($buffer)
        try {
            if ($size -eq 256) {
                $frame.Save($buffer, [Drawing.Imaging.ImageFormat]::Png)
                $frame.Save((Join-Path $assetDir 'ReadingRepair.png'), [Drawing.Imaging.ImageFormat]::Png)
            } else {
                # 小サイズは古いシェルにも対応する32 bit DIB。高さにはANDマスク分を含む。
                $entry.Write([int]40)
                $entry.Write([int]$size)
                $entry.Write([int]($size * 2))
                $entry.Write([uint16]1)
                $entry.Write([uint16]32)
                $entry.Write([byte[]]::new(24))
                for ($y = $size - 1; $y -ge 0; $y--) {
                    for ($x = 0; $x -lt $size; $x++) {
                        $entry.Write($frame.GetPixel($x, $y).ToArgb())
                    }
                }
                $maskStride = 4 * [int][Math]::Ceiling($size / 32.0)
                for ($y = $size - 1; $y -ge 0; $y--) {
                    $mask = [byte[]]::new($maskStride)
                    for ($x = 0; $x -lt $size; $x++) {
                        if ($frame.GetPixel($x, $y).A -lt 128) {
                            $i = $x -shr 3
                            $mask[$i] = $mask[$i] -bor (128 -shr ($x % 8))
                        }
                    }
                    $entry.Write($mask)
                }
            }
            [pscustomobject]@{ Size = $size; Data = $buffer.ToArray() }
        } finally {
            $entry.Dispose()
            $frame.Dispose()
        }
    }
)

$file = [IO.File]::Create((Join-Path $assetDir 'ReadingRepair.ico'))
$ico = [IO.BinaryWriter]::new($file)
try {
    $ico.Write([uint16]0)
    $ico.Write([uint16]1)
    $ico.Write([uint16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($frame in $frames) {
        $sizeByte = [byte]($frame.Size % 256)
        $ico.Write([byte[]]@($sizeByte, $sizeByte, 0, 0))
        $ico.Write([uint16]1)
        $ico.Write([uint16]32)
        $ico.Write([uint32]$frame.Data.Length)
        $ico.Write([uint32]$offset)
        $offset += $frame.Data.Length
    }
    foreach ($frame in $frames) { $ico.Write([byte[]]$frame.Data) }
} finally {
    $ico.Dispose()
}
