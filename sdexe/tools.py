"""Pure tool functions shared between web routes and CLI subcommands."""

import io
import csv
import json
import tempfile
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader, PdfWriter
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont
import markdown as md_lib

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ── Helpers ──

_PIL_FMT_MAP = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}
_MIME_MAP = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def _ext_from_filename(filename: str, default: str = "png") -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else default


def _base_from_filename(filename: str, default: str = "file") -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else default


def _ensure_processable(img: Image.Image) -> Image.Image:
    """Convert palette, CMYK, and other exotic modes to RGB/RGBA for processing."""
    if img.mode in ("P", "PA"):
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    if img.mode in ("CMYK", "YCbCr", "LAB", "HSV"):
        return img.convert("RGB")
    if img.mode == "I":
        return img.convert("L")
    return img


def _save_image(img: Image.Image, fmt: str) -> bytes:
    """Save a PIL Image to bytes in the given format string (e.g. 'png', 'jpg')."""
    pil_fmt = _PIL_FMT_MAP.get(fmt, "PNG")
    buf = io.BytesIO()
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "PA", "P"):
        save_img = img.convert("RGB")
    elif pil_fmt == "GIF":
        save_img = img
    elif img.mode in ("CMYK", "YCbCr", "LAB", "HSV", "I"):
        save_img = img.convert("RGB")
    elif img.mode in ("P", "PA") and pil_fmt == "PNG":
        save_img = img  # PNG supports palette
    else:
        save_img = img
    save_img.save(buf, pil_fmt)
    return buf.getvalue()


# ── PDF Tools ──

def merge_pdfs(streams: list[BinaryIO]) -> bytes:
    """Merge multiple PDF streams into one PDF. Returns PDF bytes."""
    writer = PdfWriter()
    for stream in streams:
        for page in PdfReader(stream).pages:
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def split_pdf(stream: BinaryIO, ranges_str: str = "") -> list[tuple[str, bytes]]:
    """Split a PDF by page ranges. Returns list of (filename, pdf_bytes).
    If ranges_str is empty, splits into individual pages.
    """
    reader = PdfReader(stream)
    total = len(reader.pages)

    page_groups = []
    if ranges_str:
        for part in ranges_str.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                start = max(1, int(start.strip()))
                end = min(total, int(end.strip()))
                page_groups.append(list(range(start - 1, end)))
            else:
                p = int(part.strip())
                if 1 <= p <= total:
                    page_groups.append([p - 1])
    else:
        page_groups = [[i] for i in range(total)]

    results = []
    for idx, pages in enumerate(page_groups, 1):
        writer = PdfWriter()
        for p in pages:
            writer.add_page(reader.pages[p])
        buf = io.BytesIO()
        writer.write(buf)
        results.append((f"page_{idx}.pdf", buf.getvalue()))
    return results


def images_to_pdf(images: list[Image.Image]) -> bytes:
    """Convert PIL Images to a single PDF. Returns PDF bytes."""
    rgb_images = []
    for img in images:
        rgb_images.append(img.convert("RGB") if img.mode != "RGB" else img)
    buf = io.BytesIO()
    if len(rgb_images) == 1:
        rgb_images[0].save(buf, "PDF")
    else:
        rgb_images[0].save(buf, "PDF", save_all=True, append_images=rgb_images[1:])
    return buf.getvalue()


def pdf_page_count(stream: BinaryIO) -> int:
    return len(PdfReader(stream).pages)


def compress_pdf(stream: BinaryIO) -> bytes:
    reader = PdfReader(stream)
    writer = PdfWriter()
    for page in reader.pages:
        page.compress_content_streams()
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def pdf_to_text(stream: BinaryIO) -> str:
    """Extract text from all pages, with page markers."""
    reader = PdfReader(stream)
    parts = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"--- Page {i} ---\n{text.strip()}")
    return "\n\n".join(parts)


def add_pdf_password(stream: BinaryIO, password: str) -> bytes:
    reader = PdfReader(stream)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def remove_pdf_password(stream: BinaryIO, password: str) -> bytes:
    reader = PdfReader(stream)
    if reader.is_encrypted:
        result = reader.decrypt(password)
        if not result:
            raise ValueError("Incorrect password")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def rotate_pdf(stream: BinaryIO, angle: int, pages_str: str = "all") -> bytes:
    if angle not in (90, 180, 270):
        raise ValueError("Angle must be 90, 180, or 270")
    reader = PdfReader(stream)
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
    return buf.getvalue()


