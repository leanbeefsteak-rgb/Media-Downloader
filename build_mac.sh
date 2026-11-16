#!/usr/bin/env bash
# Builds "dist/Media Downloader.app" and zips it for sharing.
# Run from this folder in Terminal:   bash build_mac.sh
# Needs: Python 3.10+ (python.org installer or `brew install python`).
#
# Note: a build made on an Apple Silicon Mac runs on Apple Silicon Macs; a build
# made on an Intel Mac runs on both (via Rosetta). Build on the kind of Mac your
# friends have, or on an Intel Mac if you have one.

set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}

echo "==> Creating virtual environment"
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies"
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt pyinstaller -q

# ---- ffmpeg ----
mkdir -p vendor
if [ ! -x vendor/ffmpeg ]; then
    ARCH=$(uname -m)   # arm64 or x86_64
    case "$ARCH" in
        arm64)  ASSET="ffmpeg-darwin-arm64" ;;
        x86_64) ASSET="ffmpeg-darwin-x64" ;;
        *)      echo "Unknown architecture: $ARCH"; exit 1 ;;
    esac
    echo "==> Downloading static ffmpeg ($ASSET)"
    URL="https://github.com/eugeneware/ffmpeg-static/releases/latest/download/$ASSET"
    if curl -fL --retry 3 -o vendor/ffmpeg "$URL"; then
        chmod +x vendor/ffmpeg
        xattr -d com.apple.quarantine vendor/ffmpeg 2>/dev/null || true
    else
        rm -f vendor/ffmpeg
        echo ""
        echo "Automatic ffmpeg download failed. Download a static macOS ffmpeg binary"
        echo "manually (e.g. from https://evermeet.cx/ffmpeg/ for Intel or"
        echo "https://osxexperts.net/ for Apple Silicon), put it at vendor/ffmpeg,"
        echo "run: chmod +x vendor/ffmpeg   and re-run this script."
        exit 1
    fi
fi
# Sanity check: does it actually run on this machine?
vendor/ffmpeg -version >/dev/null 2>&1 || { echo "vendor/ffmpeg does not run on this Mac"; exit 1; }

# ---- icon: make logo.icns from logo.png if we have one ----
if [ ! -f logo.icns ] && [ -f logo.png ]; then
    echo "==> Creating logo.icns from logo.png"
    rm -rf logo.iconset && mkdir logo.iconset
    for s in 16 32 64 128 256 512; do
        sips -z $s $s logo.png --out "logo.iconset/icon_${s}x${s}.png" >/dev/null
        d=$((s*2))
        sips -z $d $d logo.png --out "logo.iconset/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns logo.iconset -o logo.icns
    rm -rf logo.iconset
fi

echo "==> Building with PyInstaller"
rm -rf build "dist/Media Downloader" "dist/Media Downloader.app"
pyinstaller build.spec --noconfirm --clean

echo "==> Ad-hoc signing (required on Apple Silicon)"
codesign --force --deep --sign - "dist/Media Downloader.app"

echo "==> Zipping"
rm -f "dist/Media-Downloader-mac-$(uname -m).zip"
ditto -c -k --sequesterRsrc --keepParent "dist/Media Downloader.app" "dist/Media-Downloader-mac-$(uname -m).zip"

echo ""
echo "Done. Give your friends:  dist/Media-Downloader-mac-$(uname -m).zip"
echo "They must right-click the app > Open the first time (see README.md)."
