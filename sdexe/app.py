import os
import io
import re
import logging
import uuid
import time
import tempfile
import threading
import json
import shutil
import subprocess
import zipfile
import atexit
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from flask import Flask, render_template, request, jsonify, send_file, Response
from werkzeug.exceptions import HTTPException
from PIL import Image

from sdexe import __version__
from sdexe import tools
from sdexe import media as media_opts  # "media" is taken by the /media page route


def _ensure_ca_bundle():
    """Point OpenSSL at certifi's CA bundle when the interpreter has none.

    Framework/Homebrew Python on macOS frequently ships without a usable CA
    bundle, so every HTTPS verification (yt-dlp downloads, the update check)
    fails with CERTIFICATE_VERIFY_FAILED. If no system bundle is found and the
    env var isn't already set, fall back to certifi so networking just works.
    """
    import ssl
    if os.environ.get("SSL_CERT_FILE"):
        return
    paths = ssl.get_default_verify_paths()
    if (paths.cafile and os.path.exists(paths.cafile)) or (paths.capath and os.path.isdir(paths.capath)):
        return
    try:
        import certifi
        bundle = certifi.where()
        if os.path.exists(bundle):
            os.environ["SSL_CERT_FILE"] = bundle
    except Exception:
        pass


_ensure_ca_bundle()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB upload limit
# Flask's defaults stop a pasted text field at 500 KB and a batch at 1000
# parts, and report both as a 413. Text tools and batch renames go past that.
app.config["MAX_FORM_MEMORY_SIZE"] = 64 * 1024 * 1024
app.config["MAX_FORM_PARTS"] = 10_000


@app.errorhandler(500)
def _server_error(e):
    # Tool routes are fetched by JS that expects JSON; an HTML error page reads
    # as "Network error". Pages keep Flask's normal behaviour.
    if request.path.startswith("/api/"):
        logger.exception("unhandled error on %s", request.path)
        return jsonify({"error": "Something went wrong on sdexe's side. Details are in the log."}), 500
    return e


def _body() -> dict:
    """The JSON request body as a dict. A missing, invalid or non-object body
    (a list, a string) gives {} rather than crashing on .get()."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@app.errorhandler(ValueError)
@app.errorhandler(KeyError)
@app.errorhandler(TypeError)
def _bad_input(e):
    # A tool given bad input (a start time of "abc", an unknown format, a
    # malformed body) raises one of these. That's the user's input, not a
    # server fault: say what was wrong with a 400 instead of a bare 500.
    if not request.path.startswith("/api/"):
        raise e
    # Logged with its traceback: a bug in sdexe raises these too, and answered
    # only with a 400 it would be indistinguishable from a bad request.
    logger.warning("unhandled %s on %s, answered as a bad request", type(e).__name__, request.path,
                   exc_info=(type(e), e, e.__traceback__))
    msg = str(e).strip("'\"") if isinstance(e, ValueError) else "The request was missing or had a malformed field."
    return jsonify({"error": msg or "Invalid input."}), 400


@app.errorhandler(413)
def _too_large(_e):
    # Flask's default is an HTML page, which the pages' res.json() can't read,
    # so the user saw "Network error" instead of the reason.
    if (request.content_length or 0) > app.config["MAX_CONTENT_LENGTH"]:
        return jsonify({"error": "That file is over the 500 MB upload limit."}), 413
    return jsonify({"error": "That is too much to process in one go (too much text, or too many files)."}), 413


@app.errorhandler(HTTPException)
def _http_error(e):
    # An unknown /api/ path, a wrong method, a malformed upload: JSON like
    # every other API error, since the pages' JS calls res.json() on it.
    if request.path.startswith("/api/") and e.code and e.code >= 400:
        return jsonify({"error": e.description or e.name}), e.code
    return e


logger = logging.getLogger("sdexe")

# Hosts allowed besides loopback. Empty unless sdexe was started with --host,
# which is the user saying this machine should be reachable under that name.
_extra_hosts: set = set()
# --host 0.0.0.0: other devices reach it by IP address. A Host that is an IP
# literal cannot be a rebound domain name, so those are let through.
_allow_ip_hosts = False


def _host_name(netloc: str) -> str:
    """'127.0.0.1:5001' -> '127.0.0.1', '[::1]:5001' and '[::1]' -> '::1'."""
    netloc = netloc.strip().lower()
    if netloc.startswith("["):
        return netloc[1:].split("]", 1)[0]
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def _host_allowed(name: str) -> bool:
    if name in ("127.0.0.1", "localhost", "::1") or name in _extra_hosts:
        return True
    if _allow_ip_hosts:
        import ipaddress
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            pass
    return False


@app.before_request
def csrf_check():
    # Reject a Host that is not loopback. Without this, any website the user
    # visits can point its own domain at 127.0.0.1 (DNS rebinding) and read
    # local endpoints such as the download history and configured paths.
    raw_host = (request.headers.get("Host") or "").strip()
    if raw_host and not _host_allowed(_host_name(raw_host)):
        return jsonify({"error": "Forbidden"}), 403

    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    origin = request.headers.get("Origin") or ""
    if origin:
        # Same origin only, port included: a page served from another port on
        # this machine (someone else's dev server) is not sdexe either.
        if urlparse(origin).netloc.lower() != raw_host.lower():
            return jsonify({"error": "Forbidden"}), 403


_download_dir_swept = False


@app.before_request
def _ensure_download_dir():
    global _download_dir_swept
    DOWNLOAD_DIR.mkdir(mode=0o700, exist_ok=True)
    if not _download_dir_swept:
        _download_dir_swept = True
        _remove_orphaned_download_dirs()


@app.context_processor
def inject_version():
    return {"version": __version__}

@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    # No other site may put these pages in a frame and steer clicks onto
    # Update, Install ffmpeg or Open folder.
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response

# Named here, created on the first request (_ensure_download_dir): every CLI
# command imports this module, and one that was killed left an empty
# toolkit_* directory behind each time.
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / f"toolkit_{os.getpid()}_{uuid.uuid4().hex[:12]}"


def _remove_orphaned_download_dirs():
    """Delete the download directory of an sdexe server that is no longer
    running. One that was killed, or quit from the macOS menu bar icon (which
    exits without running Python's exit handlers), never cleaned up after
    itself, and the directory can hold gigabytes. The process id is in the
    name; a directory whose process is gone belongs to nobody."""
    import sys
    if sys.platform == "win32":
        return  # os.kill(pid, 0) is not a harmless probe on Windows
    try:
        candidates = list(Path(tempfile.gettempdir()).glob("toolkit_*_*"))
    except OSError:
        return
    for d in candidates:
        m = re.fullmatch(r"toolkit_(\d+)_[0-9a-f]{12}", d.name)
        if not m or d == DOWNLOAD_DIR:
            continue
        try:
            if d.is_symlink() or d.stat().st_uid != os.getuid():
                continue
            os.kill(int(m.group(1)), 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            continue

def _cleanup_on_exit():
    import shutil
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

atexit.register(_cleanup_on_exit)

# Simple rate limiting for /api/download
_download_timestamps: list = []
_DOWNLOAD_RATE_LIMIT = 12
_DOWNLOAD_RATE_WINDOW = 10.0
_rate_lock = threading.Lock()

def _check_download_rate() -> bool:
    global _download_timestamps
    now = time.time()
    with _rate_lock:
        _download_timestamps = [t for t in _download_timestamps if now - t < _DOWNLOAD_RATE_WINDOW]
        if len(_download_timestamps) >= _DOWNLOAD_RATE_LIMIT:
            return False
        _download_timestamps.append(now)
        return True


# yt-dlp ships date-stamped releases (2026.07.04). YouTube breaks older ones
# within weeks, and the failure looks like a missing video rather than a stale
# engine, so extraction errors get checked against this.
_YTDLP_STALE_DAYS = 45

# yt-dlp is imported where it is used, not at the top: it is a quarter of this
# module's import time, and every file command (sdexe pdf …, each MCP tool
# call) imports this module without ever downloading anything.

def _ytdlp_is_stale() -> bool:
    try:
        from yt_dlp.version import __version__ as ytdlp_version
        parts = ytdlp_version.split(".")[:3]
        released = datetime(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return False
    return (datetime.now() - released).days > _YTDLP_STALE_DAYS


# yt-dlp writes colored output, so its exception text carries ANSI escapes that
# render as literal "[0;31m" noise in the browser.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _clean_error(msg: str) -> str:
    text = _ANSI_RE.sub("", msg or "").strip()
    # yt-dlp prefixes its own messages, which means nothing to a user.
    for prefix in ("ERROR: ", "error: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    # Drop the "[youtube:tab] dQw4w9WgXcQ: " extractor tag.
    text = re.sub(r"^\[[a-z0-9:_.-]+\]\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"^[A-Za-z0-9_-]{6,20}:\s*", "", text)
    # Drop the trailing "(caused by ...)" chain.
    text = re.sub(r"\s*\(caused by .*$", "", text, flags=re.DOTALL)
    return text.strip()


def _friendly_download_error(raw: str, cancelled: bool = False, cli: bool = False) -> str:
    """Map a download failure to a message safe and useful to show a user.

    The raw text is logged for the operator. It is never returned as-is: it
    carries ANSI escapes, internal URLs, and yt-dlp argument advice.
    cli=True words the remedies for the terminal instead of the web UI.
    """
    err = _clean_error(raw)
    low = err.lower()
    logger.error("download failed: %s", err[:2000])

    if cancelled or "cancelled by user" in low:
        return "Download cancelled."
    # "Sign in to confirm your age" must not fall into the bot-check branch.
    if "your age" in low or "age-restricted" in low or "age restricted" in low or "inappropriate for some users" in low:
        if cli:
            return "Age-restricted. Sign in to YouTube in your browser, then retry with --cookies-from-browser chrome."
        return "Age-restricted. Sign in to download."
    if "sign in to confirm" in low or "not a bot" in low or "confirm you" in low:
        if cli:
            return ("YouTube is asking this machine to confirm it is not a bot. Sign in to "
                    "YouTube in your browser, then retry with --cookies-from-browser chrome "
                    "(or safari, firefox, brave, edge).")
        return ("YouTube is asking this machine to confirm it is not a bot. "
                "Sign in to YouTube in your browser, then try again shortly.")
    if "drm" in low:
        return "This video is DRM protected, so it cannot be downloaded."
    # Before the "not available" and "video unavailable" branches: YouTube's
    # "The uploader has not made this video available in your country" and
    # yt-dlp's "not available from your location due to geo restriction".
    if ("available in your country" in low or "geo-restricted" in low
            or "geo restriction" in low or "from your location" in low):
        return "Not available in your country (geo-restricted)."
    if "this video is not available" in low or "video is not available" in low:
        # Distinct from "Video unavailable". YouTube returns this for DRM
        # protected and licence-restricted titles that still play in a browser.
        return ("This video cannot be downloaded. It is usually DRM protected or "
                "licence restricted, even though it plays in a browser.")
    if "private" in low and "video" in low:
        return "This video is private."
    if "members-only" in low or "members only" in low or "join this channel" in low:
        return "Members-only video. An eligible channel membership is required."
    if "age" in low and any(w in low for w in ("restrict", "confirm", "gate")):
        if cli:
            return "Age-restricted. Sign in to YouTube in your browser, then retry with --cookies-from-browser chrome."
        return "Age-restricted. Sign in to download."
    if "premieres in" in low or "live event will begin" in low or "not started" in low:
        return "This has not premiered yet."
    if "429" in err or "rate limit" in low or "too many requests" in low:
        return "YouTube is rate limiting this machine. Wait a few minutes, then try again."
    if "copyright" in low or "blocked" in low:
        return "Blocked due to copyright."
    if "ffmpeg" in low and ("not found" in low or "no such file" in low):
        return "ffmpeg not found. Run `sdexe` once to install it."
    if ("video unavailable" in low or "unable to extract" in low
            or "requested format is not available" in low
            or "player response" in low or "nsig" in low):
        if _ytdlp_is_stale():
            fix = "Run `sdexe update`" if cli else "Update it in Settings"
            return ("Could not read this video. The downloader engine is out of date, "
                    f"which is the usual cause. {fix}, then try again.")
        return "Video unavailable or deleted."
    if any(w in low for w in ("timed out", "timeout", "connection", "network", "resolve")):
        return "Network problem while downloading. Check your connection and try again."
    if "unable to download api page" in low or "http error 40" in low:
        return "YouTube refused that request. The link may be private, removed, or region locked."
    if "does not exist" in low or "not found" in low:
        return "That link could not be found."

    # Unrecognized. Show a short, cleaned first line rather than a raw dump.
    first_line = err.splitlines()[0] if err else ""
    if len(first_line) > 160:
        first_line = first_line[:157] + "..."
    return first_line or "Download failed."


CONFIG_DIR = Path.home() / ".config" / "sdexe"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Held across a read-change-write of config.json or history.json. Three
# playlist workers finishing together each add a history entry.
_state_lock = threading.RLock()


def _write_json(path: Path, data) -> None:
    """Write to a temporary file beside `path`, then rename over it. Writing
    in place leaves the file empty for a moment; a reader in that moment saw
    "no settings" / "no history" and the next save made that permanent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = Path(os.path.realpath(path))  # keep a symlinked config a symlink
    text = json.dumps(data, indent=2)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text)
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except PermissionError:
        # Windows refuses the rename while another process has the file open.
        tmp.unlink(missing_ok=True)
        target.write_text(text)
    except OSError:
        tmp.unlink(missing_ok=True)  # a full disk: leave the old file as it was
        raise


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            # A hand-edited file holding a list or null is as unusable as a corrupt one.
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}

