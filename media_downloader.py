"""Media Downloader - a small PySide6 front-end for yt-dlp."""

import configparser
import html
import importlib.machinery
import json
import logging
import logging.handlers
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
import zipfile
import zipimport

from PySide6.QtCore import (
    Property, QEvent, QPoint, QPropertyAnimation, Qt, QThread, QTimer, Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

APP_ID = "MediaDownloader.App"  # Windows taskbar grouping / icon identity

# ---------------- PATHS ----------------
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))
APP_NAME = "Media Downloader"


def user_data_dir():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_NAME)


if FROZEN:
    BASE_DIR = os.path.dirname(sys.executable)
    # PyInstaller: onefile -> temp dir, onedir -> <app>/_internal, mac -> Contents/Frameworks
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
    DATA_DIR = user_data_dir()
else:
    BASE_DIR = RESOURCE_DIR = DATA_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, "config.ini")
LOG_FILE = os.path.join(DATA_DIR, "media_downloader.log")
ICON_PATH = os.path.join(RESOURCE_DIR, "logo.ico")

# ---------------- yt-dlp BOOTSTRAP ----------------
# A newer yt-dlp downloaded by the in-app updater lives here as yt-dlp's official
# single-file (zipimport) release. Putting it first on sys.path makes it win over
# the copy bundled into the frozen app, so the app keeps working without a rebuild.
YTDLP_ZIP = os.path.join(DATA_DIR, "yt-dlp.zip")
YTDLP_LATEST_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_ZIP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"


class _ZipYtdlpFinder:
    """Meta-path finder that serves yt_dlp (and its submodules) from the zip.

    It has to sit at the front of sys.meta_path: in a PyInstaller app the frozen
    importer would otherwise find the bundled copy first, and simply adding the
    zip to sys.path would not be enough.
    """

    def __init__(self, zip_path):
        self.zip_path = zip_path

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "yt_dlp":
            return zipimport.zipimporter(self.zip_path).find_spec(fullname)
        if fullname.startswith("yt_dlp."):
            return importlib.machinery.PathFinder.find_spec(fullname, path)
        return None


def _import_ytdlp():
    if os.path.isfile(YTDLP_ZIP):
        finder = _ZipYtdlpFinder(YTDLP_ZIP)
        sys.meta_path.insert(0, finder)
        try:
            import yt_dlp as module
            if os.path.normcase(os.path.abspath(module.__file__)).startswith(
                    os.path.normcase(os.path.abspath(YTDLP_ZIP))):
                return module
            raise ImportError("yt_dlp was not loaded from the zip")
        except Exception:
            # Corrupt download: drop it and fall back to the bundled copy.
            sys.meta_path.remove(finder)
            for name in [n for n in sys.modules if n == "yt_dlp" or n.startswith("yt_dlp.")]:
                del sys.modules[name]
            try:
                os.remove(YTDLP_ZIP)
            except OSError:
                pass
    import yt_dlp as module
    return module


yt_dlp = _import_ytdlp()

UPDATE_CHECK_INTERVAL = 24 * 60 * 60  # seconds

DEFAULT_CONFIG = {
    "download_folder": os.path.expanduser("~/Downloads"),
    "audio_only": "false",
    "open_folder": "false",
    "playlist": "false",
    "quality": "Best",
    "cookies_file": "",
    "last_update_check": "0",
}

# label -> max height (None = no limit)
QUALITY_OPTIONS = [
    ("Best", None),
    ("2160p (4K)", 2160),
    ("1440p (2K)", 1440),
    ("1080p (FHD)", 1080),
    ("720p (HD)", 720),
    ("480p", 480),
    ("360p", 360),
]

VIDEO_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/|live/|embed/|v/)|youtu\.be/)"
    r"([\w-]{11})"
)
PLAYLIST_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|music\.)?youtube\.com/playlist\?(?:[^#\s]*&)?list="
)
LIST_PARAM_RE = re.compile(r"[?&]list=([\w-]+)")

# ---------------- LOGGING ----------------
log = logging.getLogger("media_downloader")


def setup_logging():
    log.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    try:
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8"
        )
        handler.setFormatter(fmt)
        log.addHandler(handler)
    except OSError:
        pass
    if not FROZEN:
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        log.addHandler(console)


class YdlLogger:
    """Adapter so yt-dlp writes into our log file instead of stdout."""

    def debug(self, msg):
        # yt-dlp sends both debug and info here; info has no [debug] prefix
        if msg.startswith("[debug] "):
            log.debug("yt-dlp: %s", msg)
        else:
            log.info("yt-dlp: %s", msg)

    def info(self, msg):
        log.info("yt-dlp: %s", msg)

    def warning(self, msg):
        log.warning("yt-dlp: %s", msg)

    def error(self, msg):
        log.error("yt-dlp: %s", msg)


