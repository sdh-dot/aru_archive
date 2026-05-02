<#
.SYNOPSIS
    Builds Aru Archive Windows onedir ZIP using PyInstaller.

.DESCRIPTION
    Wraps PyInstaller invocation with version validation, ZIP packaging,
    and SHA256 hashing. Outputs release/AruArchive-v<Version>-win-x64.zip
    plus matching .sha256 file. Does not touch user DB or runtime data.

.PARAMETER Version
    Required. Semver string matching core/version.py APP_VERSION.

.PARAMETER Clean
    Optional. Removes build/aru_archive, dist/, release/ before building.

.PARAMETER SkipChecks
    Optional. Skips ExifTool bundle check and version consistency check.

.EXAMPLE
    .\scripts\build_windows.ps1 -Version 0.6.3 -Clean

.NOTES
    Run from repo root. Requires Python venv with PyInstaller available on PATH.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$Version,
    [switch]$Clean,
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'

# Repo root resolution (parent of scripts/)
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "[build] Repo root: $Root"

# 1. Pre-build checks
if (-not $SkipChecks) {
    Write-Host "[build] Running ExifTool bundle check..."
    & python "$Root/build/check_exiftool_bundle.py"
    if ($LASTEXITCODE -ne 0) { throw "ExifTool bundle check failed" }

    Write-Host "[build] Verifying core/version.py APP_VERSION..."
    Push-Location $Root
    $av = (& python -c "from core.version import APP_VERSION; print(APP_VERSION)") -join ""
    Pop-Location
    if ($av.Trim() -ne $Version) {
        throw "core/version.py APP_VERSION='$av' does not match requested '$Version'. Update core/version.py first."
    }
}

# 2. Clean
if ($Clean) {
    Write-Host "[build] Cleaning build/aru_archive, dist/, release/..."
    Remove-Item -Recurse -Force "$Root/build/aru_archive" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$Root/dist" -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force "$Root/release" -ErrorAction SilentlyContinue
}

# 3. PyInstaller
Write-Host "[build] Running PyInstaller..."
Push-Location $Root
try {
    & pyinstaller "build/aru_archive.spec" --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
} finally {
    Pop-Location
}

$DistDir = "$Root/dist/aru_archive"
if (-not (Test-Path $DistDir)) { throw "Expected dist output not found: $DistDir" }

# 4. Release directory + bundle name
$BundleName = "AruArchive-v$Version-win-x64"
$ReleaseDir = "$Root/release"
$BundleDir = "$Root/dist/$BundleName"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

if (Test-Path $BundleDir) {
    Remove-Item -Recurse -Force $BundleDir
}
Copy-Item -Recurse -Force $DistDir $BundleDir

# 5. ZIP
$ZipPath = "$ReleaseDir/$BundleName.zip"
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Write-Host "[build] Creating ZIP: $ZipPath"
Compress-Archive -Path "$BundleDir/*" -DestinationPath $ZipPath -CompressionLevel Optimal

# 6. SHA256
$Hash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash
$HashFile = "$ReleaseDir/$BundleName.zip.sha256"
"$Hash  $BundleName.zip" | Out-File -Encoding ascii $HashFile

Write-Host ""
Write-Host "[build] DONE"
Write-Host "  ZIP:    $ZipPath"
Write-Host "  SHA256: $Hash"
Write-Host "  Hash file: $HashFile"