def save_config(data):
    _write_json(CONFIG_FILE, data)

HISTORY_FILE = CONFIG_DIR / "history.json"

def load_history():
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text())
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            pass
    return []

def save_history(items):
    _write_json(HISTORY_FILE, items)

# Stores progress and file info keyed by download ID
downloads = {}
_downloads_lock = threading.Lock()

# Stores transcription progress and results keyed by transcription ID
transcriptions = {}
_transcriptions_lock = threading.Lock()


# Linux filesystems (ext4, btrfs, xfs) cap a file name at 255 bytes, so a
# 100-character Japanese title (300 bytes) cannot be created there. macOS and
# Windows count characters instead and take it as it is.
def _name_byte_limit():
    import sys
    return None if sys.platform in ("darwin", "win32") else 230  # room for ".webm" and " (2)"


def _safe_filename(name: str, default: str = "download", max_len: int = 200,
                   max_bytes: int | None = -1) -> str:
    """Sanitize an arbitrary string (e.g. a video title) for use as a download
    filename: drop directory components, null/control bytes, and reserved chars,
    and cap the length so it can't break the filesystem or path-traverse."""
    import re as _re
    name = (name or "").replace("\x00", "")
    name = name.replace("\\", "/").split("/")[-1]          # strip any path / traversal
    name = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        return default
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .") or default
    if max_bytes == -1:
        max_bytes = _name_byte_limit()
    raw = name.encode("utf-8")
    if max_bytes and len(raw) > max_bytes:
        name = raw[:max_bytes].decode("utf-8", "ignore").rstrip(" .") or default
    return name


def cleanup_old_files(max_age_seconds=3600):
    """Delete downloaded files older than max_age_seconds and prune stale dict entries."""
    now = time.time()
    # A job that is still running needs its files however old they are: the
    # thumbnail written at the start of a two-hour download, the audio a long
    # transcription goes back to for speaker labels.
    with _downloads_lock:
        live = [k for k, v in downloads.items() if v.get("status") not in ("done", "error")]
    live += [k for k, v in list(transcriptions.items()) if v.get("status") not in ("done", "error")]
    live = tuple(live)
    try:
        files = list(DOWNLOAD_DIR.iterdir())
    except OSError:
        files = []
    for f in files:
        # Other downloads create and delete .part files, thumbnails and
        # fragments while this runs, so any file can vanish between checks.
        try:
            if live and f.name.startswith(live):
                continue
            if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
                f.unlink(missing_ok=True)
        except OSError:
            continue
    with _downloads_lock:
        # Aged from when the job ended, not when it began: a download that
        # ran for over an hour was dropped before its file could be fetched.
        stale = [
            k for k, v in list(downloads.items())
            if v.get("status") in ("done", "error")
            and ((v.get("filename") and not (DOWNLOAD_DIR / v["filename"]).exists())
                 or now - (v.get("finished") or v.get("created", now)) > max_age_seconds)
        ]
        for k in stale:
            downloads.pop(k, None)
    # Finished transcriptions hold the full segment payload, so drop them once
    # the client has had time to fetch the result.
    for k, v in list(transcriptions.items()):
        if v.get("status") in ("done", "error") and \
                now - (v.get("finished") or v.get("created", now)) > max_age_seconds:
            transcriptions.pop(k, None)


def _validate_folder(path: str):
    """Return (resolved_path_str, error_str). error_str is empty on success."""
    if not path:
        return "", ""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return "", f"Directory does not exist: {p}"
    if not p.is_dir():
        return "", f"Path is not a directory: {p}"
    sensitive = {Path("/"), Path("/etc"), Path("/usr"), Path("/bin"),
                 Path("/sys"), Path("/dev"), Path("/proc")}
    if p in sensitive:
        return "", f"Cannot use system directory: {p}"
    return str(p), ""