def reorder_pdf(stream: BinaryIO, order: list[int]) -> bytes:
    """Reorder pages. order is 1-based list of page numbers."""
    reader = PdfReader(stream)
    total = len(reader.pages)
    writer = PdfWriter()
    for num in order:
        idx = num - 1
        if idx < 0 or idx >= total:
            raise ValueError(f"Page {num} out of range (1-{total})")
        writer.add_page(reader.pages[idx])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def delete_pdf_pages(stream: BinaryIO, pages_str: str) -> bytes:
    """Delete specific pages. pages_str like '2,5,7-10' (1-based)."""
    reader = PdfReader(stream)
    total = len(reader.pages)
    to_delete = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            s, e = part.split("-", 1)
            to_delete.update(range(int(s.strip()) - 1, int(e.strip())))
        elif part:
            to_delete.add(int(part) - 1)
    to_delete = {i for i in to_delete if 0 <= i < total}
    if len(to_delete) >= total:
        raise ValueError("Cannot delete all pages")
    writer = PdfWriter()
    for i, page in enumerate(reader.pages):
        if i not in to_delete:
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def get_pdf_metadata(stream: BinaryIO) -> dict:
    """Get PDF metadata as a dict."""
    reader = PdfReader(stream)
    meta = reader.metadata or {}
    return {
        "title": meta.get("/Title", "") or "",
        "author": meta.get("/Author", "") or "",
        "subject": meta.get("/Subject", "") or "",
        "keywords": meta.get("/Keywords", "") or "",
        "creator": meta.get("/Creator", "") or "",
        "producer": meta.get("/Producer", "") or "",
        "pages": len(reader.pages),
    }


def set_pdf_metadata(stream: BinaryIO, title: str = "", author: str = "",
                     subject: str = "", keywords: str = "",
                     creator: str = "") -> bytes:
    """Set PDF metadata. Returns new PDF bytes."""
    reader = PdfReader(stream)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    meta = {
        "/Title": title,
        "/Author": author,
        "/Subject": subject,
        "/Keywords": keywords,
    }
    if creator:
        meta["/Creator"] = creator
    writer.add_metadata(meta)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def watermark_pdf(stream: BinaryIO, text: str, font_size: int = 36,
                  opacity: float = 0.3, position: str = "center") -> bytes:
    """Add text watermark to every page of a PDF."""
    reader = PdfReader(stream)
    writer = PdfWriter()

    for page in reader.pages:
        box = page.mediabox
        w = float(box.width)
        h = float(box.height)

        # Create watermark as a PDF page using reportlab-free approach:
        # Build a small single-page PDF with the watermark text
        wm_img = Image.new("RGBA", (int(w), int(h)), (255, 255, 255, 0))
        draw = ImageDraw.Draw(wm_img)
        alpha = max(1, min(255, int(opacity * 255)))

        font = None
        for fp in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]:
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        if position == "center":
            x, y = (w - tw) / 2, (h - th) / 2
        elif position == "top-left":
            x, y = 40, 40
        elif position == "top-right":
            x, y = w - tw - 40, 40
        elif position == "bottom-left":
            x, y = 40, h - th - 40
        elif position == "bottom-right":
            x, y = w - tw - 40, h - th - 40
        else:
            x, y = (w - tw) / 2, (h - th) / 2

        draw.text((x, y), text, fill=(128, 128, 128, alpha), font=font)

        # Convert watermark image to PDF page
        wm_rgb = Image.new("RGB", wm_img.size, (255, 255, 255))
        wm_rgb.paste(wm_img, mask=wm_img.split()[3])
        wm_buf = io.BytesIO()
        wm_rgb.save(wm_buf, "PDF")
        wm_buf.seek(0)
        wm_page = PdfReader(wm_buf).pages[0]

        page.merge_page(wm_page)
        writer.add_page(page)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── Image Tools ──