# ---------------- HELPERS ----------------
def find_ffmpeg():
    """Locate ffmpeg: bundled next to the app first, then on PATH."""
    exe = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"
    candidates = [
        os.path.join(RESOURCE_DIR, exe),
        os.path.join(BASE_DIR, "_internal", exe),
        os.path.join(BASE_DIR, exe),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return shutil.which("ffmpeg")


FFMPEG_PATH = find_ffmpeg()


def ssl_context():
    """Frozen Python on macOS has no system CA bundle; use certifi when available."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/1.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
        return resp.read()


def ytdlp_version():
    return getattr(yt_dlp.version, "__version__", "unknown")


def version_tuple(v):
    parts = []
    for p in str(v).split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def build_format(max_height):
    if max_height is None:
        return "bestvideo+bestaudio/best"
    h = f"[height<={max_height}]"
    return f"bestvideo{h}+bestaudio/best{h}/bestvideo+bestaudio/best"


def format_duration(seconds):
    if not seconds:
        return "Live" if seconds is None else "0:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def clean_error(message):
    """Strip yt-dlp's 'ERROR: ' prefix and keep the first meaningful line."""
    message = str(message).strip()
    message = re.sub(r"^ERROR:\s*", "", message)
    return message.splitlines()[0] if message else "Unknown error"


def is_playlist_link(url):
    return bool(LIST_PARAM_RE.search(url))


def is_video_link(url):
    return bool(VIDEO_URL_RE.search(url))


def base_ydl_opts(cookies_file=None):
    opts = {
        "logger": YdlLogger(),
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "color": "never",
    }
    if cookies_file and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
    return opts


# ---------------- WORKERS ----------------
class DownloadWorker(QThread):
    progress = Signal(float, str)       # percent, status text
    status = Signal(str)                # status text only
    already_exists = Signal(str)        # final path that already exists
    completed = Signal(str, str)        # summary text, path to reveal
    cancelled = Signal()
    failed = Signal(str)

    POSTPROCESSOR_LABELS = {
        "Merger": "Merging video and audio...",
        "ExtractAudio": "Converting to MP3...",
        "Metadata": "Writing metadata...",
        "MoveFiles": "Finishing...",
    }

    def __init__(self, url, download_path, audio_only, max_height, playlist, cookies_file=None, overwrite=False, parent=None):
        super().__init__(parent)
        self.url = url
        self.download_path = download_path
        self.audio_only = audio_only
        self.max_height = max_height
        self.playlist = playlist and is_playlist_link(url)
        self.cookies_file = cookies_file
        self.overwrite = overwrite
        self._cancelled = False
        self._item_prefix = ""

    def cancel(self):
        self._cancelled = True

    # ---------- HOOKS (run in this thread) ----------
    def _progress_hook(self, d):
        if self._cancelled:
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

        info = d.get("info_dict") or {}
        idx = info.get("playlist_index")
        count = info.get("playlist_count") or info.get("n_entries")
        self._item_prefix = f"[{idx}/{count}] " if idx and count else ""

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            percent = min(downloaded / total * 100, 100.0) if total else 0.0
            speed = (d.get("_speed_str") or "").strip()
            eta = (d.get("_eta_str") or "").strip()
            parts = [f"{percent:.1f}%"]
            if speed:
                parts.append(speed)
            if eta and eta.lower() not in ("unknown", "n/a"):
                parts.append(f"ETA {eta}")
            self.progress.emit(percent, self._item_prefix + "  |  ".join(parts))

        elif d["status"] == "finished":
            self.progress.emit(100.0, self._item_prefix + "Download complete, processing...")

    def _postprocessor_hook(self, d):
        if d.get("status") == "started":
            name = d.get("postprocessor", "")
            label = self.POSTPROCESSOR_LABELS.get(name, "Processing...")
            self.status.emit(self._item_prefix + label)

    # ---------- OPTIONS ----------
    def _build_opts(self):
        opts = base_ydl_opts(self.cookies_file)
        opts.update({
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "updatetime": False,  # keep "now" as the file's modified time
            # Drop the source file's metadata; yt-dlp then writes its own.
            "postprocessor_args": {"Metadata": ["-map_metadata", "-1"]},
            "overwrites": self.overwrite,
        })
        if FFMPEG_PATH:
            opts["ffmpeg_location"] = FFMPEG_PATH

        if self.playlist:
            opts.update({
                "noplaylist": False,
                "ignoreerrors": "only_download",  # one bad video doesn't abort the rest
                "outtmpl": os.path.join(
                    self.download_path,
                    "%(playlist_title,playlist_id|Playlist)s",
                    "%(playlist_index)03d - %(title).200B.%(ext)s",
                ),
            })
        else:
            opts.update({
                "noplaylist": True,
                "outtmpl": os.path.join(self.download_path, "%(title).200B.%(ext)s"),
            })

        if self.audio_only:
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [
                    {"key": "FFmpegExtractAudio",
                     "preferredcodec": "mp3",
                     "preferredquality": "192"},
                    {"key": "FFmpegMetadata"},
                ],
            })
        else:
            opts.update({
                "format": build_format(self.max_height),
                "merge_output_format": "mp4",
                "postprocessors": [{"key": "FFmpegMetadata"}],
            })
        return opts

    def _expected_path(self, ydl, info):
        """Where the finished file will land, after merge/convert."""
        path = ydl.prepare_filename(info)
        base, _ = os.path.splitext(path)
        return base + (".mp3" if self.audio_only else ".mp4")

    # ---------- MAIN ----------
    def run(self):
        log.info("Download requested: %s (audio_only=%s, max_height=%s, playlist=%s)",
                 self.url, self.audio_only, self.max_height, self.playlist)
        opts = self._build_opts()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self.status.emit("Fetching video info...")
                info = ydl.extract_info(self.url, download=False)

                if not self.playlist and not self.overwrite:
                    expected = self._expected_path(ydl, info)
                    if os.path.exists(expected):
                        log.info("File already exists: %s", expected)
                        self.already_exists.emit(expected)
                        return

                if self._cancelled:
                    raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

                info = ydl.process_ie_result(info, download=True)
        except yt_dlp.utils.DownloadCancelled:
            log.info("Download cancelled by user")
            self.cancelled.emit()
            return
        except Exception as e:
            log.exception("Download failed")
            self.failed.emit(clean_error(e))
            return

        if self.playlist and info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            total = info.get("playlist_count") or len(info.get("entries") or [])
            summary = f"Playlist done: {len(entries)}/{total} videos"
            reveal = ""
            for entry in entries:
                downloads = entry.get("requested_downloads") or []
                if downloads and downloads[0].get("filepath"):
                    reveal = os.path.dirname(downloads[0]["filepath"])
                    break
            log.info("%s", summary)
            self.completed.emit(summary, reveal)
            return

        title = info.get("title") or "Download"
        downloads = info.get("requested_downloads") or []
        final_path = downloads[0].get("filepath") if downloads else ""
        log.info("Completed: %s -> %s", title, final_path)
        self.completed.emit(f"Completed: {title}", final_path or "")


