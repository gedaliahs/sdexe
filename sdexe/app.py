import os
import io
import uuid
import time
import tempfile
import threading
import json
import subprocess
import zipfile
import atexit
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from flask import Flask, render_template, request, jsonify, send_file, Response
import yt_dlp
from PIL import Image

from sdexe import __version__
from sdexe import tools

app = Flask(__name__)


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
    import sys as _sys
    info = {
        "python_ver": f"{_sys.version_info.major}.{_sys.version_info.minor}.{_sys.version_info.micro}",
        "ffmpeg_ver": "not found",
        "ytdlp_ver": "unknown",
        "tool_count": sum(1 for r in app.url_map.iter_rules() if r.endpoint != "static"),
        "config_dir": str(CONFIG_DIR),
    }
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        info["ffmpeg_ver"] = out.stdout.split("\n")[0].split("version ")[-1].split(" ")[0] if out.returncode == 0 else "not found"
    except Exception:
        pass
    try:
        info["ytdlp_ver"] = yt_dlp.version.__version__
    except Exception:
        pass
    return render_template("settings.html", info=info)


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
        images = [Image.open(f.stream) for f in files]
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
    password = request.form.get("password", "").strip()
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
    password = request.form.get("password", "").strip()
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
                keywords=request.form.get("keywords", ""),
                creator=request.form.get("creator", ""),
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
        fmt = tools._ext_from_filename(filename)
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
            img = Image.open(f.stream)
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

        fmt = tools._ext_from_filename(f.filename)
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
            img = Image.open(f.stream)
            fmt = tools._ext_from_filename(f.filename)
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
            img = Image.open(f.stream)
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
        img = Image.open(f.stream)
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
            img = Image.open(f.stream)
            rotated = tools.rotate_image(img, angle)
            fmt = tools._ext_from_filename(f.filename)
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
        img = Image.open(f.stream)
        clean = tools.strip_exif(img)
        fmt = tools._ext_from_filename(f.filename, "jpg")
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
            img = Image.open(f.stream)
            flipped = tools.flip_image(img, direction)
            fmt = tools._ext_from_filename(f.filename)
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
            img = Image.open(f.stream)
            gray = tools.grayscale_image(img)
            fmt = tools._ext_from_filename(f.filename)
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
            img = Image.open(f.stream)
            blurred = tools.blur_image(img, radius)
            fmt = tools._ext_from_filename(f.filename)
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
        img = Image.open(f.stream)
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
        img = Image.open(f.stream)
        result = tools.watermark_image(img, text, position=position,
                                       opacity=opacity, font_size=font_size)
        # Convert back from RGBA for output
        fmt = tools._ext_from_filename(f.filename)
        if fmt in ("jpg", "jpeg"):
            result = result.convert("RGB")
        return _image_response(result, f.filename, "watermarked")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/info", methods=["POST"])
def image_info_route():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        img = Image.open(f.stream)
        return jsonify(tools.image_info(img))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/adjust", methods=["POST"])
def image_adjust():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        brightness = float(request.form.get("brightness", 1.0))
        contrast = float(request.form.get("contrast", 1.0))
        sharpness = float(request.form.get("sharpness", 1.0))
    except ValueError:
        return jsonify({"error": "Invalid adjustment values"}), 400
    try:
        img = Image.open(f.stream)
        adjusted = tools.adjust_image(img, brightness=brightness,
                                      contrast=contrast, sharpness=sharpness)
        return _image_response(adjusted, f.filename, "adjusted")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/images/qr-generate", methods=["POST"])
def qr_generate():
    data = request.json or {}
    text = data.get("text", "").strip()
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
    data = request.json or {}
    width = int(data.get("width", 800))
    height = int(data.get("height", 600))
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


# ── Startup helpers ──

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


def _find_free_port(host, start_port, max_tries=20):
    """Find a free port starting from start_port."""
    import socket
    for offset in range(max_tries):
        port = start_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return None


def _print_startup_info(console, host, port):
    """Print a Rich info table with environment details."""
    import shutil
    import sys
    from rich.table import Table

    ffmpeg_ver = "not found"
    if shutil.which("ffmpeg"):
        try:
            r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
            line = r.stdout.split("\n")[0] if r.stdout else ""
            parts = line.split()
            if len(parts) >= 3:
                ffmpeg_ver = parts[2]
        except Exception:
            ffmpeg_ver = "installed"

    ytdlp_ver = "unknown"
    try:
        ytdlp_ver = yt_dlp.version.__version__
    except Exception:
        pass

    route_count = sum(1 for rule in app.url_map.iter_rules() if rule.endpoint != "static")

    table = Table(show_header=False, box=None, padding=(0, 2), expand=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    table.add_row("ffmpeg", ffmpeg_ver)
    table.add_row("yt-dlp", ytdlp_ver)
    table.add_row("Tools", str(route_count))
    table.add_row("Config", str(CONFIG_DIR))
    table.add_row("Server", f"[cyan]http://{host}:{port}[/cyan]")

    console.print(table)
    console.print()


def main():
    import argparse
    import logging
    import signal
    import sys
    import threading
    import webbrowser
    from rich.console import Console
    from rich.panel import Panel

    parser = argparse.ArgumentParser(
        prog="sdexe",
        description="Local tools for media, PDF, images & files",
    )
    parser.add_argument("-V", "--version", action="version", version=f"sdexe {__version__}")
    parser.add_argument("-p", "--port", type=int, default=5001, help="server port (default: 5001)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true", help="don't open browser on start")
    parser.add_argument("--no-tray", action="store_true", help="skip system tray, run Flask on main thread")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress startup banner")
    parser.add_argument("--open", metavar="PAGE", help="open specific page (e.g. pdf, images, text)")

    args = parser.parse_args()

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    console = Console()
    host = args.host
    port = args.port

    # Graceful Ctrl+C
    def _sigint_handler(sig, frame):
        console.print("\n  [dim]Shutting down...[/dim]")
        sys.exit(0)
    signal.signal(signal.SIGINT, _sigint_handler)

    if not args.quiet:
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

    # Port auto-detection
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            original_port = port
            port = _find_free_port(host, port + 1)
            if port is None:
                console.print(f"  [red]Error:[/red] Port {original_port} is in use and no free port found nearby.")
                sys.exit(1)
            if not args.quiet:
                console.print(f"  [yellow]Port {original_port} in use, using {port} instead[/yellow]\n")

    if not args.quiet:
        _print_startup_info(console, host, port)

    # Determine URL to open
    open_path = ""
    if args.open:
        open_path = f"/{args.open.strip('/')}"
    url = f"http://{host}:{port}{open_path}"

    if not args.no_browser:
        webbrowser.open(url)

    # Start server
    if args.no_tray:
        app.run(host=host, port=port, use_reloader=False)
    else:
        try:
            import pystray  # noqa: F401 — just checking availability
            flask_thread = threading.Thread(
                target=lambda: app.run(host=host, port=port, use_reloader=False),
                daemon=True,
            )
            flask_thread.start()
            _run_tray(port)
        except ImportError:
            app.run(host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