def set_file_metadata(filepath, metadata):
    """Embed metadata into a media file using ffmpeg."""
    allowed_keys = {"title", "artist", "album", "date", "comment"}
    args = []
    for key, value in metadata.items():
        if key not in allowed_keys:
            continue
        if value and value.strip():
            args.extend(["-metadata", f"{key}={value.strip()}"])
    if not args:
        return
    exe = tools.ffmpeg_path()
    if not exe:
        return
    tmp = filepath.parent / f"_meta_{filepath.name}"
    cmd = [exe, "-y", "-i", str(filepath), "-codec", "copy", "-map", "0"] + args + [str(tmp)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0:
            tmp.replace(filepath)
        else:
            tmp.unlink(missing_ok=True)
    except Exception:
        tmp.unlink(missing_ok=True)


# ── Page Routes ──

# ── Extra tool modules ──
# Each is a Blueprint that owns its own routes (routes_*.py) and pure helpers
# (tools_*.py), keeping this file from growing further. A module that fails to
# import only disables its own tools; the rest of the app keeps working.
def _register_extra_blueprints():
    import importlib
    for mod, attr in (("routes_pdf2", "pdf2_bp"), ("routes_images2", "images2_bp"),
                      ("routes_av2", "av2_bp"), ("routes_convert2", "convert2_bp")):
        try:
            m = importlib.import_module(f"sdexe.{mod}")
            app.register_blueprint(getattr(m, attr))
        except Exception as e:  # noqa: BLE001
            logging.getLogger("sdexe").warning("tool module %s not loaded: %s", mod, e)

_register_extra_blueprints()


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/media")
def media():
    return render_template("media.html")


@app.route("/pdf")
def pdf_page():
    return render_template("pdf.html")


@app.route("/images")
def images_page():
    return render_template("images.html")


@app.route("/convert")
def convert_page():
    return render_template("convert.html")

@app.route("/av")
def av_page():
    return render_template("av.html")

@app.route("/text")
def text_page():
    return render_template("text.html")

@app.route("/transcribe")
def transcribe_page():
    whisper_ok, diarize_ok = tools._check_transcribe_deps()
    return render_template("transcribe.html",
                           whisper_available=whisper_ok,
                           diarize_available=diarize_ok)

@app.route("/about")
def about_page():
    return render_template("about.html")


@app.route("/settings")
def settings_page():
    import sys as _sys
    ffmpeg_ver = tools.ffmpeg_version()
    resolved = tools.ffmpeg_path()
    if ffmpeg_ver and resolved and resolved != shutil.which("ffmpeg"):
        ffmpeg_ver = f"{ffmpeg_ver} (bundled)"
    info = {
        "python_ver": f"{_sys.version_info.major}.{_sys.version_info.minor}.{_sys.version_info.micro}",
        "ffmpeg_ver": ffmpeg_ver or "not found",
        "ytdlp_ver": "unknown",
        "tool_count": sum(1 for r in app.url_map.iter_rules() if r.endpoint != "static"),
        "config_dir": str(CONFIG_DIR),
        "ytdlp_stale": _ytdlp_is_stale(),
    }
    try:
        from yt_dlp.version import __version__ as ytdlp_version
        info["ytdlp_ver"] = ytdlp_version
    except Exception:
        pass
    return render_template("settings.html", info=info)


# ── Config API ──

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def set_config_route():
    updates = _body()
    # Every download reads these two back as text; a null or a number saved
    # here would fail each one at the auto-save step.
    for key in ("output_folder", "output_template"):
        if key in updates and not isinstance(updates[key], str):
            return jsonify({"error": f"{key} must be text"}), 400
    if "output_folder" in updates and updates["output_folder"]:
        resolved, err = _validate_folder(updates["output_folder"])
        if err:
            return jsonify({"error": err}), 400
        updates["output_folder"] = resolved
    if "open_browser" in updates and not isinstance(updates["open_browser"], bool):
        return jsonify({"error": "open_browser must be true or false"}), 400
    with _state_lock:
        cfg = load_config()
        cfg.update(updates)
        save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify(load_history())

@app.route("/api/history", methods=["POST"])
def add_history():
    item = _body()
    if not item.get("title"):
        return jsonify({"error": "title required"}), 400
    with _state_lock:
        items = load_history()
        items.insert(0, {
            "title": str(item.get("title", ""))[:500],
            "format": str(item.get("format", ""))[:20],
            "id": str(item.get("id", ""))[:100],
            "url": str(item.get("url", ""))[:2000],
            "ts": time.time(),
        })
        items = items[:50]
        save_history(items)
    return jsonify({"ok": True})


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    cfg = load_config()
    folder = str(cfg.get("output_folder") or "").strip()
    if not folder:
        return jsonify({"error": "No output folder configured"}), 400
    path = Path(folder).expanduser()
    if not path.is_dir():
        return jsonify({"error": "Folder not found"}), 404
    import subprocess, sys as _sys
    if _sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif _sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", str(path)])
    elif _sys.platform == "win32":
        subprocess.Popen(["explorer", str(path)])
    return jsonify({"ok": True})


@app.route("/api/open-file", methods=["POST"])
def open_file():
    path = _body().get("path")
    path = path.strip() if isinstance(path, str) else ""
    if not path:
        return jsonify({"error": "No path provided"}), 400
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return jsonify({"error": "File not found"}), 404
    # Only allow opening files in the configured output folder or temp download dir
    cfg = load_config()
    output_dir = str(cfg.get("output_folder") or "").strip()
    allowed = [DOWNLOAD_DIR.resolve()]
    if output_dir:
        allowed.append(Path(output_dir).expanduser().resolve())
    # is_relative_to compares path segments. A plain string prefix would also
    # accept a sibling directory such as "<output>-private".
    if not any(p.is_relative_to(d) for d in allowed):
        return jsonify({"error": "Access denied"}), 403
    import sys as _sys
    if _sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    elif _sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", str(p)])
    elif _sys.platform == "win32":
        subprocess.Popen(["explorer", str(p)])
    return jsonify({"ok": True})


@app.route("/api/browse-folder", methods=["POST"])
def browse_folder():
    import sys as _sys
    try:
        if _sys.platform == "darwin":
            result = subprocess.run(
                ["osascript", "-e", "POSIX path of (choose folder)"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return jsonify({"cancelled": True})
            path = result.stdout.strip()
        elif _sys.platform.startswith("linux"):
            try:
                result = subprocess.run(
                    ["zenity", "--file-selection", "--directory", "--title=Choose folder"],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode != 0:
                    return jsonify({"cancelled": True})
                path = result.stdout.strip()
            except FileNotFoundError:
                result = subprocess.run(
                    ["kdialog", "--getexistingdirectory", str(Path.home())],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode != 0:
                    return jsonify({"cancelled": True})
                path = result.stdout.strip()
        elif _sys.platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
                "$f.ShowDialog() | Out-Null;"
                "Write-Output $f.SelectedPath"
            )
            result = subprocess.run(
                ["powershell", "-Command", script],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return jsonify({"cancelled": True})
            path = result.stdout.strip()
        else:
            return jsonify({"error": "Native folder picker not supported on this platform"}), 501

        if not path:
            return jsonify({"cancelled": True})

        resolved, err = _validate_folder(path)
        if err:
            return jsonify({"error": err}), 400
        return jsonify({"path": resolved})
    except subprocess.TimeoutExpired:
        return jsonify({"cancelled": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _pip():
    """pip for whatever environment sdexe is running in (the installer's
    private venv at ~/.sdexe, a pipx venv, or any other venv)."""
    import sys
    return [sys.executable, "-m", "pip"]


def _pip_install(*pkgs, timeout=300):
    """Upgrade packages into sdexe's own environment. Returns (ok, output)."""
    import sys
    # --no-cache-dir: pip otherwise reuses a cached index page for a while
    # and misses a release published minutes ago.
    cmd = _pip() + ["install", "--upgrade", "--no-cache-dir", "--no-warn-script-location", "-q"]
    # Outside a venv, pip needs --user (and Homebrew/Debian Python refuses
    # even that without the override flag).
    if sys.prefix == sys.base_prefix:
        cmd += ["--user", "--break-system-packages"]
    cmd += list(pkgs)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "Update timed out"
    except FileNotFoundError:
        return False, "pip is not available in this Python environment"
    out = (r.stdout + "\n" + r.stderr).strip()
    return r.returncode == 0, out


def self_update(engine_only=False):
    """Upgrade sdexe (and always yt-dlp, which YouTube breaks every few weeks).

    Returns (ok, message). Used by `sdexe update` and the Settings page.
    """
    if engine_only:
        ok, out = _pip_install("yt-dlp[default]")
        return ok, ("Downloader engine updated. Restart sdexe to use it." if ok else out)

    latest = _latest_pypi_version()
    ok, out = _pip_install("sdexe", "yt-dlp[default]")
    if not ok:
        return False, out or "Update failed"
    new_ver = _installed_version()
    if latest and new_ver and new_ver != latest:
        return True, (f"sdexe {latest} was just published and PyPI is still propagating it. "
                      f"You have {new_ver}. Try again in a minute.")
    if new_ver == __version__:
        return True, f"Already on the latest version ({__version__}). Downloader engine refreshed."
    return True, f"Updated to sdexe {new_ver or 'latest'}. Restart sdexe to apply."


def _latest_pypi_version():
    import urllib.request
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/sdexe/json", timeout=5) as r:
            return json.loads(r.read())["info"]["version"]
    except Exception:
        return ""


def _installed_version():
    try:
        out = subprocess.run(_pip() + ["show", "sdexe"], capture_output=True, text=True, timeout=30).stdout
        return next((l.split(":", 1)[1].strip() for l in out.splitlines() if l.lower().startswith("version:")), "")
    except Exception:
        return ""


@app.route("/api/update", methods=["POST"])
def run_update():
    ok, msg = self_update()
    return (jsonify({"ok": True, "output": msg}), 200) if ok else (jsonify({"error": msg}), 500)


@app.route("/api/update-ytdlp", methods=["POST"])
def update_ytdlp():
    """Upgrade only yt-dlp. This is the fix for most 'Video unavailable' errors."""
    ok, msg = self_update(engine_only=True)
    return (jsonify({"ok": True, "output": msg}), 200) if ok else (jsonify({"error": msg}), 500)


@app.route("/api/install-ffmpeg", methods=["POST"])
def install_ffmpeg_route():
    """Attempt to install a full system ffmpeg via the platform package manager."""
    ok, msg = install_ffmpeg()
    return jsonify({"ok": ok, "message": msg, "ffmpeg": tools.ffmpeg_available()}), (200 if ok else 500)


@app.route("/api/deps", methods=["GET"])
def deps():
    """Report availability of optional runtime dependencies for the web UI."""
    whisper_ok, diarize_ok = tools._check_transcribe_deps()
    ytdlp_ver = "unknown"
    try:
        from yt_dlp.version import __version__ as ytdlp_ver
    except Exception:
        pass
    resolved = tools.ffmpeg_path()
    system = shutil.which("ffmpeg")
    return jsonify({
        "ffmpeg": resolved is not None,
        "ffmpeg_version": tools.ffmpeg_version(),
        # True when we fell back to the bundled binary (no system ffmpeg, or it's broken)
        "ffmpeg_bundled": bool(resolved) and resolved != system,
        "ffprobe": tools.ffprobe_available(),
        "ytdlp_version": ytdlp_ver,
        "ytdlp_stale": _ytdlp_is_stale(),
        "js_runtime": media_opts.js_runtime_label(),
        "ejs": media_opts.ejs_installed(),
        "whisper": whisper_ok,
        "diarize": diarize_ok,
    })


def _ffmpeg_missing_response():
    """Structured 503 telling the UI ffmpeg is unavailable (so it can offer to install)."""
    return jsonify({
        "error": "ffmpeg is required for this tool but isn't available.",
        "code": "ffmpeg_missing",
    }), 503


# ── Media API ──

def _summarize_formats(data):
    """Collapse yt-dlp's format list into one row per resolution and a short
    list of native audio streams, for the download picker on the media page.

    Video rows keep only the highest-bitrate stream at each height, whatever
    its codec, so 4K/2K usually come back as WebM (VP9/AV1) and 1080p and
    below as MP4. Sizes add the best audio stream so they reflect the merged
    file the user actually gets.
    """
    formats = data.get("formats") or []
    if not formats:
        return {"video": [], "audio": []}

    def size_of(f):
        return f.get("filesize") or f.get("filesize_approx") or 0

    def rate_of(f):
        return f.get("tbr") or f.get("vbr") or f.get("abr") or 0

    audio_only = [f for f in formats
                  if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
                  and f.get("format_id") and not f.get("has_drm")]
    audio_only.sort(key=lambda f: (f.get("abr") or rate_of(f), size_of(f)), reverse=True)
    best_audio = audio_only[0] if audio_only else None
    best_audio_size = size_of(best_audio) if best_audio else 0

    duration = data.get("duration") or 0

    def is_hls(f):
        return "m3u8" in (f.get("protocol") or "")

    def video_rank(f):
        # Direct downloads with a known size beat HLS streams. YouTube's HLS
        # variants report a higher bitrate but no size, and merge slower.
        return (bool(size_of(f)), not is_hls(f), rate_of(f), size_of(f))

    by_height = {}
    for f in formats:
        if f.get("vcodec") in (None, "none") or not f.get("format_id") or f.get("has_drm"):
            continue
        h = f.get("height")
        if not h:
            continue
        # Storyboards and other image-only "formats" have no bitrate.
        if not rate_of(f) and not size_of(f):
            continue
        cur = by_height.get(h)
        if cur is None or video_rank(f) > video_rank(cur):
            by_height[h] = f

    video_rows = []
    for h in sorted(by_height, reverse=True):
        f = by_height[h]
        if h >= 2160:
            label = "4K"
        elif h >= 1440:
            label = "2K"
        else:
            label = f"{h}p"
        ext = (f.get("ext") or "mp4").lower()
        merged = f.get("acodec") not in (None, "none")
        approx = False
        vsize = size_of(f)
        if not vsize and rate_of(f) and duration:
            # No size reported (HLS, live-ish): estimate from bitrate.
            vsize = int(rate_of(f) * 125 * duration)
            approx = True
        size = vsize + (0 if merged else best_audio_size) if vsize else 0
        video_rows.append({
            "label": label,
            "height": h,
            "format_id": f["format_id"],
            "ext": "mp4" if ext in ("mp4", "m4v", "mov") else ("webm" if ext in ("webm", "mkv") else ext),
            "size": size or None,
            "approx": approx,
            "fps": int(round(f.get("fps") or 0)) or None,
        })

    audio_rows = []
    seen = set()
    for f in audio_only:
        ext = (f.get("ext") or "").lower()
        # FFmpegExtractAudio with preferredcodec "best" remuxes without
        # re-encoding, so these are the containers the user ends up with.
        out_ext = "m4a" if ext in ("m4a", "mp4") else ("opus" if ext in ("webm", "opus", "ogg") else ext)
        abr = int(round(f.get("abr") or rate_of(f) or 0))
        key = (out_ext, abr // 16)
        if key in seen or not abr:
            continue
        seen.add(key)
        audio_rows.append({
            "label": f"{abr} kbps",
            "abr": abr,
            "format_id": f["format_id"],
            "ext": out_ext,
            "size": size_of(f) or None,
        })
        if len(audio_rows) >= 4:
            break

    return {"video": video_rows, "audio": audio_rows}


@app.route("/api/info", methods=["POST"])
def info():
    url = _body().get("url")
    url = url.strip() if isinstance(url, str) else ""
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Only http and https URLs are supported"}), 400

    # Normalise YouTube video+list URLs to pure playlist URLs.
    # Mixes (RD...), Watch Later (WL), and Liked (LL) are not viewable as
    # standalone playlists, so for those keep the single video instead.
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com") and "list" in parse_qs(parsed.query):
        qs = parse_qs(parsed.query)
        list_id = qs["list"][0]
        if list_id.startswith(("RD", "WL", "LL")):
            if "v" in qs:
                url = urlunparse(parsed._replace(query=urlencode({"v": qs["v"][0]})))
        else:
            url = urlunparse(parsed._replace(path="/playlist", query=urlencode({"list": list_id})))

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "socket_timeout": 12,
        "js_runtimes": media_opts.js_runtimes(),
    }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({
            "error": _friendly_download_error(str(e)),
            "ytdlp_stale": _ytdlp_is_stale(),
        }), 400

    entries_raw = data.get("entries")
    if entries_raw is not None:
        entries = []
        skipped = 0
        for entry in entries_raw:
            if not entry:
                continue
            # Flat playlist extraction still lists members the viewer cannot
            # fetch. Downloading one fails with "Video unavailable", so drop
            # them here and report the count instead.
            title_raw = entry.get("title") or ""
            availability = entry.get("availability")
            if title_raw in ("[Private video]", "[Deleted video]", "[Unavailable video]") or \
                    availability in ("private", "needs_auth", "subscriber_only", "premium_only"):
                skipped += 1
                continue
            vid = entry.get("id", "")
            thumb = entry.get("thumbnail") or ""
            if not thumb and entry.get("thumbnails"):
                thumb = entry["thumbnails"][0].get("url", "")
            if not thumb and vid and ("youtube" in url or "youtu.be" in url):
                thumb = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
            entry_url = entry.get("webpage_url") or entry.get("url") or ""
            if entry_url and not entry_url.startswith("http"):
                entry_url = f"https://www.youtube.com/watch?v={entry_url}"
            entries.append({
                "title": entry.get("title") or "Unknown",
                "url": entry_url,
                "duration": entry.get("duration"),
                "id": vid,
                "thumbnail": thumb,
            })
            if len(entries) >= 500:
                break
        return jsonify({
            "type": "playlist",
            "title": data.get("title") or "Playlist",
            "uploader": data.get("uploader") or data.get("channel"),
            "count": len(entries),
            "skipped": skipped,
            "entries": entries,
        })

    vid = data.get("id", "")
    thumbnail = data.get("thumbnail") or ""
    if not thumbnail and data.get("thumbnails"):
        thumbnail = data["thumbnails"][0].get("url", "")
    if not thumbnail and vid and ("youtube" in url or "youtu.be" in url):
        thumbnail = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    upload_date = data.get("upload_date") or ""
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return jsonify({
        "type": "video",
        "title": data.get("title"),
        "thumbnail": thumbnail,
        "duration": data.get("duration"),
        "uploader": data.get("uploader") or data.get("channel"),
        "description": data.get("description") or "",
        "upload_date": upload_date,
        "url": data.get("webpage_url") or url,
        "formats": _summarize_formats(data),
    })


@app.route("/api/download", methods=["POST"])
def download():
    body = _body()
    # A null or a number where text belongs (a hand-written client) is a bad
    # request, not a crash.
    url = body.get("url")
    url = url.strip() if isinstance(url, str) else ""
    fmt = str(body.get("format") or "mp3")
    quality = str(body.get("quality") or "best")
    metadata = body.get("metadata")
    metadata = {k: v for k, v in metadata.items() if isinstance(v, str)} if isinstance(metadata, dict) else {}
    subtitles = bool(body.get("subtitles", False))
    clip_start = body.get("clip_start")
    clip_end = body.get("clip_end")
    for clip in (clip_start, clip_end):
        if clip is not None and (isinstance(clip, bool) or not isinstance(clip, (int, float))):
            return jsonify({"error": "Clip times must be numbers of seconds"}), 400
    # A specific stream picked from the format table. "ext" is the container
    # the row promised (mp4/webm for video, m4a/opus for audio).
    format_id = str(body.get("format_id") or "").strip()
    picked_ext = str(body.get("ext") or "").strip().lower()

    if not url:
        return jsonify({"error": "No URL provided"}), 400
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "Only http and https URLs are supported"}), 400
    if format_id and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", format_id):
        return jsonify({"error": "Invalid format id"}), 400

    if not _check_download_rate():
        return jsonify({"error": "Too many downloads. Slow down a bit."}), 429

    cleanup_old_files()

    dl_id = str(uuid.uuid4())
    with _downloads_lock:
        downloads[dl_id] = {
            "progress": 0,
            "status": "starting",
            "filename": None,
            "download_name": None,
            "error": None,
            "detail": "",
            "pp_step": 0,
            "auto_saved": False,
            "saved_path": None,
            "cancelled": False,
            "created": time.time(),
            "finished": None,
        }

    def finish(status, error=None):
        d = downloads[dl_id]
        d["finished"] = time.time()  # before the status: pruning ages a finished job from here
        d["error"] = error
        d["status"] = status

    PP_NAMES = {
        "FFmpegExtractAudio": "Extracting audio" if fmt == "audio" else f"Converting to {fmt.upper()}",
        "FFmpegMerger": "Merging video + audio",
        "FFmpegVideoConvertor": "Converting video",
        "FFmpegMetadata": "Writing metadata",
        "FFmpegFixupM3u8": "Fixing stream",
        "FFmpegFixupM4a": "Fixing audio container",
        "FFmpegFixupStretched": "Fixing aspect ratio",
        "FFmpegFixupTimestamp": "Fixing timestamps",
        "FFmpegFixupDuplicateMoov": "Fixing MP4 structure",
        "FFmpegEmbedSubtitle": "Embedding subtitles",
        "EmbedThumbnail": "Embedding thumbnail",
        "MoveFiles": "Finalizing",
    }

    def progress_hook(d):
        if downloads[dl_id].get("cancelled"):
            raise Exception("Cancelled by user")
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            speed = d.get("speed")
            eta = d.get("eta")
            if total > 0:
                downloads[dl_id]["progress"] = round(downloaded / total * 100, 1)
            detail_parts = []
            if speed:
                if speed >= 1_048_576:
                    detail_parts.append(f"{speed / 1_048_576:.1f} MB/s")
                else:
                    detail_parts.append(f"{speed / 1024:.0f} KB/s")
            if eta is not None and eta > 0:
                mins, secs = divmod(int(eta), 60)
                detail_parts.append(f"{mins}:{secs:02d} left" if mins else f"{secs}s left")
            downloads[dl_id]["detail"] = " · ".join(detail_parts)
            downloads[dl_id]["status"] = "downloading"
        elif d["status"] == "finished":
            downloads[dl_id]["progress"] = 100
            downloads[dl_id]["status"] = "processing"
            downloads[dl_id]["detail"] = ""

    def postprocessor_hook(d):
        if downloads[dl_id].get("cancelled"):
            raise Exception("Cancelled by user")
        if d["status"] == "started":
            pp_name = d.get("postprocessor", "")
            downloads[dl_id]["pp_step"] += 1
            # yt-dlp reports "ExtractAudio", not "FFmpegExtractAudio".
            friendly = PP_NAMES.get(pp_name) or PP_NAMES.get("FFmpeg" + pp_name, pp_name)
            downloads[dl_id]["status"] = "processing"
            downloads[dl_id]["detail"] = friendly

    outtmpl = str(DOWNLOAD_DIR / f"{dl_id}.%(ext)s")
    common_hooks = {
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,  # the hooks above still fire; this only stops terminal spam
        "noplaylist": True,
        "writethumbnail": True,
        "js_runtimes": media_opts.js_runtimes(),
        "concurrent_fragment_downloads": 4,
        "retries": 5,
        "fragment_retries": 5,
    }
    # Use the resolved ffmpeg (system, or the bundled fallback) for post-processing,
    # so audio/video downloads work even without a working system ffmpeg.
    _ffmpeg = tools.ffmpeg_path()
    if _ffmpeg:
        common_hooks["ffmpeg_location"] = _ffmpeg

    if format_id and fmt == "video":
        # Exact stream from the picker, merged with the best audio. Keep the
        # container the picker showed (WebM for VP9/AV1, MP4 for H.264) so
        # there is no re-encode.
        container = "webm" if picked_ext == "webm" else "mp4"
        video_postprocessors = []
        if container == "mp4":
            video_postprocessors.append({"key": "EmbedThumbnail"})
        if subtitles:
            video_postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
        ydl_opts = {
            "format": f"{format_id}+bestaudio/{format_id}/best",
            "merge_output_format": container,
            "outtmpl": outtmpl,
            "postprocessors": video_postprocessors,
            **({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en"]} if subtitles else {}),
            **common_hooks,
        }
    elif format_id and fmt == "audio":
        # Native audio stream, remuxed (not re-encoded) into m4a/opus.
        ydl_opts = {
            "format": f"{format_id}/bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "best"},
                {"key": "EmbedThumbnail"},
            ],
            **common_hooks,
        }
    else:
        height = {"1080p": 1080, "720p": 720, "480p": 480}.get(quality) if fmt == "mp4" else None
        ydl_opts = {
            **media_opts.build_ydl_opts(
                fmt if fmt in ("mp4", "flac", "wav") else "mp3",
                height=height,
                bitrate=quality,
                subtitles=subtitles and fmt == "mp4",
                prefer_fps=True,
            ),
            "outtmpl": outtmpl,
            **common_hooks,
        }

    media_opts.apply_clip(ydl_opts, clip_start, clip_end)

    def do_download():
        try:
            import yt_dlp
            for attempt in range(1, media_opts.ATTEMPTS + 1):
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        vid_info = ydl.extract_info(url, download=True)
                    break
                except Exception as e:
                    msg = str(e)
                    if downloads[dl_id].get("cancelled") or attempt == media_opts.ATTEMPTS:
                        raise
                    if media_opts.is_thumbnail_failure(msg):
                        # Cover art is a nicety; retry without it.
                        media_opts.without_thumbnail(ydl_opts)
                    elif media_opts.is_retryable(msg):
                        for f in DOWNLOAD_DIR.glob(f"{dl_id}.*"):
                            f.unlink(missing_ok=True)
                        time.sleep(attempt)
                    else:
                        raise
                    downloads[dl_id].update(status="downloading", progress=0, pp_step=0,
                                            detail=f"Retrying ({attempt + 1}/{media_opts.ATTEMPTS})")

            # Find the output file (skip leftover thumbnail images)
            thumb_exts = {".jpg", ".jpeg", ".png", ".webp"}
            for f in DOWNLOAD_DIR.iterdir():
                if f.stem == dl_id and f.suffix.lower() not in thumb_exts:
                    downloads[dl_id]["filename"] = f.name
                    title = metadata.get("title") or vid_info.get("title") or "download"
                    artist = metadata.get("artist") or vid_info.get("uploader") or ""
                    album = metadata.get("album") or vid_info.get("album") or ""
                    uploader = vid_info.get("uploader") or vid_info.get("channel") or ""
                    ext = f.suffix.lstrip(".")
                    tmpl = load_config().get("output_template", "") or ""
                    if tmpl:
                        try:
                            base_name = str(tmpl).format(title=title, artist=artist, album=album, uploader=uploader)
                        except Exception:
                            # "{}" raises IndexError, "{title.x}" AttributeError: a bad
                            # template must not fail a download that already finished.
                            base_name = title
                    else:
                        base_name = title
                    base_name = _safe_filename(base_name, "download")
                    downloads[dl_id]["download_name"] = f"{base_name}.{ext}"
                    break

            # Clean up leftover thumbnail files
            for f in DOWNLOAD_DIR.iterdir():
                if f.stem == dl_id and f.suffix.lower() in thumb_exts:
                    f.unlink(missing_ok=True)

            # Verify an actual output file was produced before continuing
            out_name = downloads[dl_id].get("filename")
            out_path_check = DOWNLOAD_DIR / out_name if out_name else None
            if not out_name or not out_path_check.exists() or out_path_check.stat().st_size == 0:
                finish("error", "Download finished but produced no output file.")
                return

            # Embed metadata if provided
            meta = {}
            if metadata.get("title"):
                meta["title"] = metadata["title"]
            if metadata.get("artist"):
                meta["artist"] = metadata["artist"]
            if metadata.get("album"):
                meta["album"] = metadata["album"]
            description = metadata.get("description") or vid_info.get("description") or ""
            if description:
                meta["comment"] = description
            upload_date = vid_info.get("upload_date") or ""
            if upload_date and len(upload_date) == 8:
                upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
            if upload_date:
                meta["date"] = upload_date
            if meta and downloads[dl_id].get("filename"):
                downloads[dl_id]["status"] = "metadata"
                filepath = DOWNLOAD_DIR / downloads[dl_id]["filename"]
                set_file_metadata(filepath, meta)

            if downloads[dl_id].get("cancelled"):
                raise Exception("Cancelled by user")

            # Auto-save to output folder if configured
            cfg = load_config()
            output_dir = str(cfg.get("output_folder") or "").strip()
            if output_dir and downloads[dl_id].get("filename"):
                output_path = Path(output_dir).expanduser()
                if output_path.is_dir():
                    import shutil as _shutil
                    dest = output_path / downloads[dl_id]["download_name"]
                    n = 2
                    while dest.exists():  # never overwrite another download with the same title
                        dest = output_path / f"{Path(downloads[dl_id]['download_name']).stem} ({n}){dest.suffix}"
                        n += 1
                    try:
                        _shutil.copy2(DOWNLOAD_DIR / downloads[dl_id]["filename"], dest)
                    except OSError as e:
                        # A read-only or full folder. The download itself is fine and
                        # still in the temp directory, so offer it there (Save File)
                        # instead of reporting a finished download as failed.
                        logger.warning("could not save to the output folder %s: %s", output_path, e)
                        try:
                            dest.unlink(missing_ok=True)
                        except OSError:
                            pass
                    else:
                        downloads[dl_id]["download_name"] = dest.name
                        downloads[dl_id]["auto_saved"] = True
                        downloads[dl_id]["saved_path"] = str(dest)

            downloads[dl_id]["progress"] = 100
            finish("done")
        except Exception as e:
            finish("error", _friendly_download_error(
                str(e), cancelled=bool(downloads[dl_id].get("cancelled"))
            ))
            # Nothing can fetch or resume these (a retry gets a new id), and a
            # cancelled 4K download would otherwise sit in /tmp for an hour.
            try:
                for f in DOWNLOAD_DIR.glob(f"{dl_id}.*"):
                    f.unlink(missing_ok=True)
            except OSError:
                pass

    thread = threading.Thread(target=do_download, daemon=True)
    thread.start()

    return jsonify({"id": dl_id})


@app.route("/api/progress/<dl_id>")
def progress(dl_id):
    def stream():
        start = time.time()
        while True:
            info = downloads.get(dl_id)
            if not info:
                yield f"data: {json.dumps({'error': 'Unknown download'})}\n\n"
                break

            # One snapshot for both the message and the exit test. Reading the
            # live dict twice let the worker finish in between: the stream
            # then closed without ever sending "done".
            info = dict(info)
            yield f"data: {json.dumps(info)}\n\n"

            if info.get("status") in ("done", "error", "cancelled"):
                break

            # Safety cap: never stream forever if a worker hangs without a
            # terminal status. (Client disconnects also end the generator.)
            if time.time() - start > 7200:
                break

            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/cancel/<dl_id>", methods=["POST"])
def cancel_download(dl_id):
    info = downloads.get(dl_id)
    if not info:
        return jsonify({"error": "Unknown download"}), 404
    info["cancelled"] = True
    return jsonify({"ok": True})


@app.route("/api/file/<dl_id>")
def file(dl_id):
    info = downloads.get(dl_id)
    if not info or not info.get("filename"):
        return jsonify({"error": "File not found"}), 404

    filepath = DOWNLOAD_DIR / info["filename"]
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    download_name = info.get("download_name") or info["filename"]
    return send_file(filepath, as_attachment=True, download_name=download_name)


@app.route("/api/batch-zip", methods=["POST"])
def batch_zip():
    ids = _body().get("ids")
    if not ids or not isinstance(ids, list):
        return jsonify({"error": "No IDs provided"}), 400

    # Built on disk and stored, not deflated: a playlist is gigabytes of
    # already-compressed media, which deflate cannot shrink and RAM should not hold.
    zip_file = tempfile.TemporaryFile(dir=DOWNLOAD_DIR)
    used = set()
    try:
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_STORED) as zf:
            for dl_id in ids:
                info = downloads.get(dl_id) if isinstance(dl_id, str) else None
                if not info or not info.get("filename"):
                    continue
                filepath = DOWNLOAD_DIR / info["filename"]
                if not filepath.exists():
                    continue
                arcname = info.get("download_name") or info["filename"]
                # Two videos with one title: both go in, the second as "name_2".
                zf.write(filepath, tools._unique_name(arcname, used))
    except Exception:
        zip_file.close()
        raise
    if not used:
        zip_file.close()
        return jsonify({"error": "Those downloads are no longer available. Download them again."}), 404

    size = zip_file.tell()
    zip_file.seek(0)
    resp = send_file(zip_file, as_attachment=True, download_name="downloads.zip",
                     mimetype="application/zip")
    resp.content_length = size
    return resp


# ── PDF API ──

@app.route("/api/pdf/merge", methods=["POST"])
def pdf_merge():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Need at least 2 PDF files"}), 400
    try:
        result = tools.merge_pdfs([f.stream for f in files])
        return send_file(io.BytesIO(result), as_attachment=True, download_name="merged.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/split", methods=["POST"])
def pdf_split():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    ranges_str = request.form.get("ranges", "").strip()
    try:
        parts = tools.split_pdf(f.stream, ranges_str)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if len(parts) == 1:
        name, data = parts[0]
        return send_file(io.BytesIO(data), as_attachment=True, download_name="split.pdf",
                         mimetype="application/pdf")
    else:
        zip_data = tools.create_zip(parts)
        return send_file(io.BytesIO(zip_data), as_attachment=True, download_name="split_pages.zip",
                         mimetype="application/zip")


@app.route("/api/pdf/images-to-pdf", methods=["POST"])
def images_to_pdf():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No images provided"}), 400
    try:
        images = [tools.open_image(f.stream) for f in files]
        result = tools.images_to_pdf(images)
        return send_file(io.BytesIO(result), as_attachment=True, download_name="images.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/page-count", methods=["POST"])
def pdf_page_count():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        return jsonify({"pages": tools.pdf_page_count(f.stream)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/compress", methods=["POST"])
def pdf_compress():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        result = tools.compress_pdf(f.stream)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_compressed.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/to-text", methods=["POST"])
def pdf_to_text():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        text = tools.pdf_to_text(f.stream)
        if not text:
            return jsonify({"error": "No extractable text found in this PDF"}), 400
        buf = io.BytesIO(text.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "document")
        return send_file(buf, as_attachment=True, download_name=f"{base}.txt",
                         mimetype="text/plain")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/add-password", methods=["POST"])
def pdf_add_password():
    f = request.files.get("file")
    password = request.form.get("password", "")  # spaces are part of a password
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    if not password:
        return jsonify({"error": "No password provided"}), 400
    try:
        result = tools.add_pdf_password(f.stream, password)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_protected.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/remove-password", methods=["POST"])
def pdf_remove_password():
    f = request.files.get("file")
    password = request.form.get("password", "")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        result = tools.remove_pdf_password(f.stream, password)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_unlocked.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/rotate", methods=["POST"])
def pdf_rotate():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        angle = int(request.form.get("angle", 90))
    except ValueError:
        return jsonify({"error": "Invalid angle"}), 400
    pages_str = request.form.get("pages", "all").strip()
    try:
        result = tools.rotate_pdf(f.stream, angle, pages_str)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_rotated.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/reorder", methods=["POST"])
def pdf_reorder():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    order_str = request.form.get("order", "").strip()
    if not order_str:
        return jsonify({"error": "No page order provided"}), 400
    try:
        order = [int(x.strip()) for x in order_str.split(",")]
        result = tools.reorder_pdf(f.stream, order)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_reordered.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/delete-pages", methods=["POST"])
def pdf_delete_pages():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    pages_str = request.form.get("pages", "").strip()
    if not pages_str:
        return jsonify({"error": "No pages specified"}), 400
    try:
        result = tools.delete_pdf_pages(f.stream, pages_str)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_edited.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/metadata", methods=["GET", "POST"])
def pdf_metadata():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    if request.method == "GET" or request.form.get("action") == "get":
        try:
            return jsonify(tools.get_pdf_metadata(f.stream))
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    else:
        try:
            result = tools.set_pdf_metadata(
                f.stream,
                title=request.form.get("title", ""),
                author=request.form.get("author", ""),
                subject=request.form.get("subject", ""),
                keywords=request.form.get("keywords"),  # absent: keep the PDF's own
                creator=request.form.get("creator"),
            )
            base = tools._base_from_filename(f.filename, "document")
            return send_file(io.BytesIO(result), as_attachment=True,
                             download_name=f"{base}_meta.pdf", mimetype="application/pdf")
        except Exception as e:
            return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/extract-images", methods=["POST"])
def pdf_extract_images():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        images = tools.extract_images_from_pdf(f.stream)
        if not images:
            return jsonify({"error": "No images found in this PDF"}), 400
        if len(images) == 1:
            name, data = images[0]
            mime = "image/jpeg" if name.endswith(".jpg") else "image/png"
            return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
        else:
            zip_data = tools.create_zip(images)
            base = tools._base_from_filename(f.filename, "document")
            return send_file(io.BytesIO(zip_data), as_attachment=True,
                             download_name=f"{base}_images.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/number-pages", methods=["POST"])
def pdf_number_pages():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        start = int(request.form.get("start", 1))
        position = request.form.get("position", "bottom-center")
        result = tools.number_pdf_pages(f.stream, start=start, position=position)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_numbered.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/watermark", methods=["POST"])
def pdf_watermark():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No watermark text provided"}), 400
    try:
        font_size = int(request.form.get("font_size", 36))
        opacity = float(request.form.get("opacity", 0.3))
        position = request.form.get("position", "center")
        result = tools.watermark_pdf(f.stream, text, font_size=font_size,
                                     opacity=opacity, position=position)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_watermarked.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Image API ──

def _image_response(img, filename, suffix, fmt=None):
    """Helper to return an image response."""
    if fmt is None:
        fmt = tools.output_image_format(filename, img)
    data = tools._save_image(img, fmt)
    base = tools._base_from_filename(filename, "image")
    mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=f"{base}_{suffix}.{fmt}", mimetype=mime)


@app.route("/api/images/resize", methods=["POST"])
def image_resize():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No image provided"}), 400

    mode = request.form.get("mode", "dimensions")
    maintain = request.form.get("maintain_aspect", "true") == "true"

    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
        except Exception as e:
            return jsonify({"error": f"Invalid image {f.filename}: {e}"}), 400
        try:
            w_str = request.form.get("width", "")
            h_str = request.form.get("height", "")
            pct = float(request.form.get("percentage", 100))
            img = tools.resize_image(img, mode,
                                     width=int(w_str) if w_str else 0,
                                     height=int(h_str) if h_str else 0,
                                     percentage=pct,
                                     maintain_aspect=maintain)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        fmt = tools.output_image_format(f.filename, img)
        data = tools._save_image(img, fmt)
        out_name = tools._base_from_filename(f.filename, "image") + f"_resized.{fmt}"
        results.append((out_name, data, fmt))

    if len(results) == 1:
        name, data, fmt = results[0]
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
    else:
        zip_data = tools.create_zip([(n, d) for n, d, _ in results])
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name="resized_images.zip", mimetype="application/zip")


@app.route("/api/images/compress", methods=["POST"])
def image_compress():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No images provided"}), 400

    quality_map = {"high": 85, "medium": 60, "low": 30}
    quality = quality_map.get(request.form.get("quality", "medium"), 60)

    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
            fmt = tools.output_image_format(f.filename, img, writable=("jpg", "png", "webp"))
            data = tools.compress_image(img, quality, fmt)
            out_name = tools._base_from_filename(f.filename, "image") + f"_compressed.{fmt}"
            results.append((out_name, data, fmt))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400

    original_size = sum(f.seek(0, 2) or f.tell() for f in files)
    if len(results) == 1:
        name, data, fmt = results[0]
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        resp = send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
        resp.headers["X-Original-Size"] = str(original_size)
        resp.headers["X-Compressed-Size"] = str(len(data))
        return resp
    else:
        zip_data = tools.create_zip([(n, d) for n, d, _ in results])
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name="compressed_images.zip", mimetype="application/zip")


@app.route("/api/images/convert", methods=["POST"])
def image_convert():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No images provided"}), 400

    target = request.form.get("format", "png").lower()
    if target not in ("png", "jpg", "webp"):
        return jsonify({"error": "Unsupported format"}), 400

    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
            data = tools.convert_image(img, target)
            base = tools._base_from_filename(f.filename, f.filename)
            results.append((f"{base}.{target}", data))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400

    if len(results) == 1:
        name, data = results[0]
        mime = tools._MIME_MAP.get(target, f"image/{target}")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
    else:
        zip_data = tools.create_zip(results)
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name=f"converted_{target}.zip", mimetype="application/zip")


@app.route("/api/images/crop", methods=["POST"])
def image_crop():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        left = int(request.form.get("left", 0))
        top = int(request.form.get("top", 0))
        right = int(request.form.get("right", 0))
        bottom = int(request.form.get("bottom", 0))
    except ValueError:
        return jsonify({"error": "Invalid crop values"}), 400
    try:
        img = tools.open_image(f.stream)
        cropped = tools.crop_image(img, left, top, right, bottom)
        return _image_response(cropped, f.filename, "cropped")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/rotate", methods=["POST"])
def image_rotate():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No image provided"}), 400
    try:
        angle = int(request.form.get("angle", 90))
    except ValueError:
        return jsonify({"error": "Invalid angle"}), 400
    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
            rotated = tools.rotate_image(img, angle)
            fmt = tools.output_image_format(f.filename, rotated)
            data = tools._save_image(rotated, fmt)
            base = tools._base_from_filename(f.filename, "image")
            results.append((f"{base}_rotated.{fmt}", data, fmt))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400
    if len(results) == 1:
        name, data, fmt = results[0]
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
    zip_data = tools.create_zip([(n, d) for n, d, _ in results])
    return send_file(io.BytesIO(zip_data), as_attachment=True,
                     download_name="rotated_images.zip", mimetype="application/zip")


@app.route("/api/images/strip-exif", methods=["POST"])
def image_strip_exif():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        img = tools.open_image(f.stream)
        clean = tools.strip_exif(img)
        fmt = tools.output_image_format(f.filename, clean)
        data = tools._save_image(clean, fmt)
        base = tools._base_from_filename(f.filename, "image")
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        return send_file(io.BytesIO(data), as_attachment=True,
                         download_name=f"{base}_clean.{fmt}", mimetype=mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/flip", methods=["POST"])
def image_flip():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No image provided"}), 400
    direction = request.form.get("direction", "horizontal")
    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
            flipped = tools.flip_image(img, direction)
            fmt = tools.output_image_format(f.filename, flipped)
            data = tools._save_image(flipped, fmt)
            base = tools._base_from_filename(f.filename, "image")
            results.append((f"{base}_flipped.{fmt}", data, fmt))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400
    if len(results) == 1:
        name, data, fmt = results[0]
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
    zip_data = tools.create_zip([(n, d) for n, d, _ in results])
    return send_file(io.BytesIO(zip_data), as_attachment=True,
                     download_name="flipped_images.zip", mimetype="application/zip")


@app.route("/api/images/grayscale", methods=["POST"])
def image_grayscale():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No image provided"}), 400
    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
            gray = tools.grayscale_image(img)
            fmt = tools.output_image_format(f.filename, gray)
            data = tools._save_image(gray, fmt)
            base = tools._base_from_filename(f.filename, "image")
            results.append((f"{base}_grayscale.{fmt}", data, fmt))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400
    if len(results) == 1:
        name, data, fmt = results[0]
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
    zip_data = tools.create_zip([(n, d) for n, d, _ in results])
    return send_file(io.BytesIO(zip_data), as_attachment=True,
                     download_name="grayscale_images.zip", mimetype="application/zip")


@app.route("/api/images/blur", methods=["POST"])
def image_blur():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No image provided"}), 400
    try:
        radius = float(request.form.get("radius", 5))
    except ValueError:
        return jsonify({"error": "Invalid radius"}), 400
    results = []
    for f in files:
        try:
            img = tools.open_image(f.stream)
            blurred = tools.blur_image(img, radius)
            fmt = tools.output_image_format(f.filename, blurred)
            data = tools._save_image(blurred, fmt)
            base = tools._base_from_filename(f.filename, "image")
            results.append((f"{base}_blur.{fmt}", data, fmt))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400
    if len(results) == 1:
        name, data, fmt = results[0]
        mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name, mimetype=mime)
    zip_data = tools.create_zip([(n, d) for n, d, _ in results])
    return send_file(io.BytesIO(zip_data), as_attachment=True,
                     download_name="blurred_images.zip", mimetype="application/zip")


@app.route("/api/images/to-ico", methods=["POST"])
def image_to_ico():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    sizes_str = request.form.get("sizes", "16,32,48,64,128,256")
    try:
        sizes = [int(s.strip()) for s in sizes_str.split(",") if s.strip()]
        if not sizes:
            sizes = [16, 32, 48, 64, 128, 256]
    except ValueError:
        return jsonify({"error": "Invalid sizes"}), 400
    try:
        img = tools.open_image(f.stream)
        result = tools.image_to_ico(img, sizes)
        base = tools._base_from_filename(f.filename, "icon")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}.ico", mimetype="image/x-icon")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/watermark", methods=["POST"])
def image_watermark():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No watermark text provided"}), 400
    try:
        position = request.form.get("position", "center")
        opacity = int(request.form.get("opacity", 128))
        font_size = int(request.form.get("font_size", 36))
        img = tools.open_image(f.stream)
        result = tools.watermark_image(img, text, position=position,
                                       opacity=opacity, font_size=font_size)
        # Convert back from RGBA for output
        fmt = tools.output_image_format(f.filename)
        if fmt == "jpg":
            result = result.convert("RGB")
        return _image_response(result, f.filename, "watermarked", fmt)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/qr-generate", methods=["POST"])
def qr_generate():
    data = _body()
    text = data.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return jsonify({"error": "No text provided"}), 400
    try:
        result = tools.generate_qr(
            text,
            box_size=int(data.get("size", 10)),
            error_correction=data.get("error_correction", "M"),
            fill_color=data.get("fill_color", "black"),
            back_color=data.get("back_color", "white"),
        )
        return send_file(io.BytesIO(result), mimetype="image/png",
                         download_name="qrcode.png")
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/images/placeholder", methods=["POST"])
def placeholder_image():
    data = _body()
    try:
        width = int(data.get("width", 800))
        height = int(data.get("height", 600))
    except (TypeError, ValueError):
        return jsonify({"error": "Width and height must be whole numbers."}), 400
    if width < 1 or height < 1 or width > 4096 or height > 4096:
        return jsonify({"error": "Dimensions must be 1-4096"}), 400
    try:
        result = tools.generate_placeholder_image(
            width, height,
            bg_color=data.get("bg_color", "#cccccc"),
            text_color=data.get("text_color", "#666666"),
            text=data.get("text", ""),
        )
        return send_file(io.BytesIO(result), mimetype="image/png",
                         download_name=f"placeholder_{width}x{height}.png")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Convert API ──

@app.route("/api/convert/md-to-html", methods=["POST"])
def md_to_html():
    text = None
    f = request.files.get("file")
    if f:
        text = f.stream.read().decode("utf-8", errors="replace")
    else:
        text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No markdown content provided"}), 400
    html_doc = tools.md_to_html(text)
    buf = io.BytesIO(html_doc.encode("utf-8"))
    return send_file(buf, as_attachment=True, download_name="converted.html",
                     mimetype="text/html")


@app.route("/api/convert/md-preview", methods=["POST"])
def md_preview():
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    return jsonify({"html": tools.md_preview(text)})


@app.route("/api/convert/csv-to-json", methods=["POST"])
def csv_to_json():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No CSV file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.csv_to_json_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.json",
                         mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/json-to-csv", methods=["POST"])
def json_to_csv():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No JSON file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.json_to_csv_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.csv",
                         mimetype="text/csv")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/yaml-to-json", methods=["POST"])