def resize_image(img: Image.Image, mode: str = "dimensions",
                 width: int = 0, height: int = 0,
                 percentage: float = 100,
                 maintain_aspect: bool = True) -> Image.Image:
    if mode == "percentage":
        pct = percentage / 100
        new_w = max(1, int(img.width * pct))
        new_h = max(1, int(img.height * pct))
    else:
        if width and height:
            new_w, new_h = width, height
            if maintain_aspect:
                ratio = min(new_w / img.width, new_h / img.height)
                new_w = max(1, int(img.width * ratio))
                new_h = max(1, int(img.height * ratio))
        elif width:
            new_w = width
            new_h = max(1, int(img.height * (width / img.width))) if maintain_aspect else img.height
        elif height:
            new_h = height
            new_w = max(1, int(img.width * (height / img.height))) if maintain_aspect else img.width
        else:
            raise ValueError("Provide width, height, or percentage")
    return img.resize((new_w, new_h), Image.LANCZOS)


def compress_image(img: Image.Image, quality: int, fmt: str) -> bytes:
    """Compress image. quality: 0-100, fmt: file extension string."""
    buf = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(buf, "JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        img = _ensure_processable(img)
        img.save(buf, "WEBP", quality=quality)
    else:
        img = _ensure_processable(img)
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def convert_image(img: Image.Image, target: str) -> bytes:
    """Convert image to target format. target: 'png', 'jpg', 'webp'."""
    pil_fmt = "JPEG" if target == "jpg" else target.upper()
    if pil_fmt == "JPEG" and img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif pil_fmt in ("PNG", "WEBP"):
        img = _ensure_processable(img)
    buf = io.BytesIO()
    img.save(buf, pil_fmt)
    return buf.getvalue()


def crop_image(img: Image.Image, left: int, top: int, right: int, bottom: int) -> Image.Image:
    if right <= 0:
        right = img.width
    if bottom <= 0:
        bottom = img.height
    return img.crop((left, top, right, bottom))


def rotate_image(img: Image.Image, angle: int) -> Image.Image:
    return img.rotate(-angle, expand=True)


def strip_exif(img: Image.Image) -> Image.Image:
    new_img = Image.new(img.mode, img.size)
    if img.mode == "P":
        new_img.putpalette(img.getpalette())
    new_img.putdata(list(img.getdata()))
    return new_img


def image_to_ico(img: Image.Image, sizes: list[int] | None = None) -> bytes:
    if sizes is None:
        sizes = [16, 32, 48, 64, 128, 256]
    img = img.convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="ICO", sizes=[(s, s) for s in sizes])
    return buf.getvalue()


def flip_image(img: Image.Image, direction: str = "horizontal") -> Image.Image:
    img = _ensure_processable(img)
    if direction == "vertical":
        return img.transpose(Image.FLIP_TOP_BOTTOM)
    return img.transpose(Image.FLIP_LEFT_RIGHT)


def grayscale_image(img: Image.Image) -> Image.Image:
    return img.convert("L")