class UpdateWorker(QThread):
    """Downloads the latest yt-dlp single-file release into DATA_DIR."""

    result = Signal(bool, bool, str)  # ok, updated, message

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        current = ytdlp_version()
        log.info("yt-dlp update check (installed %s)", current)
        try:
            release = json.loads(http_get(YTDLP_LATEST_API).decode("utf-8"))
            latest = str(release.get("tag_name") or "").strip()
            if not latest:
                raise ValueError("no tag_name in release info")
        except Exception as e:
            log.warning("Update check failed: %s", e)
            self.result.emit(False, False, "Update check failed - no internet?")
            return

        if version_tuple(latest) <= version_tuple(current):
            log.info("yt-dlp %s is up to date", current)
            self.result.emit(True, False, f"yt-dlp {current} is up to date")
            return

        log.info("Downloading yt-dlp %s", latest)
        tmp = YTDLP_ZIP + ".tmp"
        try:
            data = http_get(YTDLP_ZIP_URL, timeout=120)
            with open(tmp, "wb") as f:
                f.write(data)
            with zipfile.ZipFile(tmp) as zf:
                if "yt_dlp/version.py" not in zf.namelist():
                    raise ValueError("downloaded file is not a yt-dlp release")
            os.replace(tmp, YTDLP_ZIP)
        except Exception as e:
            log.error("Update download failed: %s", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            self.result.emit(False, False, "Update download failed - see log file")
            return

        log.info("yt-dlp %s downloaded; takes effect on next launch", latest)
        self.result.emit(True, True, f"yt-dlp updated {current} → {latest} - restart to use it")


class InfoFetcher(QThread):
    """Fetches title/uploader/duration and the thumbnail for a URL."""

    ready = Signal(int, dict)   # request id, info dict
    failed = Signal(int)

    def __init__(self, request_id, url, cookies_file=None, parent=None):
        super().__init__(parent)
        self.request_id = request_id
        self.url = url
        self.cookies_file = cookies_file

    def run(self):
        try:
            opts = base_ydl_opts(self.cookies_file)
            opts["skip_download"] = True
            playlist_only = PLAYLIST_URL_RE.search(self.url) and not is_video_link(self.url)
            if playlist_only:
                opts["extract_flat"] = "in_playlist"
            else:
                opts["noplaylist"] = True

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=False)

            if playlist_only:
                entries = info.get("entries") or []
                count = info.get("playlist_count") or len(entries)
                first_id = entries[0].get("id") if entries else None
                self.ready.emit(self.request_id, {
                    "title": info.get("title") or "Playlist",
                    "uploader": info.get("uploader") or info.get("channel") or "Playlist",
                    "duration": f"{count} videos",
                    "image": self._fetch_thumbnail(first_id, info.get("thumbnail")),
                })
                return

            self.ready.emit(self.request_id, {
                "title": info.get("title") or "Unknown",
                "uploader": info.get("uploader") or info.get("channel") or "Unknown",
                "duration": format_duration(info.get("duration")),
                "image": self._fetch_thumbnail(info.get("id"), info.get("thumbnail")),
            })
        except Exception as e:
            log.warning("Info fetch failed for %s: %s", self.url, clean_error(e))
            self.failed.emit(self.request_id)

    @staticmethod
    def _fetch_thumbnail(video_id, fallback_url):
        image = QImage()  # QImage (unlike QPixmap) is safe off the GUI thread
        url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" if video_id else fallback_url
        if not url:
            return image
        try:
            image.loadFromData(http_get(url, timeout=5))
        except Exception as e:
            log.debug("Thumbnail fetch failed: %s", e)
        return image


