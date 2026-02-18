import os
import io
import csv
import uuid
import time
import tempfile
import threading
import json
import subprocess
import zipfile
import atexit
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
import markdown as md_lib
from pypdf import PdfReader, PdfWriter
from PIL import Image

app = Flask(__name__)

from sdexe import __version__

@app.context_processor
def inject_version():
    return {"version": __version__}

@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response

DOWNLOAD_DIR = Path(tempfile.mkdtemp(prefix="toolkit_"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

def _cleanup_on_exit():
    import shutil
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

atexit.register(_cleanup_on_exit)

# Simple rate limiting for /api/download
_download_timestamps: list = []
_DOWNLOAD_RATE_LIMIT = 12
_DOWNLOAD_RATE_WINDOW = 10.0

def _check_download_rate() -> bool:
    global _download_timestamps
    now = time.time()
    _download_timestamps = [t for t in _download_timestamps if now - t < _DOWNLOAD_RATE_WINDOW]
    if len(_download_timestamps) >= _DOWNLOAD_RATE_LIMIT:
        return False
    _download_timestamps.append(now)
    return True

CONFIG_DIR = Path.home() / ".config" / "sdexe"
CONFIG_FILE = CONFIG_DIR / "config.json"

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}

def save_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

HISTORY_FILE = CONFIG_DIR / "history.json"

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return []

def save_history(items):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items, indent=2))

# Stores progress and file info keyed by download ID
downloads = {}


def cleanup_old_files(max_age_seconds=3600):
    """Delete downloaded files older than max_age_seconds and prune stale dict entries."""
    now = time.time()
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
            f.unlink(missing_ok=True)
    stale = [
        k for k, v in downloads.items()
        if v.get("status") in ("done", "error")
        and v.get("filename")
        and not (DOWNLOAD_DIR / v["filename"]).exists()
    ]
    for k in stale:
        downloads.pop(k, None)


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
    args = []
    for key, value in metadata.items():
        if value and value.strip():
            args.extend(["-metadata", f"{key}={value.strip()}"])
    if not args:
        return
    tmp = filepath.parent / f"_meta_{filepath.name}"
    cmd = ["ffmpeg", "-y", "-i", str(filepath), "-codec", "copy", "-map", "0"] + args + [str(tmp)]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0:
            tmp.replace(filepath)
        else:
            tmp.unlink(missing_ok=True)
    except Exception:
        tmp.unlink(missing_ok=True)


# ── Page Routes ──

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

@app.route("/settings")
def settings_page():
    return render_template("settings.html")


# ── Config API ──

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def set_config_route():
    updates = request.json or {}
    if "output_folder" in updates and updates["output_folder"]:
        resolved, err = _validate_folder(updates["output_folder"])
        if err:
            return jsonify({"error": err}), 400
        updates["output_folder"] = resolved
    cfg = load_config()
    cfg.update(updates)
    save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify(load_history())

@app.route("/api/history", methods=["POST"])
def add_history():
    item = request.json or {}
    if not item.get("title"):
        return jsonify({"error": "title required"}), 400
    items = load_history()
    items.insert(0, {
        "title": item.get("title", ""),
        "format": item.get("format", ""),
        "id": item.get("id", ""),
        "url": item.get("url", ""),
        "ts": time.time(),
    })
    items = items[:50]
    save_history(items)
    return jsonify({"ok": True})


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    cfg = load_config()
    folder = cfg.get("output_folder", "").strip()
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
    path = (request.json or {}).get("path", "").strip()
    if not path:
        return jsonify({"error": "No path provided"}), 400
    p = Path(path).expanduser()
    if not p.exists():
        return jsonify({"error": "File not found"}), 404
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


@app.route("/api/update", methods=["POST"])
def run_update():
    try:
        result = subprocess.run(
            ["pipx", "upgrade", "sdexe"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return jsonify({"ok": True, "output": result.stdout.strip()})
        else:
            return jsonify({"error": result.stderr.strip() or result.stdout.strip()}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Update timed out"}), 504
    except FileNotFoundError:
        return jsonify({"error": "pipx not found — install sdexe via pipx to use auto-update"}), 501
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Media API ──

@app.route("/api/info", methods=["POST"])
def info():
    url = request.json.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    # Normalise YouTube video+list URLs to pure playlist URLs
    # so extract_flat returns all entries instead of the single video
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "youtube.com") and "list" in parse_qs(parsed.query):
        qs = parse_qs(parsed.query)
        url = urlunparse(parsed._replace(path="/playlist", query=urlencode({"list": qs["list"][0]})))

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "socket_timeout": 12,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    entries_raw = data.get("entries")
    if entries_raw is not None:
        entries = []
        for entry in entries_raw:
            if not entry:
                continue
            vid = entry.get("id", "")
            # Get thumbnail from entry data; YouTube fallback if needed
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
            "entries": entries,
        })

    vid = data.get("id", "")
    thumbnail = data.get("thumbnail") or ""
    if not thumbnail and data.get("thumbnails"):
        thumbnail = data["thumbnails"][0].get("url", "")
    if not thumbnail and vid and ("youtube" in url or "youtu.be" in url):
        thumbnail = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    return jsonify({
        "type": "video",
        "title": data.get("title"),
        "thumbnail": thumbnail,
        "duration": data.get("duration"),
        "uploader": data.get("uploader") or data.get("channel"),
        "url": data.get("webpage_url") or url,
    })