def blur_image(img: Image.Image, radius: float = 5.0) -> Image.Image:
    img = _ensure_processable(img)
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def watermark_image(img: Image.Image, text: str, position: str = "center",
                    opacity: int = 128, font_size: int = 36) -> Image.Image:
    """Add text watermark to an image."""
    overlay = Image.new("RGBA", img.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    font = None
    for fp in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    positions = {
        "center": ((img.width - tw) / 2, (img.height - th) / 2),
        "top-left": (20, 20),
        "top-right": (img.width - tw - 20, 20),
        "bottom-left": (20, img.height - th - 20),
        "bottom-right": (img.width - tw - 20, img.height - th - 20),
    }
    x, y = positions.get(position, positions["center"])
    draw.text((x, y), text, fill=(255, 255, 255, opacity), font=font)

    if img.mode != "RGBA":
        img = img.convert("RGBA")
    result = Image.alpha_composite(img, overlay)
    return result


def image_info(img: Image.Image) -> dict:
    """Get image metadata info."""
    info = {
        "width": img.width,
        "height": img.height,
        "format": img.format or "unknown",
        "mode": img.mode,
    }
    exif = {}
    try:
        from PIL.ExifTags import TAGS
        raw_exif = img.getexif()
        for tag_id, value in raw_exif.items():
            tag = TAGS.get(tag_id, tag_id)
            try:
                exif[str(tag)] = str(value)
            except Exception:
                pass
    except Exception:
        pass
    info["exif"] = exif
    return info


def adjust_image(img: Image.Image, brightness: float = 1.0,
                 contrast: float = 1.0, sharpness: float = 1.0) -> Image.Image:
    """Adjust brightness, contrast, and sharpness. 1.0 = original."""
    img = _ensure_processable(img)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return img


# ── Conversion Tools ──

def md_to_html(text: str) -> str:
    """Convert markdown to a full HTML document."""
    html_body = md_lib.markdown(text, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
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


def md_preview(text: str) -> str:
    """Convert markdown to HTML fragment (no wrapper)."""
    return md_lib.markdown(text, extensions=["tables", "fenced_code"])


def csv_to_json_str(text: str) -> str:
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return json.dumps(rows, indent=2, ensure_ascii=False)


def json_to_csv_str(text: str) -> str:
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON must be an array of objects")
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
    return output.getvalue()


def yaml_to_json_str(text: str) -> str:
    if not _YAML_AVAILABLE:
        raise RuntimeError("PyYAML not installed — run: pip install PyYAML")
    data = _yaml.safe_load(text)
    return json.dumps(data, indent=2, ensure_ascii=False)


def json_to_yaml_str(text: str) -> str:
    if not _YAML_AVAILABLE:
        raise RuntimeError("PyYAML not installed — run: pip install PyYAML")
    data = json.loads(text)
    return _yaml.dump(data, default_flow_style=False, allow_unicode=True)


def csv_to_tsv_str(text: str) -> str:
    rows = list(csv.reader(io.StringIO(text)))
    output = io.StringIO()
    csv.writer(output, delimiter="\t").writerows(rows)
    return output.getvalue()


def tsv_to_csv_str(text: str) -> str:
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    return output.getvalue()


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


def xml_to_json_str(text: str) -> str:
    root = ET.fromstring(text)
    data = {root.tag: _xml_to_dict(root)}
    return json.dumps(data, indent=2, ensure_ascii=False)


# ── AV Tools ──

def run_ffmpeg(input_data: bytes, in_suffix: str, out_suffix: str,
               ffmpeg_args: list[str], timeout: int = 300,
               pre_input_args: list[str] | None = None) -> bytes:
    """Run ffmpeg with input data, return output bytes."""
    with tempfile.NamedTemporaryFile(suffix=in_suffix, delete=False) as inf:
        inf.write(input_data)
        inf_path = inf.name
    with tempfile.NamedTemporaryFile(suffix=out_suffix, delete=False) as outf:
        out_path = outf.name
    try:
        cmd = ["ffmpeg", "-y"] + (pre_input_args or []) + ["-i", inf_path] + ffmpeg_args + [out_path]
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
        return Path(out_path).read_bytes()
    finally:
        Path(inf_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


# Codec maps for AV operations
AUDIO_CODEC_MAP = {
    "mp3": ["-codec:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-codec:a", "pcm_s16le"],
    "ogg": ["-codec:a", "libvorbis", "-q:a", "6"],
    "flac": ["-codec:a", "flac"],
    "aac": ["-codec:a", "aac", "-b:a", "192k"],
    "m4a": ["-codec:a", "aac", "-b:a", "192k"],
}

VIDEO_CODEC_MAP = {
    "mp4": ["-vcodec", "libx264", "-acodec", "aac"],
    "webm": ["-vcodec", "libvpx-vp9", "-acodec", "libopus"],
    "avi": ["-vcodec", "mpeg4", "-acodec", "mp3"],
    "mov": ["-vcodec", "libx264", "-acodec", "aac"],
}


def convert_audio(data: bytes, in_ext: str, out_fmt: str) -> bytes:
    if out_fmt not in AUDIO_CODEC_MAP:
        raise ValueError(f"Unsupported audio format: {out_fmt}")
    return run_ffmpeg(data, f".{in_ext}", f".{out_fmt}",
                      ["-map", "0:a"] + AUDIO_CODEC_MAP[out_fmt])


def trim_audio(data: bytes, ext: str, start: str, end: str = "") -> bytes:
    args = ["-ss", start]
    if end:
        args += ["-to", end]
    args += ["-map", "0:a", "-c", "copy"]
    return run_ffmpeg(data, f".{ext}", f".{ext}", args)


def audio_speed(data: bytes, ext: str, speed: float) -> bytes:
    if speed < 0.25 or speed > 4.0:
        raise ValueError("Speed must be between 0.25 and 4.0")
    if 0.5 <= speed <= 2.0:
        atempo_chain = f"atempo={speed}"
    elif speed < 0.5:
        atempo_chain = f"atempo=0.5,atempo={speed / 0.5:.4f}"
    else:
        atempo_chain = f"atempo=2.0,atempo={speed / 2.0:.4f}"
    out_ext = ext if ext in ("mp3", "wav", "ogg", "flac") else "mp3"
    return run_ffmpeg(data, f".{ext}", f".{out_ext}",
                      ["-map", "0:a", "-filter:a", atempo_chain])


def extract_audio(data: bytes, in_ext: str, out_fmt: str) -> bytes:
    if out_fmt not in AUDIO_CODEC_MAP:
        raise ValueError(f"Unsupported audio format: {out_fmt}")
    return run_ffmpeg(data, f".{in_ext}", f".{out_fmt}",
                      ["-vn", "-map", "0:a"] + AUDIO_CODEC_MAP[out_fmt])


def trim_video(data: bytes, ext: str, start: str, end: str = "") -> bytes:
    pre = ["-ss", start]
    args = []
    if end:
        args += ["-to", end]
    args += ["-c", "copy"]
    return run_ffmpeg(data, f".{ext}", f".{ext}", args, timeout=300, pre_input_args=pre)


def compress_video(data: bytes, ext: str, quality: str = "medium") -> bytes:
    crf_map = {"high": "18", "medium": "23", "low": "28"}
    crf = crf_map.get(quality, "23")
    return run_ffmpeg(data, f".{ext}", ".mp4",
                      ["-vcodec", "libx264", "-crf", crf, "-preset", "fast", "-acodec", "aac"],
                      timeout=300)


def convert_video(data: bytes, in_ext: str, out_fmt: str) -> bytes:
    if out_fmt not in VIDEO_CODEC_MAP:
        raise ValueError(f"Unsupported video format: {out_fmt}")
    return run_ffmpeg(data, f".{in_ext}", f".{out_fmt}",
                      VIDEO_CODEC_MAP[out_fmt], timeout=300)


# ── Archive Tools ──

def create_zip(files: list[tuple[str, bytes]]) -> bytes:
    """Create a ZIP from list of (filename, data) tuples."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)
    return buf.getvalue()


def extract_zip(data: bytes) -> list[tuple[str, bytes]]:
    """Extract ZIP. Returns list of (filename, data) tuples."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    members = [m for m in zf.namelist() if not m.endswith("/")]
    return [(Path(m).name, zf.read(m)) for m in members]


# ── Additional PDF Tools ──

def extract_images_from_pdf(stream: BinaryIO) -> list[tuple[str, bytes]]:
    """Extract all embedded images from a PDF. Returns list of (filename, image_bytes)."""
    reader = PdfReader(stream)
    results = []
    img_num = 0
    for page_num, page in enumerate(reader.pages, 1):
        try:
            for img in page.images:
                img_num += 1
                data = img.data
                name = img.name or f"image_{img_num}"
                # Clean name for filesystem
                name = name.replace("/", "_").replace("\\", "_")
                if data[:2] == b'\xff\xd8':
                    ext = "jpg"
                elif data[:8] == b'\x89PNG\r\n\x1a\n':
                    ext = "png"
                else:
                    ext = "png"
                results.append((f"page{page_num}_{name}.{ext}", data))
        except Exception:
            continue
    return results


def number_pdf_pages(stream: BinaryIO, start: int = 1,
                     position: str = "bottom-center", font_size: int = 11) -> bytes:
    """Add page numbers to every page of a PDF."""
    reader = PdfReader(stream)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        page_num = start + i
        box = page.mediabox
        w = float(box.width)
        h = float(box.height)

        stamp_img = Image.new("RGBA", (int(w), int(h)), (255, 255, 255, 0))
        draw = ImageDraw.Draw(stamp_img)

        font = None
        for fp in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]:
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        text = str(page_num)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]

        if position == "bottom-center":
            x, y = (w - tw) / 2, h - 36
        elif position == "bottom-right":
            x, y = w - tw - 40, h - 36
        elif position == "bottom-left":
            x, y = 40, h - 36
        else:
            x, y = (w - tw) / 2, h - 36

        draw.text((x, y), text, fill=(0, 0, 0, 200), font=font)

        stamp_rgb = Image.new("RGB", stamp_img.size, (255, 255, 255))
        stamp_rgb.paste(stamp_img, mask=stamp_img.split()[3])
        stamp_buf = io.BytesIO()
        stamp_rgb.save(stamp_buf, "PDF")
        stamp_buf.seek(0)
        stamp_page = PdfReader(stamp_buf).pages[0]

        page.merge_page(stamp_page)
        writer.add_page(page)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── Additional AV Tools ──

def merge_audio_files(files_data: list[tuple[str, bytes]], out_fmt: str = "mp3") -> bytes:
    """Merge multiple audio files into one using ffmpeg concat filter."""
    if out_fmt not in AUDIO_CODEC_MAP:
        raise ValueError(f"Unsupported audio format: {out_fmt}")

    tmpdir = tempfile.mkdtemp()
    try:
        input_paths = []
        for i, (ext, data) in enumerate(files_data):
            path = Path(tmpdir) / f"input_{i}.{ext}"
            path.write_bytes(data)
            input_paths.append(str(path))

        out_path = str(Path(tmpdir) / f"output.{out_fmt}")

        cmd = ["ffmpeg", "-y"]
        for p in input_paths:
            cmd += ["-i", p]

        n = len(input_paths)
        filter_str = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
        cmd += ["-filter_complex", filter_str, "-map", "[out]"]
        cmd += AUDIO_CODEC_MAP[out_fmt] + [out_path]

        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())

        return Path(out_path).read_bytes()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def normalize_volume(data: bytes, ext: str) -> bytes:
    """Normalize audio volume using ffmpeg loudnorm filter."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-map", "0:a"])


def video_to_gif(data: bytes, ext: str, fps: int = 10, width: int = 480) -> bytes:
    """Convert a video to animated GIF."""
    return run_ffmpeg(data, f".{ext}", ".gif",
                      ["-vf", f"fps={fps},scale={width}:-1:flags=lanczos", "-loop", "0"],
                      timeout=300)


def reverse_audio(data: bytes, ext: str) -> bytes:
    """Reverse audio using ffmpeg areverse filter. Returns audio bytes."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-map", "0:a", "-af", "areverse"])


