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
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

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

DOWNLOAD_DIR = Path(tempfile.mkdtemp(prefix="toolkit_"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

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

# Stores progress and file info keyed by download ID
downloads = {}


def cleanup_old_files(max_age_seconds=3600):
    """Delete downloaded files older than max_age_seconds."""
    now = time.time()
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
            f.unlink(missing_ok=True)


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


# ── Config API ──

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())

@app.route("/api/config", methods=["POST"])
def set_config_route():
    cfg = load_config()
    cfg.update(request.json or {})
    save_config(cfg)
    return jsonify({"ok": True})


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
    else:  # mp3 — 320kbps CBR
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"},
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
                    ext = f.suffix.lstrip(".")
                    downloads[dl_id]["download_name"] = f"{title}.{ext}"
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
            if "private" in err_lower and "video" in err_lower:
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


# ── Image API ──

@app.route("/api/images/resize", methods=["POST"])
def image_resize():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400

    try:
        img = Image.open(f.stream)
    except Exception as e:
        return jsonify({"error": f"Invalid image: {e}"}), 400

    mode = request.form.get("mode", "dimensions")
    maintain = request.form.get("maintain_aspect", "true") == "true"

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
    return send_file(buf, as_attachment=True, download_name=out_name,
                     mimetype=f"image/{pil_fmt}")


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

    if len(results) == 1:
        name, buf = results[0]
        fmt = name.rsplit(".", 1)[-1]
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}
        return send_file(buf, as_attachment=True, download_name=name,
                         mimetype=f"image/{mime_map.get(fmt, 'png')}")
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


def main():
    import logging
    import webbrowser
    from rich.console import Console
    from rich.panel import Panel

    # Suppress werkzeug startup noise
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

    console.print(f"  [dim]Starting →[/dim] [cyan]http://localhost:{port}[/cyan]\n")
    webbrowser.open(f"http://localhost:{port}")
    app.run(port=port, use_reloader=False)


if __name__ == "__main__":
    app.run(debug=True, port=5001)