@app.route("/api/download", methods=["POST"])
def download():
    url = request.json.get("url", "").strip()
    fmt = request.json.get("format", "mp3")
    quality = request.json.get("quality", "best")
    metadata = request.json.get("metadata") or {}
    subtitles = request.json.get("subtitles", False)

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    if not _check_download_rate():
        return jsonify({"error": "Too many downloads — slow down a bit."}), 429

    cleanup_old_files()

    dl_id = str(uuid.uuid4())
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
    }

    PP_NAMES = {
        "FFmpegExtractAudio": f"Converting to {fmt.upper()}",
        "FFmpegMerger": "Merging video + audio",
        "FFmpegVideoConvertor": "Converting video",
        "FFmpegMetadata": "Writing metadata",
        "FFmpegFixupM3u8": "Fixing stream",
        "FFmpegFixupM4a": "Fixing audio container",
        "FFmpegFixupStretchedPP": "Fixing aspect ratio",
        "FFmpegFixupTimestampPP": "Fixing timestamps",
        "FFmpegFixupDuplicateMoovPP": "Fixing MP4 structure",
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
        if d["status"] == "started":
            pp_name = d.get("postprocessor", "")
            downloads[dl_id]["pp_step"] += 1
            friendly = PP_NAMES.get(pp_name, pp_name)
            downloads[dl_id]["status"] = "processing"
            downloads[dl_id]["detail"] = friendly

    outtmpl = str(DOWNLOAD_DIR / f"{dl_id}.%(ext)s")
    common_hooks = {
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "writethumbnail": True,
    }

    if fmt == "mp4":
        if quality == "1080p":
            format_str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"
        elif quality == "720p":
            format_str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best"
        elif quality == "480p":
            format_str = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best"
        else:
            format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

        mp4_postprocessors = [{"key": "EmbedThumbnail"}]
        if subtitles:
            mp4_postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
        ydl_opts = {
            "format": format_str,
            "merge_output_format": "mp4",
            "outtmpl": outtmpl,
            "postprocessors": mp4_postprocessors,
            **({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en"]} if subtitles else {}),
            **common_hooks,
        }
    elif fmt == "flac":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "flac"},
                {"key": "EmbedThumbnail"},
            ],
            **common_hooks,
        }
    elif fmt == "wav":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "wav"},
            ],
            **common_hooks,
        }
    else:  # mp3
        bitrate = quality if quality in ("128", "192", "320") else "320"
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": bitrate},
                {"key": "EmbedThumbnail"},
            ],
            **common_hooks,
        }

    def do_download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                vid_info = ydl.extract_info(url, download=True)

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
                        import re as _re
                        try:
                            base_name = tmpl.format(title=title, artist=artist, album=album, uploader=uploader)
                        except (KeyError, ValueError):
                            base_name = title
                        base_name = _re.sub(r'[<>:"/\\|?*]', "_", base_name).strip(" .")
                        if not base_name:
                            base_name = "download"
                    else:
                        base_name = title
                    downloads[dl_id]["download_name"] = f"{base_name}.{ext}"
                    break

            # Clean up leftover thumbnail files
            for f in DOWNLOAD_DIR.iterdir():
                if f.stem == dl_id and f.suffix.lower() in thumb_exts:
                    f.unlink(missing_ok=True)

            # Embed metadata if provided
            meta = {}
            if metadata.get("title"):
                meta["title"] = metadata["title"]
            if metadata.get("artist"):
                meta["artist"] = metadata["artist"]
            if metadata.get("album"):
                meta["album"] = metadata["album"]
            if meta and downloads[dl_id].get("filename"):
                downloads[dl_id]["status"] = "metadata"
                filepath = DOWNLOAD_DIR / downloads[dl_id]["filename"]
                set_file_metadata(filepath, meta)

            # Auto-save to output folder if configured
            cfg = load_config()
            output_dir = cfg.get("output_folder", "").strip()
            if output_dir and downloads[dl_id].get("filename"):
                output_path = Path(output_dir).expanduser()
                if output_path.is_dir():
                    import shutil as _shutil
                    dest = output_path / downloads[dl_id]["download_name"]
                    _shutil.copy2(DOWNLOAD_DIR / downloads[dl_id]["filename"], dest)
                    downloads[dl_id]["auto_saved"] = True
                    downloads[dl_id]["saved_path"] = str(dest)

            downloads[dl_id]["status"] = "done"
            downloads[dl_id]["progress"] = 100
        except Exception as e:
            err = str(e)
            err_lower = err.lower()
            if downloads[dl_id].get("cancelled") or "cancelled by user" in err_lower:
                friendly = "Download cancelled."
            elif "private" in err_lower and "video" in err_lower:
                friendly = "This video is private."
            elif "age" in err_lower and any(w in err_lower for w in ("restrict", "confirm", "gate")):
                friendly = "Age-restricted — sign in to download."
            elif "not available in your country" in err_lower or "geo" in err_lower:
                friendly = "Not available in your country (geo-restricted)."
            elif "video unavailable" in err_lower:
                friendly = "Video unavailable or deleted."
            elif "copyright" in err_lower or "blocked" in err_lower:
                friendly = "Blocked due to copyright."
            elif "429" in err or "rate limit" in err_lower:
                friendly = "Rate limited — try again in a moment."
            elif "ffmpeg" in err_lower and ("not found" in err_lower or "no such file" in err_lower):
                friendly = "ffmpeg not found — run `sdexe` once to install it."
            else:
                friendly = err
            downloads[dl_id]["status"] = "error"
            downloads[dl_id]["error"] = friendly

    thread = threading.Thread(target=do_download, daemon=True)
    thread.start()

    return jsonify({"id": dl_id})