def change_pitch(data: bytes, ext: str, semitones: float) -> bytes:
    """Change audio pitch without changing speed.

    semitones: -12 to 12 (negative = lower, positive = higher).
    Uses asetrate to shift pitch then atempo to compensate speed.
    """
    if semitones < -12 or semitones > 12:
        raise ValueError("Semitones must be between -12 and 12")
    semitone_ratio = 2 ** (semitones / 12)
    tempo_correction = 1 / semitone_ratio
    af = f"asetrate=44100*{semitone_ratio:.6f},atempo={tempo_correction:.6f}"
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-map", "0:a", "-af", af])


def audio_equalizer(data: bytes, ext: str, bass: float = 0,
                    mid: float = 0, treble: float = 0) -> bytes:
    """Apply 3-band equalizer to audio.

    bass: -10 to 10 dB (centered at 100 Hz).
    mid: -10 to 10 dB (centered at 1000 Hz).
    treble: -10 to 10 dB (centered at 4000 Hz).
    """
    bass = max(-10, min(10, bass))
    mid = max(-10, min(10, mid))
    treble = max(-10, min(10, treble))
    af = f"bass=g={bass}:f=100,treble=g={treble}:f=4000,equalizer=f=1000:t=h:width=500:g={mid}"
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-map", "0:a", "-af", af])