def yaml_to_json():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No YAML file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.yaml_to_json_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.json",
                         mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/json-to-yaml", methods=["POST"])
def json_to_yaml():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No JSON file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.json_to_yaml_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.yaml",
                         mimetype="text/yaml")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/csv-to-tsv", methods=["POST"])
def csv_to_tsv():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No CSV file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.csv_to_tsv_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.tsv",
                         mimetype="text/tab-separated-values")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/tsv-to-csv", methods=["POST"])
def tsv_to_csv():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No TSV file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.tsv_to_csv_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.csv",
                         mimetype="text/csv")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/xml-to-json", methods=["POST"])
def xml_to_json():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No XML file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        result = tools.xml_to_json_str(text)
        buf = io.BytesIO(result.encode("utf-8"))
        base = tools._base_from_filename(f.filename, "data")
        return send_file(buf, as_attachment=True, download_name=f"{base}.json",
                         mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── AV API ──

@app.route("/api/av/convert-audio", methods=["POST"])
def av_convert_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    fmt = request.form.get("format", "mp3").lower()
    if fmt not in tools.AUDIO_CODEC_MAP:
        return jsonify({"error": "Unsupported format"}), 400
    ext = tools._ext_from_filename(f.filename, "bin")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.convert_audio(f.stream.read(), ext, fmt)
        return send_file(io.BytesIO(result), as_attachment=True, download_name=f"{base}.{fmt}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/trim-audio", methods=["POST"])
def av_trim_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()
    if not start:
        return jsonify({"error": "Start time required"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.trim_audio(f.stream.read(), ext, start, end)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_trimmed.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/audio-speed", methods=["POST"])
def av_audio_speed():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    speed = request.form.get("speed", "1.5")
    try:
        speed_f = float(speed)
    except ValueError:
        return jsonify({"error": "Invalid speed"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    out_ext = ext if ext in ("mp3", "wav", "ogg", "flac") else "mp3"
    try:
        result = tools.audio_speed(f.stream.read(), ext, speed_f)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_{speed}x.{out_ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/extract-audio", methods=["POST"])
def av_extract_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    fmt = request.form.get("format", "mp3").lower()
    if fmt not in tools.AUDIO_CODEC_MAP:
        return jsonify({"error": "Unsupported format"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.extract_audio(f.stream.read(), ext, fmt)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_audio.{fmt}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/trim-video", methods=["POST"])
def av_trim_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    start = request.form.get("start", "").strip()
    end = request.form.get("end", "").strip()
    if not start:
        return jsonify({"error": "Start time required"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.trim_video(f.stream.read(), ext, start, end)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_trimmed.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/compress-video", methods=["POST"])
def av_compress_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    quality = request.form.get("quality", "medium")
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.compress_video(f.stream.read(), ext, quality)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_compressed.mp4")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/convert-video", methods=["POST"])
def av_convert_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    fmt = request.form.get("format", "mp4").lower()
    if fmt not in tools.VIDEO_CODEC_MAP:
        return jsonify({"error": "Unsupported format"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.convert_video(f.stream.read(), ext, fmt)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}.{fmt}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/merge-audio", methods=["POST"])
def av_merge_audio():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Need at least 2 audio files"}), 400
    fmt = request.form.get("format", "mp3").lower()
    try:
        files_data = [(tools._ext_from_filename(f.filename, "mp3"), f.stream.read()) for f in files]
        result = tools.merge_audio_files(files_data, fmt)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"merged.{fmt}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/normalize-volume", methods=["POST"])
def av_normalize_volume():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.normalize_volume(f.stream.read(), ext)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_normalized.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/video-to-gif", methods=["POST"])
def av_video_to_gif():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    try:
        fps = int(request.form.get("fps", 10))
        width = int(request.form.get("width", 480))
    except ValueError:
        return jsonify({"error": "Invalid parameters"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.video_to_gif(f.stream.read(), ext, fps=fps, width=width)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}.gif", mimetype="image/gif")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/reverse-audio", methods=["POST"])
def av_reverse_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.reverse_audio(f.stream.read(), ext)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_reversed.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/change-pitch", methods=["POST"])
def av_change_pitch():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    try:
        semitones = float(request.form.get("semitones", 0))
    except ValueError:
        return jsonify({"error": "Invalid semitones value"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.change_pitch(f.stream.read(), ext, semitones)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_pitch.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/audio-equalizer", methods=["POST"])
def av_audio_equalizer():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    try:
        bass = float(request.form.get("bass", 0))
        mid = float(request.form.get("mid", 0))
        treble = float(request.form.get("treble", 0))
    except ValueError:
        return jsonify({"error": "Invalid equalizer values"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.audio_equalizer(f.stream.read(), ext, bass, mid, treble)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_eq.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/audio-fade", methods=["POST"])
def av_audio_fade():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    try:
        fade_in = float(request.form.get("fade_in", 0))
        fade_out = float(request.form.get("fade_out", 0))
        duration = float(request.form.get("duration", 0))
    except ValueError:
        return jsonify({"error": "Invalid fade values"}), 400
    ext = tools._ext_from_filename(f.filename, "mp3")
    base = tools._base_from_filename(f.filename, "audio")
    try:
        result = tools.audio_fade(f.stream.read(), ext, fade_in, fade_out, duration)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_faded.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/crop-video", methods=["POST"])
def av_crop_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    try:
        width = int(request.form.get("width", 0))
        height = int(request.form.get("height", 0))
        x = int(request.form.get("x", 0))
        y = int(request.form.get("y", 0))
    except ValueError:
        return jsonify({"error": "Invalid crop parameters"}), 400
    if width <= 0 or height <= 0:
        return jsonify({"error": "Width and height required"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.crop_video(f.stream.read(), ext, width, height, x, y)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_cropped.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/rotate-video", methods=["POST"])
def av_rotate_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    try:
        angle = int(request.form.get("angle", 90))
    except ValueError:
        return jsonify({"error": "Invalid angle"}), 400
    if angle not in (90, 180, 270):
        return jsonify({"error": "Angle must be 90, 180, or 270"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.rotate_video(f.stream.read(), ext, angle)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_rotated.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/resize-video", methods=["POST"])
def av_resize_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    try:
        width = int(request.form.get("width", 0))
        height = int(request.form.get("height", -1))
    except ValueError:
        return jsonify({"error": "Invalid dimensions"}), 400
    if width <= 0:
        return jsonify({"error": "Width required"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.resize_video(f.stream.read(), ext, width, height)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_resized.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/reverse-video", methods=["POST"])
def av_reverse_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.reverse_video(f.stream.read(), ext)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_reversed.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/loop-video", methods=["POST"])
def av_loop_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    try:
        count = int(request.form.get("count", 2))
    except ValueError:
        return jsonify({"error": "Invalid loop count"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.loop_video(f.stream.read(), ext, count)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_looped.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/mute-video", methods=["POST"])
def av_mute_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    ext = tools._ext_from_filename(f.filename, "mp4")
    base = tools._base_from_filename(f.filename, "video")
    try:
        result = tools.mute_video(f.stream.read(), ext)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_muted.{ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/add-audio", methods=["POST"])
def av_add_audio():
    video = request.files.get("video")
    audio = request.files.get("audio")
    if not video:
        return jsonify({"error": "No video file provided"}), 400
    if not audio:
        return jsonify({"error": "No audio file provided"}), 400
    video_ext = tools._ext_from_filename(video.filename, "mp4")
    base = tools._base_from_filename(video.filename, "video")
    audio_ext = tools._ext_from_filename(audio.filename, "mp3")
    try:
        result = tools.add_audio_to_video(video.stream.read(), video_ext,
                                          audio.stream.read(), audio_ext)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_with_audio.{video_ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/burn-subtitles", methods=["POST"])
def av_burn_subtitles():
    video = request.files.get("video")
    subtitles = request.files.get("subtitles")
    if not video:
        return jsonify({"error": "No video file provided"}), 400
    if not subtitles:
        return jsonify({"error": "No subtitles file provided"}), 400
    video_ext = tools._ext_from_filename(video.filename, "mp4")
    base = tools._base_from_filename(video.filename, "video")
    try:
        result = tools.burn_subtitles(video.stream.read(), video_ext,
                                      subtitles.stream.read())
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_subtitled.{video_ext}")
    except tools.FFmpegMissingError:
        return _ffmpeg_missing_response()
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


# ── Archive convert ──

@app.route("/api/convert/zip", methods=["POST"])
def convert_zip():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400
    try:
        file_list = [(f.filename or "file", f.stream.read()) for f in files]
        result = tools.create_zip(file_list)
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name="archive.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/unzip", methods=["POST"])
def convert_unzip():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No ZIP file provided"}), 400
    try:
        extracted = tools.extract_zip(f.stream.read())
        if not extracted:
            return jsonify({"error": "ZIP file is empty"}), 400
        if len(extracted) == 1:
            name, data = extracted[0]
            return send_file(io.BytesIO(data), as_attachment=True, download_name=name)
        else:
            zip_data = tools.create_zip(extracted)
            base = tools._base_from_filename(f.filename, "archive")
            return send_file(io.BytesIO(zip_data), as_attachment=True,
                             download_name=f"{base}_extracted.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Transcription API ──

@app.route("/api/transcribe/check", methods=["GET"])
def transcribe_check():
    whisper_ok, diarize_ok = tools._check_transcribe_deps()
    return jsonify({"whisper": whisper_ok, "diarize": diarize_ok})


@app.route("/api/transcribe", methods=["POST"])
def transcribe():
    whisper_ok, _ = tools._check_transcribe_deps()
    if not whisper_ok:
        return jsonify({"error": "Transcription not available. Install with: pip install sdexe[transcribe]"}), 400

    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400

    model = request.form.get("model", "base")
    language = request.form.get("language", "").strip() or None
    diarize = request.form.get("diarize", "false") == "true"
    hf_token = request.form.get("hf_token", "").strip()
    num_speakers_str = request.form.get("num_speakers", "").strip()
    try:
        num_speakers = int(num_speakers_str) if num_speakers_str else None
    except ValueError:
        return jsonify({"error": "Number of speakers must be a whole number"}), 400
    if num_speakers is not None and num_speakers < 1:
        return jsonify({"error": "Number of speakers must be at least 1"}), 400

    valid_models = ("tiny", "base", "small", "medium", "large-v3")
    if model not in valid_models:
        return jsonify({"error": f"Invalid model. Choose from: {', '.join(valid_models)}"}), 400

    t_id = str(uuid.uuid4())[:12]
    ext = tools._ext_from_filename(f.filename, "mp3")
    input_path = str(DOWNLOAD_DIR / f"{t_id}_input.{ext}")
    f.save(input_path)

    # "error" is pre-created so the worker thread never resizes this dict while
    # the SSE generator is serializing it.
    transcriptions[t_id] = {
        "progress": 0, "status": "starting",
        "detail": "Preparing audio...", "segments": None, "language": None,
        "error": None, "note": None, "created": time.time(), "finished": None,
    }

    def do_transcribe():
        wav_path = str(DOWNLOAD_DIR / f"{t_id}_audio.wav")
        try:
            def progress_cb(pct, status, detail):
                transcriptions[t_id]["progress"] = pct
                transcriptions[t_id]["status"] = status
                transcriptions[t_id]["detail"] = detail

            progress_cb(2, "preparing", "Extracting audio...")
            tools.extract_audio_for_transcription(input_path, wav_path)

            segments, detected_lang = tools.transcribe_audio(
                wav_path, model_size=model, language=language, progress_cb=progress_cb
            )
            transcriptions[t_id]["language"] = detected_lang

            _, diarize_ok = tools._check_transcribe_deps()
            if diarize and diarize_ok and hf_token:
                diar_segments = tools.diarize_audio(
                    wav_path, hf_token=hf_token,
                    num_speakers=num_speakers, progress_cb=progress_cb
                )
                segments = tools.merge_transcription_and_diarization(segments, diar_segments)
            elif diarize and not diarize_ok:
                transcriptions[t_id]["note"] = "Speaker labels were skipped: pyannote.audio isn't installed."
            elif diarize and not hf_token:
                transcriptions[t_id]["note"] = "Speaker labels were skipped: no HuggingFace token."

            progress_cb(95, "finalizing", "Preparing results...")
            transcriptions[t_id]["segments"] = segments
            transcriptions[t_id]["progress"] = 100
            transcriptions[t_id]["detail"] = "Transcription complete"
            transcriptions[t_id]["finished"] = time.time()
            transcriptions[t_id]["status"] = "done"

        except Exception as e:
            transcriptions[t_id]["error"] = str(e)[:500]
            transcriptions[t_id]["finished"] = time.time()
            transcriptions[t_id]["status"] = "error"
        finally:
            Path(input_path).unlink(missing_ok=True)
            Path(wav_path).unlink(missing_ok=True)

    thread = threading.Thread(target=do_transcribe, daemon=True)
    thread.start()
    return jsonify({"id": t_id})


@app.route("/api/transcribe/progress/<t_id>")
def transcribe_progress(t_id):
    def stream():
        while True:
            info = transcriptions.get(t_id)
            if not info:
                yield f"data: {json.dumps({'error': 'Unknown transcription'})}\n\n"
                break
            info = dict(info)  # one snapshot, as in progress() above
            yield f"data: {json.dumps(info)}\n\n"
            if info["status"] in ("done", "error"):
                break
            time.sleep(0.5)
    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/transcribe/export", methods=["POST"])
def transcribe_export():
    data = _body()
    segments = data.get("segments", [])
    fmt = data.get("format", "txt")
    include_speakers = data.get("include_speakers", True)

    if not segments:
        return jsonify({"error": "No segments to export"}), 400

    if fmt == "txt":
        content = tools.export_transcript_txt(segments, include_speakers)
        mimetype, filename = "text/plain", "transcript.txt"
    elif fmt == "srt":
        content = tools.export_transcript_srt(segments)
        mimetype, filename = "application/x-subrip", "transcript.srt"
    elif fmt == "vtt":
        content = tools.export_transcript_vtt(segments)
        mimetype, filename = "text/vtt", "transcript.vtt"
    elif fmt == "csv":
        content = tools.export_transcript_csv(segments)
        mimetype, filename = "text/csv", "transcript.csv"
    else:
        return jsonify({"error": f"Unsupported format: {fmt}"}), 400

    return send_file(
        io.BytesIO(content.encode("utf-8")),
        as_attachment=True, download_name=filename, mimetype=mimetype,
    )


def _exit_on_terminate():
    """Turn SIGTERM (kill) and SIGHUP (the terminal window was closed) into a
    normal exit, so the temp download directory is removed on the way out.
    By default both end the process without running any exit handler.
    Not for the menu bar icon: its run loop never returns to Python to run
    a handler, so installing one there would make sdexe ignore kill."""
    import signal
    import sys

    def handler(sig, frame):
        sys.exit(128 + sig)

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        # Left alone when already ignored: that is how `nohup sdexe &` keeps
        # the server alive after its terminal closes.
        if sig is not None and signal.getsignal(sig) != signal.SIG_IGN:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def _run_with_terminal_app(tui, host, port, url, note, update):
    """The web server on a thread, the clickable terminal app on the main one.
    Server logs go to a file: anything printed would draw over the app."""
    import logging
    import signal
    import sys
    import threading
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(CONFIG_DIR / "server.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    for name in ("werkzeug", "sdexe", app.logger.name):
        log = logging.getLogger(name)
        log.handlers = [handler]
        log.propagate = False
    signal.signal(signal.SIGINT, signal.default_int_handler)
    _exit_on_terminate()
    threading.Thread(target=lambda: app.run(host=host, port=port, use_reloader=False), daemon=True).start()
    try:
        tui.run(url=url, note=note, update=update)
    finally:
        from sdexe import ui
        ui.console().print("  [muted]sdexe stopped.[/muted]")
    sys.exit(0)


def _run_update():
    import sys
    from sdexe import ui
    c = ui.console()
    with c.status("  [muted]updating sdexe and its downloader engine…[/muted]", spinner="dots"):
        ok, msg = self_update()
    c.print(f"  [ok]✓[/ok] {msg}\n" if ok else f"  [err]✗[/err] {msg}\n")
    sys.exit(0 if ok else 1)


# ── Startup helpers ──

def _install_transcribe_deps():
    """Install transcription dependencies into sdexe's own environment."""
    import shutil
    import sys
    from rich.console import Console

    console = Console()
    deps = ["faster-whisper", "pyannote.audio"]

    whisper_ok, _ = tools._check_transcribe_deps()
    if whisper_ok:
        console.print("  [green]Transcription dependencies already installed.[/green]")
        return

    console.print(f"\n  Installing transcription support ({', '.join(deps)})...\n")

    cmd = [sys.executable, "-m", "pip", "install"] + deps

    console.print(f"  [dim]Running: {' '.join(cmd)}[/dim]\n")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        console.print("\n  [green]Transcription support installed successfully.[/green]")
    else:
        console.print("\n  [red]Installation failed.[/red] Try manually: pip install faster-whisper pyannote.audio")


def install_ffmpeg():
    """Install a system ffmpeg via the platform package manager (non-interactive).

    Returns (ok, message). A bundled ffmpeg (imageio-ffmpeg) already covers most
    needs; this is for users who want a full-featured system ffmpeg. Uses
    non-interactive sudo on Linux so a web-triggered call can never hang on a
    password prompt.
    """
    import sys
    platform = sys.platform
    try:
        if platform == "darwin":
            if not shutil.which("brew"):
                return False, "Homebrew not found. Install it from https://brew.sh, then run: brew install ffmpeg"
            r = subprocess.run(["brew", "install", "ffmpeg"], capture_output=True, text=True, timeout=900)
        elif platform.startswith("linux"):
            if shutil.which("apt-get"):
                r = subprocess.run(["sudo", "-n", "apt-get", "install", "-y", "ffmpeg"], capture_output=True, text=True, timeout=900)
            elif shutil.which("dnf"):
                r = subprocess.run(["sudo", "-n", "dnf", "install", "-y", "ffmpeg"], capture_output=True, text=True, timeout=900)
            else:
                return False, "No supported package manager found. Install ffmpeg manually."
        elif platform.startswith("win"):
            if shutil.which("winget"):
                r = subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                                    "--accept-source-agreements", "--accept-package-agreements"],
                                   capture_output=True, text=True, timeout=900)
            elif shutil.which("choco"):
                r = subprocess.run(["choco", "install", "ffmpeg", "-y"], capture_output=True, text=True, timeout=900)
            else:
                return False, "No package manager (winget/choco) found. Install ffmpeg from https://ffmpeg.org/download.html"
        else:
            return False, "Unsupported platform. Install ffmpeg from https://ffmpeg.org/download.html"
    except subprocess.TimeoutExpired:
        return False, "ffmpeg install timed out."
    except Exception as e:
        return False, f"ffmpeg install failed: {e}"

    tools._reset_ffmpeg_cache()
    if r.returncode == 0 and shutil.which("ffmpeg"):
        return True, "ffmpeg installed."
    detail = (r.stderr or r.stdout or "Installation failed.").strip()
    return False, detail[-400:]


def _run_tray(port):
    try:
        import pystray
        from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont
        import webbrowser as _wb

        size = 64
        img = _Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = _ImageDraw.Draw(img)
        draw.ellipse([2, 2, size - 2, size - 2], fill=(30, 30, 40, 255))

        font = None
        for font_path in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSText.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]:
            try:
                font = _ImageFont.truetype(font_path, 26)
                break
            except Exception:
                continue
        if font is None:
            font = _ImageFont.load_default()

        text = "sd"
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            tx = (size - tw) / 2 - bbox[0]
            ty = (size - th) / 2 - bbox[1]
        except AttributeError:
            tw, th = draw.textsize(text, font=font)
            tx = (size - tw) / 2
            ty = (size - th) / 2
        draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

        def open_app(icon, item):
            _wb.open(f"http://127.0.0.1:{port}")

        def quit_app(icon, item):
            icon.stop()
            import os
            # os._exit skips atexit handlers, so the temp download dir would be
            # left behind on every quit.
            _cleanup_on_exit()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Open sdexe", open_app, default=True),
            pystray.MenuItem("Quit", quit_app),
        )
        icon = pystray.Icon("sdexe", img, "sdexe", menu)
        _tray_exit_cleanup()
        icon.run()
        return True
    except Exception:
        return False


def _tray_exit_cleanup():
    """macOS only. While the menu bar icon runs, Ctrl+C ends the process from
    inside the Cocoa run loop (NSApp terminate), and kill / a closed terminal
    window end it outright. None of those run Python's exit handlers, so the
    temp download directory was left behind every time."""
    import sys
    if sys.platform != "darwin":
        return
    try:
        import signal
        import AppKit
        from PyObjCTools import MachSignals

        def terminated(sig):
            _cleanup_on_exit()
            os._exit(128 + sig)

        for sig in (signal.SIGTERM, signal.SIGHUP):
            if signal.getsignal(sig) != signal.SIG_IGN:  # nohup: stay ignored
                MachSignals.signal(sig, terminated)
        # Kept referenced for the life of the process.
        _tray_exit_cleanup.observer = AppKit.NSNotificationCenter.defaultCenter() \
            .addObserverForName_object_queue_usingBlock_(
                "NSApplicationWillTerminateNotification", None, None,
                lambda _note: _cleanup_on_exit())
    except Exception:
        pass


def _find_free_port(host, start_port, max_tries=20):
    """Find a free port starting from start_port."""
    import socket
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for offset in range(max_tries):
        port = start_port + offset
        if port > 65535:
            break
        with socket.socket(family, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return None


def _open_browser_when_up(url, host, port):
    """Open the browser once the server accepts connections. It used to be
    opened first, 0.1 to 0.4 s before the server listened (longer when the
    update check was slow), so an already-running browser could get there
    first and show "can't connect"."""
    import socket
    import threading
    import webbrowser

    def wait_then_open():
        for _ in range(100):
            try:
                socket.create_connection((host, port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.05)
        webbrowser.open(url)

    threading.Thread(target=wait_then_open, daemon=True).start()


def _allow_bind_host(host):
    """--host names something other than loopback: let requests for it past
    the Host check, which otherwise answers every page with 403."""
    global _allow_ip_hosts
    host = host.strip("[]").lower()
    if host in ("0.0.0.0", "::", ""):
        import socket
        _allow_ip_hosts = True
        name = socket.gethostname().lower()
        if name:
            _extra_hosts.update({name, name.split(".")[0], name.split(".")[0] + ".local"})
    elif host not in ("127.0.0.1", "localhost", "::1"):
        _extra_hosts.add(host)


_COMMANDS = ("download", "info", "pdf", "image", "audio", "video", "convert", "file", "mcp", "skill",
             "setup", "settings", "tutorial", "search", "update", "transcribe")

def _print_main_help():
    from rich.text import Text
    from sdexe import ui
    c = ui.console()
    ui.header(c)
    w = 30
    groups = [
        ("Start", [
            ("sdexe", "the web app at localhost:5001"),
            ("sdexe tutorial", "a 3-minute hands-on walkthrough"),
            ("sdexe settings", "defaults, download folder, colours, Claude Code, startup"),
            ("sdexe setup", "the guided first-run questions, again"),
        ]),
        ("Media from links", [
            ('sdexe download "<link>" …', "video or audio · add -mp3, -a, -720p, --best"),
            ('sdexe search "<words>"', "find a video or song by name · no link needed"),
            ('sdexe info "<link>"', "qualities, sizes, chapters · a dry run of download"),
        ]),
        ("Your files", [
            ("sdexe pdf <command>", "merge · split · compress · text · OCR · watermark · encrypt"),
            ("sdexe image <command>", "resize · compress · convert (HEIC too) · crop · QR"),
            ("sdexe audio <command>", "convert · trim · speed · normalize · fade · merge"),
            ("sdexe video <command>", "convert · trim · compress · GIF · frames · merge"),
            ("sdexe convert <file> -f FMT", "csv · json · yaml · xml · toml · md · html · xlsx"),
            ("sdexe file <command>", "hash · zip · unzip · split"),
        ]),
        ("AI agents", [
            ("sdexe mcp", "MCP server: every tool for Claude, Cursor & co."),
            ("sdexe skill [--install]", "a Claude Code skill describing every command"),
        ]),
        ("Keep it current", [
            ("sdexe update", "sdexe and its downloader engine"),
            ("sdexe transcribe", "install the optional transcription engine"),
        ]),
    ]
    for title, items in groups:
        c.print()
        c.print(ui.section(title))
        c.print(ui.rows(items, key_width=w))
    c.print()
    c.print(ui.section("Starting the web app"))
    c.print(ui.rows([
        ("--browser / --no-browser", "open it this time or not, whatever the setting"),
        ("-p, --port PORT", "default 5001, or the next free one"),
        ("--open PAGE", "media, pdf, images, convert, av, text"),
        ("--classic", "no clickable app: print the address and wait"),
        ("--no-tray · --host · -q · -V", "no menu bar icon · bind address · no banner · version"),
    ], key_width=w))
    c.print()
    c.print(Text.assemble(("  Every command takes ", "muted"), ("--help", "brand2"), (", ", "muted"),
                          ("--json", "brand2"), (" and ", "muted"), ("-o", "brand2"),
                          (". Results land in the current folder.", "muted")))
    c.print()


def main():
    import argparse
    import logging
    import signal
    import sys
    import threading
    import webbrowser
    from sdexe import ui

    if len(sys.argv) > 1 and sys.argv[1] == "download":
        from sdexe.cli import download_main
        sys.exit(download_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        from sdexe.cli_search import search_main
        sys.exit(search_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "info":
        from sdexe.cli_info import info_main
        sys.exit(info_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("setup", "tutorial"):
        from sdexe import cli_home
        sys.exit((cli_home.setup_main if sys.argv[1] == "setup" else cli_home.tutorial_main)(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("update", "transcribe"):
        # These take no options; without this, `sdexe update --help` updated.
        cmd = sys.argv[1]
        argparse.ArgumentParser(prog=f"sdexe {cmd}", description={
            "update": "Update sdexe and its downloader engine.",
            "transcribe": "Install the optional transcription engine.",
        }[cmd]).parse_args(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        _run_update()
    if len(sys.argv) > 1 and sys.argv[1] == "transcribe":
        _install_transcribe_deps()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "settings":
        from sdexe.settings import settings_main
        sys.exit(settings_main(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("mcp", "skill"):
        from sdexe import agent
        sys.exit((agent.mcp_main if sys.argv[1] == "mcp" else agent.skill_main)(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] in ("pdf", "image", "audio", "video", "convert", "file"):
        from sdexe.cli_tools import tools_main
        sys.exit(tools_main(sys.argv[1:]))

    parser = argparse.ArgumentParser(prog="sdexe", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-V", "--version", action="version", version=f"sdexe {__version__}")
    parser.add_argument("-p", "--port", type=int)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--classic", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--open", metavar="PAGE")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("command", nargs="?")

    args, extra = parser.parse_known_args()

    err = ui.console(stderr=True)
    if args.help:
        _print_main_help()
        return
    if args.command and args.command not in _COMMANDS:
        import difflib
        guess = difflib.get_close_matches(args.command, _COMMANDS, n=1)
        hint = f" Did you mean [brand]sdexe {guess[0]}[/brand]?" if guess else " Run [brand]sdexe --help[/brand]."
        err.print(f"sdexe: unknown command '{args.command}'.{hint}")
        sys.exit(2)
    if extra:
        err.print(f"sdexe: unknown option {extra[0]}. Run [brand]sdexe --help[/brand].")
        sys.exit(2)
    if args.command:
        # Reached only when options came before the command (sdexe -q download).
        err.print(f"sdexe: put [brand]{args.command}[/brand] first, e.g. sdexe {args.command} …")
        sys.exit(2)

    if args.update:
        _run_update()

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    # Flask prints "* Serving Flask app" / "* Debug mode: off"; the screen below says it better.
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None

    from sdexe import cli_home, settings
    console = ui.console()
    host = args.host
    port = args.port or settings.get("port")
    if not 1 <= port <= 65535:
        # bind() raises OverflowError for these, which showed as a traceback.
        err.print(f"sdexe: port {port} is out of range. Use 1 to 65535.")
        sys.exit(2)
    _allow_bind_host(host)

    # Graceful Ctrl+C
    def _sigint_handler(sig, frame):
        console.print("\n  [muted]sdexe stopped.[/muted]\n")
        sys.exit(0)

    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if interactive and not args.quiet and cli_home.needs_setup():
        try:
            cli_home.run_setup(console, first_run=True)
        except (KeyboardInterrupt, EOFError):
            console.print("\n  [muted]Setup skipped. Run[/muted] [brand]sdexe setup[/brand] [muted]any time.[/muted]")
    signal.signal(signal.SIGINT, _sigint_handler)

    check = not args.quiet and settings.get("update_check")
    update_thread, update = cli_home.start_update_check() if check else (None, {})
    if not settings.get("tray"):
        args.no_tray = True

    # Port auto-detection
    import socket
    port_note = ""
    # An IPv6 address cannot bind an IPv4 socket; that failure used to read
    # as "port in use" on every port tried.
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            original_port = port
            port = _find_free_port(host, port + 1)
            if port is None:
                console.print(f"  [err]✗[/err] Port {original_port} is in use and no free port found nearby.")
                sys.exit(1)
            port_note = f"port {original_port} was busy, so this is {port}"

    # Determine URL to open
    open_path = ""
    if args.open:
        open_path = f"/{args.open.strip('/')}"
    if host.strip("[]").lower() not in ("127.0.0.1", "localhost", "::1"):
        lan = "anyone on your network can use sdexe, no password needed"
        port_note = f"{port_note} · {lan}" if port_note else lan

    # 0.0.0.0 means "every interface", not an address a browser can open.
    url_host = {"0.0.0.0": "127.0.0.1", "": "127.0.0.1", "::": "[::1]"}.get(host, f"[{host}]" if ":" in host else host)
    url = f"http://{url_host}:{port}{open_path}"

    open_browser = args.browser or (not args.no_browser and cli_home.opens_browser())
    if open_browser:
        _open_browser_when_up(url, url_host.strip("[]"), port)

    use_app = interactive and not args.quiet and not args.classic and settings.get("terminal_app")
    if use_app:
        try:
            from sdexe import tui
        except ImportError:
            use_app = False
            console.print("  [warn]![/warn] [muted]The terminal app needs Textual:[/muted] [brand]sdexe update[/brand]")
    if use_app:
        _run_with_terminal_app(tui, host, port, url, port_note, update)
        return

    if not args.quiet:
        if update_thread:
            update_thread.join(timeout=1.5)
        try:
            import pystray  # noqa: F401
            has_tray = not args.no_tray
        except ImportError:
            has_tray = False
        cli_home.startup_screen(console, url, opened=open_browser, port_note=port_note, update=update,
                                tray=has_tray)

    # Start server
    if args.no_tray:
        _exit_on_terminate()
        app.run(host=host, port=port, use_reloader=False)
    else:
        try:
            import pystray  # noqa: F401, just checking availability
            flask_thread = threading.Thread(
                target=lambda: app.run(host=host, port=port, use_reloader=False),
                daemon=True,
            )
            flask_thread.start()
            # The tray fails to start on a headless session or a missing
            # backend. Flask runs on a daemon thread, so returning here would
            # kill the server the moment main() ends. Block instead.
            if not _run_tray(port):
                if not args.quiet:
                    console.print("  [warn]![/warn] [muted]Menu bar icon unavailable here; running without it.[/muted]\n")
                _exit_on_terminate()
                flask_thread.join()
        except ImportError:
            _exit_on_terminate()
            app.run(host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    app.run(port=5001)
