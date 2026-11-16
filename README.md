# Media Downloader

A small app that downloads videos as MP4 or audio as MP3 from YouTube and most other video sites. Paste a link, press Download.

---

## For friends: installing and using it

You don't need Python or anything else installed — the app is self-contained.

**Download:** go to the [Releases page](https://github.com/leanbeefsteak-rgb/Media-Downloader/releases/latest) and pick the file for your computer:

| Your computer | File |
|---|---|
| Windows | `Media-Downloader-windows.exe` |
| Mac with Apple Silicon (M1/M2/M3/M4 — most Macs from 2020 on) | `Media-Downloader-mac-arm64.zip` |
| Mac with an Intel chip (older Macs) | `Media-Downloader-mac-x86_64.zip` |

Not sure which Mac you have? Click the Apple menu → **About This Mac**. If it says "Apple M…" you want arm64; if it says "Intel" you want x86_64.

### Windows

1. Download **`Media-Downloader-windows.exe`** and put it anywhere (Desktop, Downloads, wherever).
2. Double-click it. The first time, Windows may show a blue **"Windows protected your PC"** box because the app isn't from a registered publisher. Click **More info → Run anyway**. This only happens once.
3. The first launch takes a few seconds (it unpacks itself); after that it opens quickly.

### macOS

1. Download the **`Media-Downloader-mac-….zip`** file and double-click it to unzip. Drag **Media Downloader.app** into your **Applications** folder (or anywhere you like).
2. The first time, **don't double-click it**. Instead **right-click (or Control-click) the app → Open → Open**. macOS will warn that it can't verify the developer; this is because the app isn't registered with Apple, not because anything is wrong.
3. On **macOS 15 (Sequoia) or newer**, right-click → Open may not be enough. If the app refuses to open: open **System Settings → Privacy & Security**, scroll down, and next to the message about "Media Downloader" click **Open Anyway**. Then open the app again.
4. After the first time, it opens normally.

If macOS says the app is *"damaged and can't be opened"*, open Terminal and run
`xattr -cr "/Applications/Media Downloader.app"` then try again.

### Using it

- Paste a video link into the box (if you copied a YouTube link, it fills in automatically). The title and thumbnail preview only appears for YouTube links, but downloads work from most video sites.
- **Audio only (MP3)** — get just the audio as an MP3.
- **Download whole playlist** — if the link is a playlist, get every video into a folder.
- **Open folder when complete** — shows the file in Explorer/Finder when it's done.
- **Video Quality** — pick a maximum resolution; "Best" takes the highest available.
- **Change Folder** — where files are saved (defaults to your Downloads folder).
- Bottom-right: **⟳** checks for an update to the download engine (yt-dlp). **🍪** sets a cookies file — you only need this for age-restricted videos or if YouTube asks you to sign in; otherwise ignore it.

### If downloads stop working

YouTube changes things regularly and the download engine (yt-dlp) needs updating to keep up. The app checks for updates once a day by itself, but if a download fails, press **⟳** in the bottom-right, wait for "updated", then **close and reopen the app**.

Settings and a log file live in:
- Windows: `%APPDATA%\Media Downloader\`
- macOS: `~/Library/Application Support/Media Downloader/`

If something goes wrong, the log file there says why.

---

### The manual way: building on your own computer

PyInstaller can't cross-compile, so **build the Windows version on Windows and the Mac version on a Mac**.

Files in the repository:

```
media_downloader.py           the app
requirements.txt              Python dependencies
build.spec                    PyInstaller recipe (both platforms)
build_windows.ps1             Windows build script
build_mac.sh                  macOS build script
logo.ico                      app icon (Windows, and shown in-app)
logo.png                      optional, 1024×1024 — build_mac.sh turns it into logo.icns
.github/workflows/build.yml   GitHub Actions: builds all platforms and publishes a release
.gitignore                    keeps build output, settings and cookies out of the repository
LICENSE                       GPL-3.0
```

### Windows

1. Install Python 3.10+ from https://python.org — tick **"Add python.exe to PATH"**.
2. Open PowerShell in the folder and run:
   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass   # allows running the script this session
   .\build_windows.ps1
   ```
   The script creates a virtual environment, installs dependencies, downloads a static `ffmpeg.exe` into `vendor/`, and builds.
3. Result: **`dist\Media Downloader.exe`** (~80–100 MB). That one file is all your friends need.

### macOS

1. Install Python 3.10+ (https://python.org or `brew install python`).
2. In Terminal, in the folder: `bash build_mac.sh`
   The script downloads a static `ffmpeg` into `vendor/`, builds the `.app`, ad-hoc signs it, and zips it.
3. Result: **`dist/Media-Downloader-mac-arm64.zip`** (or `-x86_64`). Send the zip.

An Apple Silicon build only runs on Apple Silicon Macs. An Intel build runs on both (through Rosetta). If your friends have a mix, build on an Intel Mac, or build once on each and send the right one.

### Things to know

- **Licence.** The project is under the GPL-3.0 (see `LICENSE`). That's deliberate: the bundled ffmpeg builds are GPL, and shipping them inside the app means the app has to be GPL-compatible too. In practice it only means that if someone redistributes a modified version they must publish their source as well. yt-dlp (Unlicense) and PySide6 (LGPL) are fine with this.
- **No code signing.** The app isn't signed with a Microsoft or Apple developer certificate, which is why friends see the one-time warnings above. Signing costs money (Apple: $99/yr) and is only worth it if you distribute widely.
- **yt-dlp updates itself inside the app.** The built app bundles whatever yt-dlp version was current when you built it, but it checks GitHub daily and downloads yt-dlp's official single-file release into the app-data folder, which is loaded in preference to the bundled copy. So you don't need to rebuild every time YouTube breaks something — the ⟳ button covers it. Rebuild occasionally anyway to pick up new PySide6/Python/ffmpeg versions.
- **ffmpeg** is bundled and is what merges video+audio and makes MP3s. If `vendor/ffmpeg(.exe)` is missing at build time, the spec prints a warning and the app will say "ffmpeg not found" at the bottom when launched.
- **Antivirus false positives.** Single-file PyInstaller executables are occasionally flagged by overzealous antivirus software. If a friend's AV quarantines it, they can restore it and add an exclusion, or you can switch to a folder build (`onefile=False` in `build.spec`) and send a zip, which is flagged less often.
- **Rebuilding:** delete `build/` and `dist/` (the scripts do this) and run the script again. The `.venv/` and `vendor/` folders are cached and reused.
