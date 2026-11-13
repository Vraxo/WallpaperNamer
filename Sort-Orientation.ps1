<#
.SYNOPSIS
    Moves images into Portraits/ and Landscape/ subfolders based on orientation.

    Requires Python with Pillow (already a WallpaperNamer dependency) to read
    image dimensions. Falls back to reporting files it can't inspect.

.PARAMETER ImageDir
    Root folder containing your wallpapers. Defaults to E:\Images\Wallpapers.

.PARAMETER SquareFolder
    Name of the folder for square images (width == height).
    Set to $null or empty to leave square images where they are.

.PARAMETER WhatIf
    Preview moves without actually moving anything.
#>
param(
    [string]$ImageDir = "E:\Images\Wallpapers",
    [string]$SquareFolder = "Square",
    [switch]$WhatIf
)

if (-not (Test-Path $ImageDir)) {
    Write-Error "Directory not found: $ImageDir"
    exit 1
}

# Use Python + Pillow to get image dimensions reliably.
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Error "Could not find Python (py / python / python3). Install it or run with Pillow available."
    exit 1
}

$getSizeScript = @'
import sys, json
from pathlib import Path
from PIL import Image
for p in sys.argv[1:]:
    try:
        with Image.open(p) as im:
            w, h = im.size
        print(json.dumps({'path': p, 'w': w, 'h': h, 'ok': True}))
    except Exception as e:
        print(json.dumps({'path': p, 'ok': False, 'error': str(e)}))
'@

$imageExts = @(".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff")

$files = Get-ChildItem -Path $ImageDir -Recurse -File |
    Where-Object { $imageExts -contains $_.Extension.ToLower() } |
    Where-Object { $_.Directory.Name -notin @("Portraits", "Landscape", $SquareFolder) }

# Batch all paths into one Python call for speed.
$paths = $files | ForEach-Object { $_.FullName }
if ($paths.Count -eq 0) {
    Write-Host "No images found."
    exit 0
}

$pythonPath = $python.Source
$output = & $pythonPath -c $getSizeScript $paths

$results = foreach ($line in $output) {
    if ($line) { $line | ConvertFrom-Json }
}

foreach ($file in $files) {
    $info = $results | Where-Object { $_.path -eq $file.FullName }
    if (-not $info -or -not $info.ok) {
        Write-Host "[SKIP]  $($file.Name)  (could not read dimensions)" -ForegroundColor Yellow
        continue
    }

    $w = [int]$info.w
    $h = [int]$info.h

    if ($w -gt $h) {
        $folder = "Landscape"
    }
    elseif ($h -gt $w) {
        $folder = "Portraits"
    }
    else {
        $folder = $SquareFolder
    }

    if (-not $folder) {
        Write-Host "[SKIP]  $($file.Name)  (square, no square folder configured)" -ForegroundColor Gray
        continue
    }

    $destDir = Join-Path $file.DirectoryName $folder
    $dest    = Join-Path $destDir $file.Name
    $i       = 1
    while (Test-Path $dest) {
        $dest = Join-Path $destDir "$($file.BaseName)_$i$($file.Extension)"
        $i++
    }

    if ($WhatIf) {
        Write-Host "[WOULD] $($file.Name) -> $folder\$(Split-Path $dest -Leaf)" -ForegroundColor Cyan
    }
    else {
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        try {
            Move-Item -Path $file.FullName -Destination $dest -ErrorAction Stop
            Write-Host "[OK]    $($file.Name) -> $folder\" -ForegroundColor Green
        }
        catch {
            Write-Host "[ERR]   $($file.Name): $($_.Exception.Message)" -ForegroundColor Red
        }
    }
}