@app.route("/api/progress/<dl_id>")
def progress(dl_id):
    def stream():
        while True:
            info = downloads.get(dl_id)
            if not info:
                yield f"data: {json.dumps({'error': 'Unknown download'})}\n\n"
                break

            yield f"data: {json.dumps(info)}\n\n"

            if info["status"] in ("done", "error"):
                break

            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/cancel/<dl_id>", methods=["POST"])
def cancel_download(dl_id):
    info = downloads.get(dl_id)
    if not info:
        return jsonify({"error": "Unknown download"}), 404
    downloads[dl_id]["cancelled"] = True
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
    ids = request.json.get("ids", [])
    if not ids:
        return jsonify({"error": "No IDs provided"}), 400

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dl_id in ids:
            info = downloads.get(dl_id)
            if not info or not info.get("filename"):
                continue
            filepath = DOWNLOAD_DIR / info["filename"]
            if not filepath.exists():
                continue
            arcname = info.get("download_name") or info["filename"]
            zf.write(filepath, arcname)

    zip_buf.seek(0)
    return send_file(zip_buf, as_attachment=True, download_name="downloads.zip",
                     mimetype="application/zip")


# ── PDF API ──

@app.route("/api/pdf/merge", methods=["POST"])
def pdf_merge():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Need at least 2 PDF files"}), 400

    writer = PdfWriter()
    try:
        for f in files:
            reader = PdfReader(f.stream)
            for page in reader.pages:
                writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="merged.pdf",
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
        reader = PdfReader(f.stream)
        total_pages = len(reader.pages)
    except Exception as e:
        return jsonify({"error": f"Invalid PDF: {e}"}), 400

    # Parse page ranges
    page_groups = []
    if ranges_str:
        for part in ranges_str.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                start = max(1, int(start.strip()))
                end = min(total_pages, int(end.strip()))
                page_groups.append(list(range(start - 1, end)))
            else:
                p = int(part.strip())
                if 1 <= p <= total_pages:
                    page_groups.append([p - 1])
    else:
        # Split into individual pages
        page_groups = [[i] for i in range(total_pages)]

    if len(page_groups) == 1:
        # Return single PDF
        writer = PdfWriter()
        for p in page_groups[0]:
            writer.add_page(reader.pages[p])
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name="split.pdf",
                         mimetype="application/pdf")
    else:
        # Return ZIP of PDFs
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for idx, pages in enumerate(page_groups, 1):
                writer = PdfWriter()
                for p in pages:
                    writer.add_page(reader.pages[p])
                pdf_buf = io.BytesIO()
                writer.write(pdf_buf)
                zf.writestr(f"page_{idx}.pdf", pdf_buf.getvalue())
        zip_buf.seek(0)
        return send_file(zip_buf, as_attachment=True, download_name="split_pages.zip",
                         mimetype="application/zip")


@app.route("/api/pdf/images-to-pdf", methods=["POST"])
def images_to_pdf():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No images provided"}), 400

    images = []
    try:
        for f in files:
            img = Image.open(f.stream)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
    except Exception as e:
        return jsonify({"error": f"Invalid image: {e}"}), 400

    if not images:
        return jsonify({"error": "No valid images"}), 400

    buf = io.BytesIO()
    if len(images) == 1:
        images[0].save(buf, "PDF")
    else:
        images[0].save(buf, "PDF", save_all=True, append_images=images[1:])
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="images.pdf",
                     mimetype="application/pdf")