def audio_fade(data: bytes, ext: str, fade_in: float = 0,
               fade_out: float = 0, duration: float = 0) -> bytes:
    """Add fade-in and/or fade-out to audio.

    fade_in: fade-in duration in seconds.
    fade_out: fade-out duration in seconds.
    duration: total audio duration in seconds (required for fade-out).
    """
    filters = []
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0 and duration > 0:
        fade_start = max(0, duration - fade_out)
        filters.append(f"afade=t=out:st={fade_start}:d={fade_out}")
    if not filters:
        raise ValueError("Provide fade_in and/or fade_out duration")
    af = ",".join(filters)
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-map", "0:a", "-af", af])


def crop_video(data: bytes, ext: str, width: int, height: int,
               x: int = 0, y: int = 0) -> bytes:
    """Crop video to specified dimensions.

    width/height: output dimensions in pixels.
    x/y: top-left corner offset of the crop area.
    """
    vf = f"crop={width}:{height}:{x}:{y}"
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", vf, "-c:a", "copy"], timeout=300)


def rotate_video(data: bytes, ext: str, angle: int) -> bytes:
    """Rotate video by 90, 180, or 270 degrees.

    Uses ffmpeg transpose filter:
    90  = transpose=1 (clockwise)
    180 = transpose=1,transpose=1
    270 = transpose=2 (counter-clockwise)
    """
    if angle == 90:
        vf = "transpose=1"
    elif angle == 180:
        vf = "transpose=1,transpose=1"
    elif angle == 270:
        vf = "transpose=2"
    else:
        raise ValueError("Angle must be 90, 180, or 270")
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", vf, "-c:a", "copy"], timeout=300)