# ---------------- WIDGETS ----------------
class ToggleSwitch(QCheckBox):
    """Checkbox drawn as an animated toggle switch."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 0; height: 0; }")
        self.setFixedSize(260, 26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._offset = 1.0 if self.isChecked() else 0.0

        self._animation = QPropertyAnimation(self, b"offset", self)
        self._animation.setDuration(160)
        self.toggled.connect(self._start_animation)

    def get_offset(self):
        return self._offset

    def set_offset(self, value):
        self._offset = value
        self.update()

    offset = Property(float, get_offset, set_offset)

    def setChecked(self, checked):
        super().setChecked(checked)
        self._offset = 1.0 if checked else 0.0
        self.update()

    def _start_animation(self, checked):
        self._animation.stop()
        self._animation.setStartValue(self._offset)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle()
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        switch_w, switch_h, padding = 44, 22, 4
        radius = switch_h / 2
        x = rect.width() - switch_w - padding
        y = (rect.height() - switch_h) / 2

        if not self.isEnabled():
            track = QColor(60, 60, 70)
            text_color = QColor("#6f6a85")
            thumb = QColor("#9d93b5")
        else:
            track = QColor("#9d4edd") if self.isChecked() else QColor(90, 90, 100)
            text_color = QColor("#e6dcff")
            thumb = QColor("#ffffff")

        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(x, y, switch_w, switch_h, radius, radius)

        thumb_x = x + 2 + (switch_w - switch_h) * self._offset
        painter.setBrush(thumb)
        painter.drawEllipse(int(thumb_x), int(y + 2), switch_h - 4, switch_h - 4)

        painter.setPen(text_color)
        painter.drawText(0, 0, int(x - padding), rect.height(),
                         Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()


class TitleBar(QWidget):
    """Draggable custom title bar for the frameless window."""

    def __init__(self, window, title):
        super().__init__(window)
        self._window = window
        self._drag_offset = QPoint()
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)

        label = QLabel(title)
        label.setObjectName("Title")

        minimize_btn = QPushButton("−")
        minimize_btn.setFixedSize(40, 30)
        minimize_btn.setObjectName("MinimizeButton")
        minimize_btn.clicked.connect(window.showMinimized)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(40, 30)
        close_btn.setObjectName("CloseButton")
        close_btn.clicked.connect(window.close)

        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(minimize_btn)
        layout.addWidget(close_btn)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        handle = self._window.windowHandle()
        # Native move gives proper snapping/multi-monitor behaviour where supported.
        if handle is None or not handle.startSystemMove():
            self._drag_offset = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
        event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and not self._drag_offset.isNull():
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = QPoint()
        event.accept()


# ---------------- MAIN WINDOW ----------------
class MediaDownloader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setFixedSize(540, 420)
        # WindowMinimizeButtonHint lets the taskbar restore a frameless window.
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint
        )
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        self.config = configparser.ConfigParser()
        self.load_config()

        self.worker = None
        self._updater = None
        self._update_quiet = True
        self._fetchers = set()
        self._info_request = 0
        self._last_clipboard = ""

        self._url_timer = QTimer(self)
        self._url_timer.setSingleShot(True)
        self._url_timer.setInterval(400)
        self._url_timer.timeout.connect(self.fetch_video_info)

        self.setup_ui()
        self.setStyleSheet(STYLE)
        self.maybe_update_ytdlp()

        if not FFMPEG_PATH:
            log.warning("ffmpeg not found")
            self.status.setText("Warning: ffmpeg not found - merging/MP3 will fail")

        self.check_clipboard()

    # ---------- CONFIG ----------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                self.config.read(CONFIG_FILE, encoding="utf-8")
            except configparser.Error as e:
                log.warning("Could not read config: %s", e)
        defaults = self.config["DEFAULT"]
        for key, value in DEFAULT_CONFIG.items():
            defaults.setdefault(key, value)

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                self.config.write(f)
        except OSError as e:
            log.error("Could not save config: %s", e)
            self.status.setText(f"Could not save settings: {e}")

    def cfg(self, key):
        return self.config["DEFAULT"].get(key, DEFAULT_CONFIG.get(key, ""))

    def cfg_bool(self, key):
        return self.config["DEFAULT"].getboolean(key, fallback=False)

    def set_cfg(self, key, value):
        if isinstance(value, bool):
            value = str(value).lower()
        self.config["DEFAULT"][key] = str(value)
        self.save_config()

    @property
    def download_folder(self):
        return self.cfg("download_folder")

    # ---------- UI ----------
    def setup_ui(self):
        central = QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 12)

        self.title_bar = TitleBar(self, APP_NAME)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 0)
        content_layout.setSpacing(12)

        # URL row
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste a video URL here")
        self.url_input.textChanged.connect(self.on_url_changed)
        self.url_input.returnPressed.connect(self.start_download)

        self.clear_btn = QPushButton("✕")
        self.clear_btn.setFixedSize(30, 30)
        self.clear_btn.setObjectName("ClearButton")
        self.clear_btn.clicked.connect(self.url_input.clear)

        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.clear_btn)

        # Toggles + video info
        toggles_info_layout = QHBoxLayout()
        toggles_info_layout.setSpacing(20)

        toggles_layout = QVBoxLayout()
        toggles_layout.setSpacing(6)

        self.audio_only = ToggleSwitch("Audio only (MP3)")
        self.audio_only.setChecked(self.cfg_bool("audio_only"))
        self.audio_only.toggled.connect(self.on_audio_only_toggled)

        self.playlist = ToggleSwitch("Download whole playlist")
        self.playlist.setChecked(self.cfg_bool("playlist"))
        self.playlist.setToolTip("When the link contains a playlist, download every video into a subfolder.")
        self.playlist.toggled.connect(self.on_playlist_toggled)

        self.open_folder = ToggleSwitch("Open folder when complete")
        self.open_folder.setChecked(self.cfg_bool("open_folder"))
        self.open_folder.toggled.connect(lambda v: self.set_cfg("open_folder", v))

        for t in (self.audio_only, self.playlist, self.open_folder):
            toggles_layout.addWidget(t, 0, Qt.AlignLeft)

        info_layout = QHBoxLayout()
        info_layout.setSpacing(6)
        info_layout.setContentsMargins(0, 0, 0, 0)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("Thumbnail")
        self.thumbnail_label.setFixedSize(80, 45)
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.hide()

        self.info_label = QLabel()
        self.info_label.setObjectName("InfoLabel")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.info_label.setMaximumWidth(160)
        self.info_label.hide()

        info_layout.addWidget(self.thumbnail_label)
        info_layout.addWidget(self.info_label)
        info_layout.addStretch()

        info_widget = QWidget()
        info_widget.setLayout(info_layout)

        toggles_info_layout.addLayout(toggles_layout)
        toggles_info_layout.addStretch()
        toggles_info_layout.addWidget(info_widget, 0, Qt.AlignTop)

        # Quality row
        quality_layout = QHBoxLayout()
        self.quality_label = QLabel("Video Quality:")
        self.quality_selector = QComboBox()
        for label, height in QUALITY_OPTIONS:
            self.quality_selector.addItem(label, height)
        index = self.quality_selector.findText(self.cfg("quality"), Qt.MatchStartsWith)
        self.quality_selector.setCurrentIndex(max(index, 0))
        self.quality_selector.currentIndexChanged.connect(self.save_quality)
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_selector)

        # Download button
        self.download_btn = QPushButton("Download")
        self.download_btn.clicked.connect(self.start_download)

        # Folder row
        location_layout = QHBoxLayout()
        location_btn = QPushButton("Change Folder")
        location_btn.clicked.connect(self.select_folder)
        self.location_label = QLabel(self.download_folder)
        self.location_label.setWordWrap(True)
        location_layout.addWidget(location_btn)
        location_layout.addWidget(self.location_label)

        # Progress + bottom bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.status = QLabel("Ready")

        bottom_bar = QHBoxLayout()
        bottom_bar.addWidget(self.status, 1)

        self.cookies_btn = QPushButton("🍪")
        self.cookies_btn.setFixedSize(30, 30)
        self.cookies_btn.setObjectName("CookiesButton")
        self.cookies_btn.setCursor(Qt.PointingHandCursor)
        self.cookies_btn.clicked.connect(self.on_cookies_clicked)
        self.cookies_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cookies_btn.customContextMenuRequested.connect(self._cookies_context_menu)
        self._refresh_cookies_button()

        self.update_btn = QPushButton("⟳")
        self.update_btn.setFixedSize(30, 30)
        self.update_btn.setObjectName("UpdateButton")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setToolTip("Check for yt-dlp updates")
        self.update_btn.clicked.connect(self.check_for_updates)

        bottom_bar.addWidget(self.update_btn)
        bottom_bar.addWidget(self.cookies_btn)

        content_layout.addLayout(url_layout)
        content_layout.addLayout(toggles_info_layout)
        content_layout.addLayout(quality_layout)
        content_layout.addWidget(self.download_btn)
        content_layout.addLayout(location_layout)
        content_layout.addWidget(self.progress)
        content_layout.addLayout(bottom_bar)

        layout.addWidget(self.title_bar)
        layout.addWidget(content)

        self.on_audio_only_toggled(self.audio_only.isChecked(), save=False)

    # ---------- UPDATES ----------
    def maybe_update_ytdlp(self):
        """Silent background check at most once a day."""
        try:
            last = float(self.cfg("last_update_check") or 0)
        except ValueError:
            last = 0
        if time.time() - last < UPDATE_CHECK_INTERVAL:
            return
        self._run_update(quiet=True)

    def check_for_updates(self):
        self._run_update(quiet=False)

    def _run_update(self, quiet):
        if self._updater is not None:
            return
        self._update_quiet = quiet
        self.update_btn.setEnabled(False)
        if not quiet:
            self.status.setText("Checking for yt-dlp updates...")
        self._updater = UpdateWorker(self)
        self._updater.result.connect(self.on_update_result)
        self._updater.finished.connect(self._updater_done)
        self._updater.start()

    def on_update_result(self, ok, updated, message):
        if ok:
            self.set_cfg("last_update_check", str(int(time.time())))
        if updated or not self._update_quiet:
            self.status.setText(message)

    def _updater_done(self):
        if self._updater is not None:
            self._updater.deleteLater()
            self._updater = None
        self.update_btn.setEnabled(True)

    # ---------- CLIPBOARD ----------
    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.check_clipboard()
        super().changeEvent(event)

    def check_clipboard(self):
        """Auto-fill the URL box from the clipboard if it holds a new YouTube link."""
        if self.url_input.text().strip():
            return
        text = (QApplication.clipboard().text() or "").strip()
        if text == self._last_clipboard:
            return
        self._last_clipboard = text
        if is_video_link(text) or PLAYLIST_URL_RE.search(text):
            self.url_input.setText(text)

    # ---------- FOLDER / COOKIES ----------
    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Download Folder", self.download_folder
        )
        if folder:
            self.set_cfg("download_folder", folder)
            self.location_label.setText(folder)

    def on_cookies_clicked(self):
        if not self.cfg("cookies_file"):
            self.select_cookies_file()
            return
        menu = QMenu(self)
        menu.addAction("Change cookies file...", self.select_cookies_file)
        menu.addAction("Remove cookies file", self.clear_cookies_file)
        menu.addSeparator()
        menu.addAction("Open log file", self.open_log)
        menu.exec(self.cookies_btn.mapToGlobal(
            self.cookies_btn.rect().topLeft() - QPoint(0, menu.sizeHint().height())
        ))

    def select_cookies_file(self):
        current = self.cfg("cookies_file")
        start_dir = os.path.dirname(current) if current else os.path.expanduser("~")
        file, _ = QFileDialog.getOpenFileName(
            self, "Select Cookies File", start_dir, "Text Files (*.txt);;All Files (*)"
        )
        if file:
            self.set_cfg("cookies_file", file)
            self._refresh_cookies_button()

    def clear_cookies_file(self):
        self.set_cfg("cookies_file", "")
        self._refresh_cookies_button()

    def _refresh_cookies_button(self):
        path = self.cfg("cookies_file")
        self.cookies_btn.setToolTip(
            f"Cookies file: {path}\n(click to change or remove)" if path
            else "Set a cookies file (only needed for age-restricted or sign-in-only videos)\n"
                 "Right-click for the log file"
        )

    def _cookies_context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Open log file", self.open_log)
        menu.exec(self.cookies_btn.mapToGlobal(pos))

    def open_log(self):
        self._open_path(LOG_FILE if os.path.exists(LOG_FILE) else DATA_DIR)

    # ---------- OPTIONS ----------
    def on_audio_only_toggled(self, checked, save=True):
        self.quality_selector.setEnabled(not checked)
        self.quality_label.setEnabled(not checked)
        if save:
            self.set_cfg("audio_only", checked)

    def on_playlist_toggled(self, checked):
        self.set_cfg("playlist", checked)
        self._update_playlist_hint()

    def save_quality(self):
        self.set_cfg("quality", self.quality_selector.currentText().split()[0])

    def _update_playlist_hint(self):
        if self.worker is not None:
            return
        url = self.url_input.text().strip()
        if is_playlist_link(url):
            if self.playlist.isChecked():
                self.status.setText("Playlist link - will download every video")
            else:
                self.status.setText("Playlist link - downloading this video only")
        elif self.status.text().startswith("Playlist link"):
            self.status.setText("Ready")

    # ---------- VIDEO INFO ----------
    def on_url_changed(self, text):
        self._url_timer.stop()
        self._info_request += 1  # invalidates any in-flight fetch
        text = text.strip()
        if is_video_link(text) or PLAYLIST_URL_RE.search(text):
            self._url_timer.start()
        else:
            self._clear_video_info()
        self._update_playlist_hint()

    def _clear_video_info(self):
        self.info_label.clear()
        self.info_label.hide()
        self.thumbnail_label.clear()
        self.thumbnail_label.hide()

    def fetch_video_info(self):
        url = self.url_input.text().strip()
        if not url:
            return
        fetcher = InfoFetcher(self._info_request, url, self.cfg("cookies_file"), self)
        fetcher.ready.connect(self.update_video_info)
        fetcher.finished.connect(lambda f=fetcher: self._fetcher_done(f))
        self._fetchers.add(fetcher)
        fetcher.start()

    def _fetcher_done(self, fetcher):
        self._fetchers.discard(fetcher)
        fetcher.deleteLater()

    def update_video_info(self, request_id, info):
        if request_id != self._info_request:
            return  # stale result from an earlier URL
        self.info_label.setText(
            f"<b>{html.escape(info['title'])}</b><br>"
            f"{html.escape(info['uploader'])} • {info['duration']}"
        )
        self.info_label.show()

        image = info["image"]
        if image.isNull():
            self.thumbnail_label.hide()
        else:
            pixmap = QPixmap.fromImage(image).scaled(
                80, 45, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(pixmap)
            self.thumbnail_label.show()

    # ---------- DOWNLOAD ----------
    def start_download(self, overwrite=False):
        if self.worker is not None:
            self.cancel_download()
            return

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please enter a video URL.")
            return
        if not os.path.isdir(self.download_folder):
            QMessageBox.warning(
                self, "Folder Missing",
                f"Download folder does not exist:\n{self.download_folder}"
            )
            return

        self.progress.setValue(0)
        self.status.setText("Starting...")
        self.download_btn.setText("Cancel")

        self.worker = DownloadWorker(
            url,
            self.download_folder,
            self.audio_only.isChecked(),
            self.quality_selector.currentData(),
            self.playlist.isChecked(),
            cookies_file=self.cfg("cookies_file"),
            overwrite=overwrite,
            parent=self,
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.status.setText)
        self.worker.already_exists.connect(self.on_already_exists)
        self.worker.completed.connect(self.download_finished)
        self.worker.cancelled.connect(self.download_cancelled)
        self.worker.failed.connect(self.download_error)
        self.worker.finished.connect(self._worker_done)
        self.worker.start()

    def cancel_download(self):
        if self.worker is not None:
            self.worker.cancel()
            self.status.setText("Cancelling...")
            self.download_btn.setEnabled(False)

    def _worker_done(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.download_btn.setText("Download")
        self.download_btn.setEnabled(True)

    def update_progress(self, percent, text):
        self.progress.setValue(int(percent))
        self.status.setText(text)

    def on_already_exists(self, path):
        self.status.setText("File already exists")
        # Let the worker thread finish before we possibly start a new one.
        if self.worker is not None:
            self.worker.wait(2000)
            self._worker_done()

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("File Already Exists")
        box.setText(f"{os.path.basename(path)}\nalready exists in the download folder.")
        overwrite = box.addButton("Overwrite", QMessageBox.AcceptRole)
        box.addButton("Skip", QMessageBox.RejectRole)
        box.exec()

        if box.clickedButton() is overwrite:
            self.start_download(overwrite=True)
        else:
            self.status.setText("Skipped - file already exists")

    def download_finished(self, summary, reveal_path):
        self.progress.setValue(100)
        self.status.setText(summary)
        if self.open_folder.isChecked():
            self.reveal_in_folder(reveal_path)

    def download_cancelled(self):
        self.progress.setValue(0)
        self.status.setText("Cancelled")

    def download_error(self, message):
        self.progress.setValue(0)
        self.status.setText("Error")
        QMessageBox.critical(
            self, "Download Failed",
            f"{message}\n\nDetails are in the log file:\n{LOG_FILE}"
        )

    def reveal_in_folder(self, path):
        if path and os.path.isfile(path):
            try:
                if IS_WINDOWS:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                    return
                if sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", path])
                    return
            except OSError as e:
                log.warning("Could not reveal file: %s", e)
        self._open_path(path if path and os.path.isdir(path) else self.download_folder)

    @staticmethod
    def _open_path(path):
        try:
            if IS_WINDOWS:
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as e:
            log.warning("Could not open %s: %s", path, e)

    # ---------- SHUTDOWN ----------
    def closeEvent(self, event):
        if self.worker is not None:
            self.worker.cancel()
        threads = list(self._fetchers)
        if self.worker is not None:
            threads.append(self.worker)
        if self._updater is not None:
            threads.append(self._updater)
        for t in threads:
            if not t.wait(3000):
                t.terminate()
                t.wait(1000)
        super().closeEvent(event)


# ---------------- STYLES ----------------
STYLE = """
    QWidget#CentralWidget { background-color: #0f0f14; }
    QWidget#TitleBar { background-color: #0f0f14; }
    QWidget {
        background-color: transparent;
        color: #e6dcff;
        font-family: 'Segoe UI', 'Arial', sans-serif;
        font-size: 10pt;
    }
    QLabel#Title { font-size: 11pt; font-weight: 600; color: #c77dff; }
    QLabel#InfoLabel { font-size: 9pt; }
    QLabel#Thumbnail {
        background-color: rgba(28, 28, 38, 180);
        border: 1px solid #3c096c;
        border-radius: 4px;
    }
    QLabel:disabled { color: #6f6a85; }
    QLineEdit {
        background-color: rgba(28, 28, 38, 180);
        border: 1px solid #3c096c;
        border-radius: 6px;
        padding: 6px;
    }
    QPushButton {
        background-color: #5a189a;
        border-radius: 6px;
        padding: 8px;
        font-weight: 600;
    }
    QPushButton:hover { background-color: #7b2cbf; }
    QPushButton:disabled { background-color: #3a2a55; color: #9d93b5; }
    QPushButton#MinimizeButton, QPushButton#CloseButton {
        background-color: transparent; font-size: 20px; font-weight: normal;
    }
    QPushButton#MinimizeButton:hover { background-color: rgba(60, 9, 108, 150); }
    QPushButton#CloseButton:hover { background-color: #d32f2f; }
    QPushButton#ClearButton, QPushButton#CookiesButton, QPushButton#UpdateButton {
        background-color: rgba(60, 9, 108, 180);
        border: 1px solid transparent;
        padding: 2px; font-size: 14px; font-weight: normal;
    }
    QPushButton#ClearButton:hover, QPushButton#CookiesButton:hover,
    QPushButton#UpdateButton:hover { background-color: #5a189a; }
    QPushButton#UpdateButton { font-size: 16px; }
    QPushButton#UpdateButton:disabled { background-color: #3a2a55; color: #9d93b5; }
    QProgressBar {
        background-color: rgba(28, 28, 38, 180);
        border: none;
        border-radius: 6px;
        max-height: 14px;
    }
    QProgressBar::chunk { background-color: #9d4edd; border-radius: 6px; }
    QComboBox {
        background-color: rgba(28, 28, 38, 180);
        border: 1px solid #3c096c;
        border-radius: 6px;
        padding: 6px;
    }
    QComboBox:hover { border: 1px solid #5a189a; }
    QComboBox:disabled { color: #6f6a85; border-color: #2a1a40; }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background-color: #1c1c26;
        border: 1px solid #3c096c;
        selection-background-color: #5a189a;
    }
    QMenu { background-color: #1c1c26; border: 1px solid #3c096c; padding: 4px; }
    QMenu::item { padding: 6px 16px; border-radius: 4px; }
    QMenu::item:selected { background-color: #5a189a; }
    QMessageBox { background-color: #1c1c26; }
    QToolTip { background-color: #1c1c26; color: #e6dcff; border: 1px solid #3c096c; }
"""


# ---------------- RUN ----------------
def main():
    setup_logging()
    log.info("Starting (frozen=%s, yt-dlp=%s, ffmpeg=%s, data=%s)",
             FROZEN, ytdlp_version(), FFMPEG_PATH, DATA_DIR)

    app = QApplication(sys.argv)

    if IS_WINDOWS:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    window = MediaDownloader()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
