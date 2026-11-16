# Builds "dist\Media Downloader.exe" (single file).
# Run from this folder in PowerShell:   .\build_windows.ps1
# Needs: Python 3.10+ from python.org (tick "Add to PATH" when installing).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Creating virtual environment"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".\.venv\Scripts\Activate.ps1"

Write-Host "==> Installing dependencies"
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt pyinstaller -q

# ---- ffmpeg ----
New-Item -ItemType Directory -Force -Path vendor | Out-Null
if (-not (Test-Path "vendor\ffmpeg.exe")) {
    Write-Host "==> Downloading ffmpeg (BtbN static build)"
    $zip = "vendor\ffmpeg.zip"
    Invoke-WebRequest -Uri "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip" -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath "vendor\ffmpeg_tmp" -Force
    $exe = Get-ChildItem -Path "vendor\ffmpeg_tmp" -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    Copy-Item $exe.FullName "vendor\ffmpeg.exe"
    Remove-Item -Recurse -Force "vendor\ffmpeg_tmp", $zip
}

Write-Host "==> Building with PyInstaller"
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
pyinstaller build.spec --noconfirm --clean

Write-Host ""
Write-Host "Done. Give your friends:  dist\Media Downloader.exe"