def resize_video(data: bytes, ext: str, width: int, height: int = -1) -> bytes:
    """Resize video to specified dimensions.

    width/height: target dimensions. Use -1 for either to auto-calculate
    based on aspect ratio. Both values are rounded to nearest even number
    by the scale filter.
    """
    vf = f"scale={width}:{height}"
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", vf, "-c:a", "copy"], timeout=300)


def reverse_video(data: bytes, ext: str) -> bytes:
    """Reverse video and audio using ffmpeg reverse and areverse filters."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", "reverse", "-af", "areverse"], timeout=300)


def loop_video(data: bytes, ext: str, count: int = 2) -> bytes:
    """Loop video N times using ffmpeg stream_loop.

    count: number of total plays (e.g. 2 = play twice).
    """
    if count < 1:
        raise ValueError("Loop count must be at least 1")
    # stream_loop takes number of additional loops (0 = play once, 1 = play twice)
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as inf:
        inf.write(data)
        inf_path = inf.name
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as outf:
        out_path = outf.name
    try:
        cmd = ["ffmpeg", "-y", "-stream_loop", str(count - 1),
               "-i", inf_path, "-c", "copy", out_path]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
        return Path(out_path).read_bytes()
    finally:
        Path(inf_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


def mute_video(data: bytes, ext: str) -> bytes:
    """Strip audio track from video."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-an", "-c:v", "copy"], timeout=300)


def add_audio_to_video(video_data: bytes, video_ext: str,
                       audio_data: bytes, audio_ext: str) -> bytes:
    """Replace audio in a video with a separate audio file.

    Uses two input files: the video (video track only) and the audio.
    The audio is trimmed or padded to match the video duration.
    """
    tmpdir = tempfile.mkdtemp()
    try:
        video_path = str(Path(tmpdir) / f"video.{video_ext}")
        audio_path = str(Path(tmpdir) / f"audio.{audio_ext}")
        out_path = str(Path(tmpdir) / f"output.{video_ext}")

        Path(video_path).write_bytes(video_data)
        Path(audio_path).write_bytes(audio_data)

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())

        return Path(out_path).read_bytes()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def burn_subtitles(video_data: bytes, video_ext: str, srt_data: bytes) -> bytes:
    """Burn SRT subtitles into a video using the ffmpeg subtitles filter.

    Renders subtitle text permanently onto video frames.
    """
    tmpdir = tempfile.mkdtemp()
    try:
        video_path = str(Path(tmpdir) / f"video.{video_ext}")
        srt_path = str(Path(tmpdir) / "subs.srt")
        out_path = str(Path(tmpdir) / f"output.{video_ext}")

        Path(video_path).write_bytes(video_data)
        Path(srt_path).write_bytes(srt_data)

        # Escape special characters in path for ffmpeg subtitles filter
        escaped_srt = srt_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles={escaped_srt}",
            "-c:a", "copy",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())

        return Path(out_path).read_bytes()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ── QR Code Tools ──

def generate_qr(text: str, box_size: int = 10, border: int = 4,
                error_correction: str = "M",
                fill_color: str = "black", back_color: str = "white") -> bytes:
    """Generate a QR code PNG from text."""
    import qrcode
    ec_map = {
        "L": qrcode.constants.ERROR_CORRECT_L,
        "M": qrcode.constants.ERROR_CORRECT_M,
        "Q": qrcode.constants.ERROR_CORRECT_Q,
        "H": qrcode.constants.ERROR_CORRECT_H,
    }
    qr = qrcode.QRCode(
        version=None,
        error_correction=ec_map.get(error_correction, qrcode.constants.ERROR_CORRECT_M),
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fill_color, back_color=back_color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ── Developer Tools ──

def generate_hash(data: bytes, algorithm: str = "sha256") -> dict:
    """Generate hash digests for the given data."""
    import hashlib
    algos = ["md5", "sha1", "sha256", "sha512"]
    if algorithm == "all":
        return {a: hashlib.new(a, data).hexdigest() for a in algos}
    if algorithm not in algos:
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    return {algorithm: hashlib.new(algorithm, data).hexdigest()}


def json_format(text: str, indent: int = 2) -> str:
    """Format/prettify JSON string."""
    data = json.loads(text)
    return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False)


