<#
.SYNOPSIS
    Moves images into Portraits/ and Landscape/ subfolders based on orientation.

    Requires Python with Pillow (already a WallpaperNamer dependency) to read
    image dimensions.

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

# Find Python
$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) { $python = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Error "Could not find Python (py / python / python3). Install it or run with Pillow available."
    exit 1
}

$getSizeScript = @'
import sys, json
from PIL import Image
with open(sys.argv[1]) as f:
    for line in f:
        p = line.strip()
        if not p:
            continue
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

$paths = $files | ForEach-Object { $_.FullName }
if ($paths.Count -eq 0) {
    Write-Host "No images found."
    exit 0
}

# Write paths to a temp file to avoid command-line length limits
$tempPaths = [System.IO.Path]::GetTempFileName()
$paths | Out-File -FilePath $tempPaths -Encoding utf8

# Capture Python stdout to a temp file to avoid PowerShell encoding errors
$tempOut = [System.IO.Path]::GetTempFileName()
try {
    Start-Process -FilePath $python.Source -ArgumentList "-c", $getSizeScript, $tempPaths `
        -RedirectStandardOutput $tempOut -Wait -NoNewWindow
    $output = Get-Content -Path $tempOut
} finally {
    Remove-Item -Path $tempPaths -ErrorAction SilentlyContinue
    Remove-Item -Path $tempOut -ErrorAction SilentlyContinue
}

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