@app.route("/api/pdf/page-count", methods=["POST"])
def pdf_page_count():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        reader = PdfReader(f.stream)
        return jsonify({"pages": len(reader.pages)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/compress", methods=["POST"])
def pdf_compress():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        reader = PdfReader(f.stream)
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams()
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "document"
        return send_file(buf, as_attachment=True, download_name=f"{base}_compressed.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/to-text", methods=["POST"])
def pdf_to_text():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        reader = PdfReader(f.stream)
        parts = []
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"--- Page {i} ---\n{text.strip()}")
        combined = "\n\n".join(parts)
        if not combined:
            return jsonify({"error": "No extractable text found in this PDF"}), 400
        buf = io.BytesIO(combined.encode("utf-8"))
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "document"
        return send_file(buf, as_attachment=True, download_name=f"{base}.txt",
                         mimetype="text/plain")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/add-password", methods=["POST"])
def pdf_add_password():
    f = request.files.get("file")
    password = request.form.get("password", "").strip()
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    if not password:
        return jsonify({"error": "No password provided"}), 400
    try:
        reader = PdfReader(f.stream)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(password)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "document"
        return send_file(buf, as_attachment=True, download_name=f"{base}_protected.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/pdf/remove-password", methods=["POST"])
def pdf_remove_password():
    f = request.files.get("file")
    password = request.form.get("password", "").strip()
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        reader = PdfReader(f.stream)
        if reader.is_encrypted:
            result = reader.decrypt(password)
            if not result:
                return jsonify({"error": "Incorrect password"}), 400
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "document"
        return send_file(buf, as_attachment=True, download_name=f"{base}_unlocked.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Image API ──

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
            img = Image.open(f.stream)
        except Exception as e:
            return jsonify({"error": f"Invalid image {f.filename}: {e}"}), 400

        try:
            if mode == "percentage":
                pct = float(request.form.get("percentage", 100)) / 100
                new_w = max(1, int(img.width * pct))
                new_h = max(1, int(img.height * pct))
            else:
                new_w = request.form.get("width", "")
                new_h = request.form.get("height", "")
                if new_w and new_h:
                    new_w, new_h = int(new_w), int(new_h)
                    if maintain:
                        ratio = min(new_w / img.width, new_h / img.height)
                        new_w = max(1, int(img.width * ratio))
                        new_h = max(1, int(img.height * ratio))
                elif new_w:
                    new_w = int(new_w)
                    new_h = max(1, int(img.height * (new_w / img.width))) if maintain else img.height
                elif new_h:
                    new_h = int(new_h)
                    new_w = max(1, int(img.width * (new_h / img.height))) if maintain else img.width
                else:
                    return jsonify({"error": "Provide width, height, or percentage"}), 400
            img = img.resize((new_w, new_h), Image.LANCZOS)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

        fmt = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}
        pil_fmt = mime_map.get(fmt, "png")
        buf = io.BytesIO()
        save_img = img.convert("RGB") if pil_fmt == "jpeg" and img.mode == "RGBA" else img
        save_img.save(buf, pil_fmt.upper())
        buf.seek(0)
        out_name = f.filename.rsplit(".", 1)[0] + f"_resized.{fmt}" if "." in f.filename else "resized.png"
        results.append((out_name, buf, pil_fmt))

    if len(results) == 1:
        out_name, buf, pil_fmt = results[0]
        return send_file(buf, as_attachment=True, download_name=out_name,
                         mimetype=f"image/{pil_fmt}")
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for out_name, buf, _ in results:
                zf.writestr(out_name, buf.getvalue())
        zip_buf.seek(0)
        return send_file(zip_buf, as_attachment=True, download_name="resized_images.zip",
                         mimetype="application/zip")


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
            img = Image.open(f.stream)
            buf = io.BytesIO()
            fmt = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"

            if fmt in ("jpg", "jpeg"):
                if img.mode == "RGBA":
                    img = img.convert("RGB")
                img.save(buf, "JPEG", quality=quality, optimize=True)
            elif fmt == "webp":
                img.save(buf, "WEBP", quality=quality)
            else:
                img.save(buf, "PNG", optimize=True)

            buf.seek(0)
            out_name = f.filename.rsplit(".", 1)[0] + f"_compressed.{fmt}" if "." in f.filename else f"compressed.{fmt}"
            results.append((out_name, buf))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400

    original_size = sum(f.seek(0, 2) or f.tell() for f in files)
    if len(results) == 1:
        name, buf = results[0]
        fmt = name.rsplit(".", 1)[-1]
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}
        resp = send_file(buf, as_attachment=True, download_name=name,
                         mimetype=f"image/{mime_map.get(fmt, 'png')}")
        resp.headers["X-Original-Size"] = str(original_size)
        resp.headers["X-Compressed-Size"] = str(buf.getbuffer().nbytes)
        return resp
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, buf in results:
                zf.writestr(name, buf.getvalue())
        zip_buf.seek(0)
        return send_file(zip_buf, as_attachment=True, download_name="compressed_images.zip",
                         mimetype="application/zip")