def json_minify(text: str) -> str:
    """Minify JSON string."""
    data = json.loads(text)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def json_validate(text: str) -> dict:
    """Validate JSON and return info."""
    try:
        data = json.loads(text)
        info = {"valid": True, "type": type(data).__name__}
        if isinstance(data, list):
            info["length"] = len(data)
        elif isinstance(data, dict):
            info["keys"] = len(data)
        return info
    except json.JSONDecodeError as e:
        return {"valid": False, "error": str(e), "line": e.lineno, "column": e.colno}


def base64_encode(data: bytes) -> str:
    """Base64 encode binary data."""
    import base64
    return base64.b64encode(data).decode("ascii")


def base64_decode(text: str) -> bytes:
    """Base64 decode a string."""
    import base64
    return base64.b64decode(text)


def generate_placeholder_image(width: int, height: int, bg_color: str = "#cccccc",
                                text_color: str = "#666666", text: str = "") -> bytes:
    """Generate a placeholder image with dimensions text."""
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    label = text or f"{width} x {height}"
    font_size = max(12, min(width, height) // 8)
    font = None
    for fp in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - tw) / 2
    y = (height - th) / 2
    draw.text((x, y), label, fill=text_color, font=font)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def generate_password(length: int = 16, uppercase: bool = True, lowercase: bool = True,
                      digits: bool = True, symbols: bool = True, count: int = 1) -> list[str]:
    """Generate random passwords."""
    import secrets
    import string
    chars = ""
    if uppercase:
        chars += string.ascii_uppercase
    if lowercase:
        chars += string.ascii_lowercase
    if digits:
        chars += string.digits
    if symbols:
        chars += "!@#$%^&*()-_=+[]{}|;:,.<>?"
    if not chars:
        chars = string.ascii_letters + string.digits
    return ["".join(secrets.choice(chars) for _ in range(length)) for _ in range(count)]


def generate_uuid(version: int = 4, count: int = 1) -> list[str]:
    """Generate UUIDs."""
    import uuid as _uuid
    results = []
    for _ in range(count):
        if version == 1:
            results.append(str(_uuid.uuid1()))
        else:
            results.append(str(_uuid.uuid4()))
    return results


def generate_lorem(paragraphs: int = 3) -> str:
    """Generate lorem ipsum placeholder text."""
    base = [
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.",
        "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.",
        "Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo.",
        "Nemo enim ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit, sed quia consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt. Neque porro quisquam est, qui dolorem ipsum quia dolor sit amet.",
        "At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis praesentium voluptatum deleniti atque corrupti quos dolores et quas molestias excepturi sint occaecati cupiditate non provident.",
    ]
    result = []
    for i in range(paragraphs):
        result.append(base[i % len(base)])
    return "\n\n".join(result)


def text_stats(text: str) -> dict:
    """Get text statistics."""
    lines = text.split("\n")
    words = text.split()
    return {
        "characters": len(text),
        "characters_no_spaces": len(text.replace(" ", "").replace("\n", "")),
        "words": len(words),
        "lines": len(lines),
        "paragraphs": len([p for p in text.split("\n\n") if p.strip()]),
        "sentences": len([s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]),
    }


def text_diff(text1: str, text2: str) -> str:
    """Generate a unified diff between two texts."""
    import difflib
    lines1 = text1.splitlines(keepends=True)
    lines2 = text2.splitlines(keepends=True)
    diff = difflib.unified_diff(lines1, lines2, fromfile="Original", tofile="Modified")
    return "".join(diff)


def file_metadata(filepath: str) -> dict:
    """Get file metadata."""
    import os
    import datetime
    p = Path(filepath)
    stat = p.stat()
    return {
        "name": p.name,
        "size": stat.st_size,
        "created": datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "extension": p.suffix,
    }
