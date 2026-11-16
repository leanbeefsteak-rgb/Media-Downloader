# Media Downloader

A small app that downloads videos as MP4 or audio as MP3 from YouTube and most other video sites. Paste a link, press Download.

---

## For friends: installing and using it

You don't need Python or anything else installed - the app is self-contained.

**Download:** go to the [Releases page](https://github.com/leanbeefsteak-rgb/Media-Downloader/releases/latest) and pick the file for your computer:

| Your computer | File |
|---|---|
| Windows | `Media-Downloader-windows.exe` |
| Mac with Apple Silicon (M1/M2/M3/M4 - most Macs from 2020 on) | `Media-Downloader-mac-arm64.zip` |
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
- **Audio only (MP3)** - get just the audio as an MP3.
- **Download whole playlist** - if the link is a playlist, get every video into a folder.
- **Open folder when complete** - shows the file in Explorer/Finder when it's done.
- **Video Quality** - pick a maximum resolution; "Best" takes the highest available.
- **Change Folder** - where files are saved (defaults to your Downloads folder).
- Bottom-right: **⟳** checks for an update to the download engine (yt-dlp). **🍪** sets a cookies file - you only need this for age-restricted videos or if YouTube asks you to sign in; otherwise ignore it.

### If downloads stop working

YouTube changes things regularly and the download engine (yt-dlp) needs updating to keep up. The app checks for updates once a day by itself, but if a download fails, press **⟳** in the bottom-right, wait for "updated", then **close and reopen the app**.

Settings and a log file live in:
- Windows: `%APPDATA%\Media Downloader\`
- macOS: `~/Library/Application Support/Media Downloader/`

If something goes wrong, the log file there says why.