@app.route("/api/images/convert", methods=["POST"])
def image_convert():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No images provided"}), 400

    target = request.form.get("format", "png").lower()
    if target not in ("png", "jpg", "webp"):
        return jsonify({"error": "Unsupported format"}), 400

    pil_fmt = "JPEG" if target == "jpg" else target.upper()

    results = []
    for f in files:
        try:
            img = Image.open(f.stream)
            if pil_fmt == "JPEG" and img.mode == "RGBA":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, pil_fmt)
            buf.seek(0)
            base = f.filename.rsplit(".", 1)[0] if "." in f.filename else f.filename
            out_name = f"{base}.{target}"
            results.append((out_name, buf))
        except Exception as e:
            return jsonify({"error": f"Error processing {f.filename}: {e}"}), 400

    if len(results) == 1:
        name, buf = results[0]
        mime_map = {"jpg": "jpeg", "png": "png", "webp": "webp"}
        return send_file(buf, as_attachment=True, download_name=name,
                         mimetype=f"image/{mime_map.get(target, 'png')}")
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, buf in results:
                zf.writestr(name, buf.getvalue())
        zip_buf.seek(0)
        return send_file(zip_buf, as_attachment=True, download_name=f"converted_{target}.zip",
                         mimetype="application/zip")


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

    html_body = md_lib.markdown(text, extensions=["tables", "fenced_code"])
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Converted Markdown</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #333; }}
  pre {{ background: #f5f5f5; padding: 16px; overflow-x: auto; border-radius: 4px; }}
  code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
  pre code {{ background: none; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  blockquote {{ border-left: 4px solid #ddd; margin: 16px 0; padding: 0 16px; color: #666; }}
  img {{ max-width: 100%; }}
  h1, h2, h3, h4, h5, h6 {{ margin-top: 24px; margin-bottom: 8px; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    buf = io.BytesIO(html_doc.encode("utf-8"))
    return send_file(buf, as_attachment=True, download_name="converted.html",
                     mimetype="text/html")


@app.route("/api/convert/csv-to-json", methods=["POST"])
def csv_to_json():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No CSV file provided"}), 400

    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        result = json.dumps(rows, indent=2, ensure_ascii=False)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    buf = io.BytesIO(result.encode("utf-8"))
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
    return send_file(buf, as_attachment=True, download_name=f"{base}.json",
                     mimetype="application/json")


@app.route("/api/convert/json-to-csv", methods=["POST"])
def json_to_csv():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No JSON file provided"}), 400

    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        if not isinstance(data, list):
            return jsonify({"error": "JSON must be an array of objects"}), 400

        # Collect all keys across objects for headers
        headers = []
        seen = set()
        for obj in data:
            if isinstance(obj, dict):
                for key in obj:
                    if key not in seen:
                        headers.append(key)
                        seen.add(key)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for obj in data:
            if isinstance(obj, dict):
                writer.writerow(obj)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    buf = io.BytesIO(output.getvalue().encode("utf-8"))
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
    return send_file(buf, as_attachment=True, download_name=f"{base}.csv",
                     mimetype="text/csv")


@app.route("/api/convert/md-preview", methods=["POST"])
def md_preview():
    text = request.form.get("text", "").strip()
    if not text:
        return jsonify({"error": "No text provided"}), 400
    html = md_lib.markdown(text, extensions=["tables", "fenced_code"])
    return jsonify({"html": html})


@app.route("/api/convert/yaml-to-json", methods=["POST"])
def yaml_to_json():
    if not _YAML_AVAILABLE:
        return jsonify({"error": "PyYAML not installed — run: pip install PyYAML"}), 501
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No YAML file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        data = _yaml.safe_load(text)
        result = json.dumps(data, indent=2, ensure_ascii=False)
        buf = io.BytesIO(result.encode("utf-8"))
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
        return send_file(buf, as_attachment=True, download_name=f"{base}.json",
                         mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/json-to-yaml", methods=["POST"])
def json_to_yaml():
    if not _YAML_AVAILABLE:
        return jsonify({"error": "PyYAML not installed — run: pip install PyYAML"}), 501
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No JSON file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        data = json.loads(text)
        result = _yaml.dump(data, default_flow_style=False, allow_unicode=True)
        buf = io.BytesIO(result.encode("utf-8"))
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
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
        rows = list(csv.reader(io.StringIO(text)))
        output = io.StringIO()
        csv.writer(output, delimiter="\t").writerows(rows)
        buf = io.BytesIO(output.getvalue().encode("utf-8"))
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
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
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        output = io.StringIO()
        csv.writer(output).writerows(rows)
        buf = io.BytesIO(output.getvalue().encode("utf-8"))
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
        return send_file(buf, as_attachment=True, download_name=f"{base}.csv",
                         mimetype="text/csv")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def _xml_to_dict(el):
    result = {}
    if el.attrib:
        result.update({f"@{k}": v for k, v in el.attrib.items()})
    children = list(el)
    if children:
        child_map = {}
        for child in children:
            cd = _xml_to_dict(child)
            if child.tag in child_map:
                existing = child_map[child.tag]
                if not isinstance(existing, list):
                    child_map[child.tag] = [existing]
                child_map[child.tag].append(cd)
            else:
                child_map[child.tag] = cd
        result.update(child_map)
    text = (el.text or "").strip()
    if text:
        result["_text"] = text if result else text
    return result or {}


@app.route("/api/convert/xml-to-json", methods=["POST"])
def xml_to_json():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No XML file provided"}), 400
    try:
        text = f.stream.read().decode("utf-8", errors="replace")
        root = ET.fromstring(text)
        data = {root.tag: _xml_to_dict(root)}
        result = json.dumps(data, indent=2, ensure_ascii=False)
        buf = io.BytesIO(result.encode("utf-8"))
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "data"
        return send_file(buf, as_attachment=True, download_name=f"{base}.json",
                         mimetype="application/json")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── AV API ──

def _run_ffmpeg_route(input_data, in_suffix, out_suffix, ffmpeg_args, download_name, timeout=300):
    """Write input to temp file, run ffmpeg, return send_file."""
    with tempfile.NamedTemporaryFile(suffix=in_suffix, delete=False) as inf:
        inf.write(input_data)
        inf_path = inf.name
    with tempfile.NamedTemporaryFile(suffix=out_suffix, delete=False) as outf:
        out_path = outf.name
    try:
        cmd = ["ffmpeg", "-y", "-i", inf_path] + ffmpeg_args + [out_path]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            raise Exception(result.stderr.decode("utf-8", errors="replace").strip())
        buf = io.BytesIO(Path(out_path).read_bytes())
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=download_name)
    finally:
        Path(inf_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


@app.route("/api/av/convert-audio", methods=["POST"])
def av_convert_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    fmt = request.form.get("format", "mp3").lower()
    if fmt not in ("mp3", "wav", "ogg", "flac", "aac", "m4a"):
        return jsonify({"error": "Unsupported format"}), 400
    codec_map = {
        "mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
        "wav": ["-codec:a", "pcm_s16le"],
        "ogg": ["-codec:a", "libvorbis", "-q:a", "6"],
        "flac": ["-codec:a", "flac"],
        "aac": ["-codec:a", "aac", "-b:a", "192k"],
        "m4a": ["-codec:a", "aac", "-b:a", "192k"],
    }
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "bin"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "audio"
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", f".{fmt}",
            ["-map", "0:a"] + codec_map[fmt],
            f"{base}.{fmt}",
        )
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
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "mp3"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "audio"
    args = ["-ss", start]
    if end:
        args += ["-to", end]
    args += ["-map", "0:a", "-c", "copy"]
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", f".{ext}",
            args, f"{base}_trimmed.{ext}",
        )
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
    if speed_f < 0.25 or speed_f > 4.0:
        return jsonify({"error": "Speed must be between 0.25 and 4.0"}), 400
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "mp3"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "audio"
    # atempo only supports 0.5–2.0; chain filters if outside that range
    if 0.5 <= speed_f <= 2.0:
        atempo_chain = f"atempo={speed_f}"
    elif speed_f < 0.5:
        atempo_chain = f"atempo=0.5,atempo={speed_f / 0.5:.4f}"
    else:
        atempo_chain = f"atempo=2.0,atempo={speed_f / 2.0:.4f}"
    out_ext = ext if ext in ("mp3", "wav", "ogg", "flac") else "mp3"
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", f".{out_ext}",
            ["-map", "0:a", "-filter:a", atempo_chain],
            f"{base}_{speed}x.{out_ext}",
        )
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/extract-audio", methods=["POST"])
def av_extract_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    fmt = request.form.get("format", "mp3").lower()
    if fmt not in ("mp3", "wav", "ogg", "flac", "aac", "m4a"):
        return jsonify({"error": "Unsupported format"}), 400
    codec_map = {
        "mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
        "wav": ["-codec:a", "pcm_s16le"],
        "ogg": ["-codec:a", "libvorbis", "-q:a", "6"],
        "flac": ["-codec:a", "flac"],
        "aac": ["-codec:a", "aac", "-b:a", "192k"],
        "m4a": ["-codec:a", "aac", "-b:a", "192k"],
    }
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "mp4"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "video"
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", f".{fmt}",
            ["-vn", "-map", "0:a"] + codec_map[fmt],
            f"{base}_audio.{fmt}",
        )
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
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "mp4"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "video"
    args = ["-ss", start]
    if end:
        args += ["-to", end]
    args += ["-c", "copy"]
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", f".{ext}",
            args, f"{base}_trimmed.{ext}", timeout=300,
        )
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/compress-video", methods=["POST"])
def av_compress_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    quality = request.form.get("quality", "medium")
    crf_map = {"high": "18", "medium": "23", "low": "28"}
    crf = crf_map.get(quality, "23")
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "mp4"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "video"
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", ".mp4",
            ["-vcodec", "libx264", "-crf", crf, "-preset", "fast", "-acodec", "aac"],
            f"{base}_compressed.mp4", timeout=300,
        )
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


@app.route("/api/av/convert-video", methods=["POST"])
def av_convert_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    fmt = request.form.get("format", "mp4").lower()
    if fmt not in ("mp4", "webm", "avi", "mov"):
        return jsonify({"error": "Unsupported format"}), 400
    codec_map = {
        "mp4": ["-vcodec", "libx264", "-acodec", "aac"],
        "webm": ["-vcodec", "libvpx-vp9", "-acodec", "libopus"],
        "avi": ["-vcodec", "mpeg4", "-acodec", "mp3"],
        "mov": ["-vcodec", "libx264", "-acodec", "aac"],
    }
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "mp4"
    base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "video"
    try:
        return _run_ffmpeg_route(
            f.stream.read(), f".{ext}", f".{fmt}",
            codec_map[fmt], f"{base}.{fmt}", timeout=300,
        )
    except Exception as e:
        return jsonify({"error": str(e)[-500:]}), 500


# ── Image extras ──

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
        img = Image.open(f.stream)
        if right <= 0:
            right = img.width
        if bottom <= 0:
            bottom = img.height
        cropped = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        fmt = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
        pil_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}
        pil_fmt = pil_map.get(fmt, "PNG")
        save_img = cropped.convert("RGB") if pil_fmt == "JPEG" and cropped.mode == "RGBA" else cropped
        save_img.save(buf, pil_fmt)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "image"
        mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
        return send_file(buf, as_attachment=True, download_name=f"{base}_cropped.{fmt}", mimetype=mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/rotate", methods=["POST"])
def image_rotate():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        angle = int(request.form.get("angle", 90))
    except ValueError:
        return jsonify({"error": "Invalid angle"}), 400
    try:
        img = Image.open(f.stream)
        rotated = img.rotate(-angle, expand=True)
        buf = io.BytesIO()
        fmt = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "png"
        pil_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}
        pil_fmt = pil_map.get(fmt, "PNG")
        save_img = rotated.convert("RGB") if pil_fmt == "JPEG" and rotated.mode == "RGBA" else rotated
        save_img.save(buf, pil_fmt)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "image"
        mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
        return send_file(buf, as_attachment=True, download_name=f"{base}_rotated.{fmt}", mimetype=mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/strip-exif", methods=["POST"])
def image_strip_exif():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        img = Image.open(f.stream)
        new_img = Image.new(img.mode, img.size)
        new_img.putdata(list(img.getdata()))
        buf = io.BytesIO()
        fmt = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else "jpg"
        pil_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}
        pil_fmt = pil_map.get(fmt, "PNG")
        if pil_fmt == "JPEG":
            new_img.save(buf, "JPEG", quality=95)
        else:
            new_img.save(buf, pil_fmt)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "image"
        mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
        return send_file(buf, as_attachment=True, download_name=f"{base}_clean.{fmt}", mimetype=mime)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


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
        img = Image.open(f.stream).convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="ICO", sizes=[(s, s) for s in sizes])
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "icon"
        return send_file(buf, as_attachment=True, download_name=f"{base}.ico", mimetype="image/x-icon")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── PDF extras ──

@app.route("/api/pdf/rotate", methods=["POST"])
def pdf_rotate():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        angle = int(request.form.get("angle", 90))
    except ValueError:
        return jsonify({"error": "Invalid angle"}), 400
    if angle not in (90, 180, 270):
        return jsonify({"error": "Angle must be 90, 180, or 270"}), 400
    pages_str = request.form.get("pages", "all").strip()
    try:
        reader = PdfReader(f.stream)
        writer = PdfWriter()
        total = len(reader.pages)
        if pages_str == "all":
            page_indices = set(range(total))
        else:
            page_indices = set()
            for part in pages_str.split(","):
                part = part.strip()
                if "-" in part:
                    s, e = part.split("-", 1)
                    page_indices.update(range(int(s.strip()) - 1, int(e.strip())))
                elif part:
                    page_indices.add(int(part) - 1)
            page_indices = {i for i in page_indices if 0 <= i < total}
        for i, page in enumerate(reader.pages):
            if i in page_indices:
                page.rotate(angle)
            writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "document"
        return send_file(buf, as_attachment=True, download_name=f"{base}_rotated.pdf",
                         mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Archive convert ──

@app.route("/api/convert/zip", methods=["POST"])
def convert_zip():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400
    try:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.writestr(f.filename or "file", f.stream.read())
        zip_buf.seek(0)
        return send_file(zip_buf, as_attachment=True, download_name="archive.zip",
                         mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/convert/unzip", methods=["POST"])
def convert_unzip():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No ZIP file provided"}), 400
    try:
        zf = zipfile.ZipFile(io.BytesIO(f.stream.read()))
        members = [m for m in zf.namelist() if not m.endswith("/")]
        if not members:
            return jsonify({"error": "ZIP file is empty"}), 400
        if len(members) == 1:
            data = zf.read(members[0])
            name = Path(members[0]).name
            buf = io.BytesIO(data)
            return send_file(buf, as_attachment=True, download_name=name)
        else:
            out_buf = io.BytesIO()
            with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out_zf:
                for member in members:
                    out_zf.writestr(Path(member).name, zf.read(member))
            out_buf.seek(0)
            base = f.filename.rsplit(".", 1)[0] if "." in f.filename else "archive"
            return send_file(out_buf, as_attachment=True, download_name=f"{base}_extracted.zip",
                             mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def _check_ffmpeg(console):
    import shutil
    import sys
    import subprocess
    from rich.prompt import Confirm

    if shutil.which("ffmpeg"):
        return

    console.print("  [yellow]⚠[/yellow]  [bold]ffmpeg[/bold] not found — needed for media downloads.\n")

    if not Confirm.ask("  Install ffmpeg now?", default=True):
        console.print("  [dim]Skipping. Media downloads may not work.[/dim]\n")
        return

    platform = sys.platform
    success = False

    if platform == "darwin" and shutil.which("brew"):
        with console.status("  Installing via Homebrew...", spinner="dots"):
            r = subprocess.run(["brew", "install", "ffmpeg"], capture_output=True)
            success = r.returncode == 0
    elif platform == "darwin":
        console.print("  [dim]Homebrew not found. Run:[/dim] [cyan]brew install ffmpeg[/cyan]\n")
        return
    elif platform.startswith("linux"):
        with console.status("  Installing via apt...", spinner="dots"):
            r = subprocess.run(
                ["sudo", "apt-get", "install", "-y", "ffmpeg"],
                capture_output=True,
            )
            success = r.returncode == 0
    else:
        console.print("  [dim]Install ffmpeg from[/dim] [cyan]https://ffmpeg.org/download.html[/cyan]\n")
        return

    if success:
        console.print("  [green]✓[/green]  ffmpeg installed!\n")
    else:
        console.print("  [red]✗[/red]  Installation failed. Please install ffmpeg manually.\n")


def _check_for_updates(console):
    import urllib.request
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/sdexe/json", timeout=3) as r:
            data = json.loads(r.read())
        latest = data["info"]["version"]
        if latest != __version__:
            console.print(
                f"  [yellow]↑[/yellow]  Update available: [dim]v{__version__}[/dim] → "
                f"[bold]v{latest}[/bold]  [dim]Run:[/dim] [cyan]pipx upgrade sdexe[/cyan]\n"
            )
    except Exception:
        pass


def _run_tray(port):
    try:
        import pystray
        from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont
        import webbrowser as _wb

        size = 64
        img = _Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = _ImageDraw.Draw(img)
        draw.ellipse([2, 2, size - 2, size - 2], fill=(30, 30, 40, 255))

        # Try to load a system font for "sd" text
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
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("Open sdexe", open_app, default=True),
            pystray.MenuItem("Quit", quit_app),
        )
        icon = pystray.Icon("sdexe", img, "sdexe", menu)
        icon.run()
        return True
    except Exception:
        return False


def main():
    import logging
    import threading
    import webbrowser
    from rich.console import Console
    from rich.panel import Panel

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    console = Console()
    port = 5001

    console.print()
    console.print(
        Panel.fit(
            f"[bold blue]sdexe[/bold blue]  [dim]v{__version__}[/dim]\n"
            "[dim]Local tools for media, PDF, images & files[/dim]",
            border_style="blue",
            padding=(0, 2),
        )
    )
    console.print()

    _check_ffmpeg(console)
    _check_for_updates(console)

    console.print(f"  [dim]Starting →[/dim] [cyan]http://127.0.0.1:{port}[/cyan]\n")
    webbrowser.open(f"http://127.0.0.1:{port}")

    # Try to run Flask in a thread + system tray on main thread
    try:
        import pystray  # noqa: F401 — just checking availability
        flask_thread = threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False),
            daemon=True,
        )
        flask_thread.start()
        _run_tray(port)
    except ImportError:
        app.run(host="127.0.0.1", port=port, use_reloader=False)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
