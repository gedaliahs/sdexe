"""Pure tool functions shared between web routes and CLI subcommands."""

import io
import re
import csv
import json
import logging
import shutil
import tempfile
import time
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO

from pypdf import PdfReader, PdfWriter, Transformation
from PIL import Image, ImageFilter, ImageEnhance, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
import markdown as md_lib

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

logger = logging.getLogger("sdexe")


# ── Dependency resolution ──

_ffmpeg_path_cache = None  # None = unresolved; "" = resolved to nothing


def _binary_runs(path: str) -> bool:
    """True only if the binary actually starts (catches e.g. a dangling dylib)."""
    try:
        return subprocess.run([path, "-version"], stdin=subprocess.DEVNULL, capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def ffmpeg_path(refresh: bool = False) -> str | None:
    """Path to a *working* ffmpeg binary.

    Prefers a system ffmpeg on PATH; if that is missing or broken (e.g. a dangling
    dynamic-library dependency that makes it fail to start), falls back to the ffmpeg
    bundled with imageio-ffmpeg. Returns None only if neither runs.

    The result is cached; pass refresh=True to re-resolve after installing ffmpeg.
    """
    global _ffmpeg_path_cache
    if _ffmpeg_path_cache is not None and not refresh:
        return _ffmpeg_path_cache or None

    resolved = ""
    system = shutil.which("ffmpeg")
    if system and _binary_runs(system):
        resolved = system
    else:
        try:
            import imageio_ffmpeg
            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled and _binary_runs(bundled):
                resolved = bundled
        except Exception:
            resolved = ""
    _ffmpeg_path_cache = resolved
    return resolved or None


def _reset_ffmpeg_cache():
    """Forget the cached ffmpeg path (call after an install)."""
    global _ffmpeg_path_cache, _bundled_cache
    _ffmpeg_path_cache = None
    _bundled_cache = None


def _ffmpeg_exe() -> str:
    """Resolved ffmpeg path, or raise FFmpegMissingError."""
    exe = ffmpeg_path()
    if not exe:
        raise FFmpegMissingError("ffmpeg is not installed")
    return exe


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


_filter_cache: dict[str, set] = {}


def _ffmpeg_filters(exe: str) -> set:
    """Filter names a given ffmpeg build provides."""
    if exe in _filter_cache:
        return _filter_cache[exe]
    names = set()
    try:
        r = subprocess.run([exe, "-hide_banner", "-filters"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) > 1:
                names.add(parts[1])
    except Exception:
        pass
    _filter_cache[exe] = names
    return names


_bundled_cache = None  # None = not looked up yet; "" = there is none


def _bundled_ffmpeg() -> str | None:
    """The ffmpeg that ships with imageio-ffmpeg, if it runs. Looked up once:
    starting it to check costs about 20 ms every time."""
    global _bundled_cache
    if _bundled_cache is None:
        found = ""
        try:
            import imageio_ffmpeg
            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled and _binary_runs(bundled):
                found = bundled
        except Exception:
            pass
        _bundled_cache = found
    return _bundled_cache or None


def ffmpeg_exe_with_filter(name: str) -> str | None:
    """An ffmpeg that provides `name`, preferring the resolved default.

    A Homebrew ffmpeg built without libass has no `subtitles` filter, while the
    bundled imageio-ffmpeg build does, so fall back to it rather than failing.
    """
    candidates = []
    default = ffmpeg_path()
    if default:
        candidates.append(default)
    bundled = _bundled_ffmpeg()
    if bundled and bundled not in candidates:
        candidates.append(bundled)
    for exe in candidates:
        if name in _ffmpeg_filters(exe):
            return exe
    return None


_encoder_cache: dict[str, set] = {}


def _ffmpeg_encoders(exe: str) -> set:
    """Encoder names a given ffmpeg build provides."""
    if exe not in _encoder_cache:
        names = set()
        try:
            r = subprocess.run([exe, "-hide_banner", "-encoders"],
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
            for line in r.stdout.splitlines():
                parts = line.split()
                if len(parts) > 1:
                    names.add(parts[1])
        except Exception:
            pass
        _encoder_cache[exe] = names
    return _encoder_cache[exe]


def ffmpeg_for_output(out_ext: str, args: list | tuple = ()) -> str:
    """The ffmpeg to write this output with. Current Homebrew builds have no
    libvorbis, so every .ogg job failed there ("cannot write that output
    format") or came out as FLAC inside an Ogg file; the bundled build has it."""
    exe = _ffmpeg_exe()
    if out_ext.lower().lstrip(".") in ("ogg", "oga") or "libvorbis" in args:
        if "libvorbis" not in _ffmpeg_encoders(exe):
            bundled = _bundled_ffmpeg()
            if bundled and "libvorbis" in _ffmpeg_encoders(bundled):
                return bundled
    return exe


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _probe_file(path: str) -> dict:
    """{"duration": seconds, "sample_rate": Hz} of a media file, 0 where unknown."""
    info = {"duration": 0.0, "sample_rate": 0}
    try:
        # ffprobe may be absent when only the bundled ffmpeg is available, so
        # read these off ffmpeg's own stderr instead.
        r = subprocess.run([_ffmpeg_exe(), "-hide_banner", "-i", path], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, errors="replace", timeout=60)
        match = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", r.stderr or "")
        if match:
            hours, minutes, seconds = match.groups()
            info["duration"] = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        match = re.search(r"Stream #0:\d+.*?: Audio: .*?(\d+) Hz", r.stderr or "")
        if match:
            info["sample_rate"] = int(match.group(1))
    except FFmpegMissingError:
        raise
    except Exception:
        pass
    return info


@contextmanager
def _input_file(data: bytes, suffix: str):
    """data in a temp file that is removed afterwards, also when writing it fails."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        with tmp:
            tmp.write(data)
        yield tmp.name
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def probe_duration(data: bytes, ext: str) -> float:
    """Duration of a media blob in seconds, or 0 when it cannot be determined."""
    _ffmpeg_exe()
    with _input_file(data, f".{ext.lstrip('.')}") as path:
        return _probe_file(path)["duration"]


def ffmpeg_version() -> str | None:
    """Short ffmpeg version string for display, or None if unavailable."""
    path = ffmpeg_path()
    if not path:
        return None
    try:
        r = subprocess.run([path, "-version"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout:
            parts = r.stdout.split("\n", 1)[0].split()
            if len(parts) >= 3:
                return parts[2]
    except Exception:
        pass
    return "installed"


# ── Helpers ──

_PIL_FMT_MAP = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF"}
_MIME_MAP = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def _ext_from_filename(filename: str, default: str = "png") -> str:
    # Letters and digits only. The extension ends up in temp-file names, so
    # "a./x" (extension "/x") pointed into a folder that does not exist.
    ext = filename.rsplit(".", 1)[-1].strip().lower() if "." in filename else ""
    return ext if ext.isascii() and ext.isalnum() else default


def output_image_format(filename: str, img: Image.Image | None = None,
                        writable: tuple = ("jpg", "png", "webp", "gif")) -> str:
    """The format to save an edited image in: the input's own when we can
    write it, else PNG. So a .bmp/.tiff/.heic comes back as a real .png, not
    PNG bytes under the old name, and transparency never goes to JPEG/GIF."""
    fmt = _ext_from_filename(filename)
    fmt = "jpg" if fmt == "jpeg" else fmt
    if fmt not in writable:
        fmt = "png"
    if img is not None and fmt in ("jpg", "gif") and img.mode in ("RGBA", "LA"):
        fmt = "png"
    return fmt


def _base_from_filename(filename: str, default: str = "file") -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else default


def _gray8(img: Image.Image) -> Image.Image:
    """8-bit gray from 16/32-bit or float gray. convert("L") clips instead of
    scaling, which turns a 16-bit scan solid white."""
    hi = img.getextrema()[1]
    if img.mode == "F" and hi <= 1.0:
        scale = 255.0
    elif hi <= 255:
        scale = 1.0
    else:
        scale = 255.0 / (65535 if hi <= 65535 else hi)
    if scale != 1.0:
        img = img.point(lambda v: v * scale)
    return img.convert("L")


_DEEP_GRAY = ("I", "F", "I;16", "I;16L", "I;16B", "I;16N")


def _ensure_processable(img: Image.Image) -> Image.Image:
    """Convert palette, CMYK, and other exotic modes to RGB/RGBA for processing."""
    if img.mode in ("P", "PA"):
        return img.convert("RGBA" if img.mode == "PA" or "transparency" in img.info else "RGB")
    if img.mode in ("CMYK", "YCbCr", "LAB", "HSV"):
        return img.convert("RGB")
    if img.mode == "I":
        return _gray8(img)
    return img


def _ensure_filterable(img: Image.Image) -> Image.Image:
    """_ensure_processable, plus 8-bit gray for the modes Pillow's filters and
    enhancers reject (1-bit, 16-bit, float)."""
    img = _ensure_processable(img)
    if img.mode == "1":
        return img.convert("L")
    if img.mode in _DEEP_GRAY:
        return _gray8(img)
    return img


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _icc_for(img: Image.Image, saved: Image.Image) -> bytes | None:
    """The source's colour profile, if it still describes the pixels being
    saved. Pillow only writes it to JPEG/WebP when asked, and without it a
    Display P3 phone photo comes back with duller colours."""
    icc = img.info.get("icc_profile")
    if not icc or len(icc) < 20:
        return None
    space = bytes(icc[16:20])
    if space == b"RGB " and saved.mode in ("RGB", "RGBA", "P"):
        return icc
    if space == b"GRAY" and saved.mode in ("L", "LA"):
        return icc
    return None


def _keep_icc(src: Image.Image, out: Image.Image) -> Image.Image:
    """Carry the colour profile onto an image Pillow built from scratch."""
    if "icc_profile" in src.info and "icc_profile" not in out.info:
        out.info["icc_profile"] = src.info["icc_profile"]
    return out


def _for_format(img: Image.Image, pil_fmt: str) -> Image.Image:
    """img in a mode pil_fmt can store."""
    mode = img.mode
    if pil_fmt == "JPEG":
        if mode in ("RGB", "L"):
            return img
        if mode in _DEEP_GRAY:
            return _gray8(img)
        if mode == "PA":
            img = img.convert("RGBA")
        return _flatten_alpha(img)  # see-through areas go white, not black
    if mode == "PA" or (mode == "LA" and pil_fmt == "GIF"):
        return img.convert("RGBA")  # GIF only keeps transparency from RGBA or a palette
    if mode in ("CMYK", "YCbCr", "LAB", "HSV"):
        return img.convert("RGB")
    if mode in ("I", "F") or (mode in _DEEP_GRAY and pil_fmt != "PNG"):
        return _gray8(img)  # PNG keeps 16-bit gray as it is
    return img


def _save_image(img: Image.Image, fmt: str) -> bytes:
    """Save a PIL Image to bytes in the given format string (e.g. 'png', 'jpg')."""
    pil_fmt = _PIL_FMT_MAP.get(fmt, "PNG")
    buf = io.BytesIO()
    save_img = _for_format(img, pil_fmt)
    save_img.save(buf, pil_fmt, icc_profile=_icc_for(img, save_img))
    return buf.getvalue()


# ── PDF Tools ──

def _whole_writer(reader: PdfReader) -> PdfWriter:
    """A writer holding the whole document, not just its pages: copying pages
    one by one drops the bookmarks, the fillable form and the title/author."""
    try:
        return PdfWriter(clone_from=reader)
    except Exception:
        if reader.is_encrypted:
            raise
        # A damaged outline or form: the pages alone still copy.
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        return writer


def _append_pages(writer: PdfWriter, reader: PdfReader, pages: list[int] | None = None,
                  outline: bool = True) -> None:
    """Add pages (all, or these 0-based ones in this order) with the
    bookmarks and form fields that belong to them. Unlike add_page, this
    doesn't follow a link and bring the page it points to along, hidden in the
    file: removed pages really are gone."""
    before = len(writer.pages)
    try:
        if pages is None:
            writer.append(reader, import_outline=outline)
        else:
            writer.append(reader, pages=pages, import_outline=outline)
    except Exception:
        if reader.is_encrypted:
            raise
        # Drop whatever it added before failing, then copy the plain pages.
        while len(writer.pages) > before:
            writer.remove_page(len(writer.pages) - 1)
        for i in (range(len(reader.pages)) if pages is None else pages):
            writer.add_page(reader.pages[i])


def _keep_metadata(reader: PdfReader, writer: PdfWriter) -> None:
    meta = {k: v for k, v in (reader.metadata or {}).items() if isinstance(v, str)}
    if meta:
        writer.add_metadata(meta)


def merge_pdfs(streams: list[BinaryIO]) -> bytes:
    """Merge multiple PDF streams into one PDF. Returns PDF bytes."""
    writer = PdfWriter()
    for stream in streams:
        _append_pages(writer, PdfReader(stream))
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
            if not part:
                continue
            try:
                if "-" in part:
                    start_str, end_str = part.split("-", 1)
                    start = int(start_str.strip())
                    end = min(total, int(end_str.strip()))
                else:
                    start = end = int(part.strip())
            except ValueError:
                raise ValueError(f"Invalid page range: {part}")
            # A reversed or out-of-range group would otherwise produce a
            # zero-page PDF that looks like a successful split.
            if start < 1 or start > end or start > total:
                raise ValueError(f"Page range out of bounds for a {total}-page PDF: {part}")
            page_groups.append(list(range(start - 1, end)))
        if not page_groups:
            raise ValueError("No valid page ranges provided")
    else:
        page_groups = [[i] for i in range(total)]

    results = []
    for idx, pages in enumerate(page_groups, 1):
        writer = PdfWriter()
        _append_pages(writer, reader, pages, outline=False)
        buf = io.BytesIO()
        writer.write(buf)
        results.append((f"page_{idx}.pdf", buf.getvalue()))
    return results


def _page_set(pages_str: str, total: int) -> set:
    """0-based page indices for "2,5,7-10". A typo ("a", "3-1", page 99 of 3)
    is an error, not a silent no-op that still reports success."""
    indices = set()
    for part in (pages_str or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                s, e = part.split("-", 1)
                start, end = int(s.strip()), int(e.strip())
            else:
                start = end = int(part)
        except ValueError:
            raise ValueError(f"Invalid page range: {part}")
        if start < 1 or end < start or start > total:
            raise ValueError(f"Page range out of bounds for a {total}-page PDF: {part}")
        indices.update(range(start - 1, min(end, total)))
    if not indices:
        raise ValueError("No pages selected")
    return indices


def read_image(src) -> Image.Image:
    """Image.open, with an error a person can read. Pillow's own names the
    upload's internals: "cannot identify image file <tempfile.Spooled… at 0x…>"."""
    try:
        return Image.open(src)
    except UnidentifiedImageError:
        raise ValueError("This is not an image sdexe can read.") from None


def open_image(src) -> Image.Image:
    """Open an image to edit it, upright. Phone photos store "rotate me" in an
    EXIF tag instead of rotating the pixels; without applying it they come out
    sideways, and saving drops the tag."""
    img = read_image(src)
    img.load()
    return ImageOps.exif_transpose(img) or img


def _flatten_alpha(img: Image.Image, background=(255, 255, 255)) -> Image.Image:
    """RGB for formats without transparency: see-through areas become white,
    not black."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, background)
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return img.convert("RGB") if img.mode != "RGB" else img


def images_to_pdf(images: list[Image.Image]) -> bytes:
    """Convert PIL Images to a single PDF. Returns PDF bytes."""
    rgb_images = [_flatten_alpha(img) for img in images]
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
    writer = _whole_writer(reader)
    # pypdf >= 5 only compresses pages that already belong to a writer.
    for page in writer.pages:
        page.compress_content_streams()
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
    writer = _whole_writer(reader)
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
    writer = _whole_writer(reader)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def rotate_pdf(stream: BinaryIO, angle: int, pages_str: str = "all") -> bytes:
    if angle not in (90, 180, 270):
        raise ValueError("Angle must be 90, 180, or 270")
    reader = PdfReader(stream)
    total = len(reader.pages)
    if (pages_str or "").strip().lower() in ("", "all"):
        page_indices = set(range(total))
    else:
        page_indices = _page_set(pages_str, total)
    writer = _whole_writer(reader)
    for i, page in enumerate(writer.pages):
        if i in page_indices:
            page.rotate(angle)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def reorder_pdf(stream: BinaryIO, order: list[int]) -> bytes:
    """Reorder pages. order is 1-based list of page numbers."""
    reader = PdfReader(stream)
    total = len(reader.pages)
    writer = PdfWriter()
    for num in order:
        if num < 1 or num > total:
            raise ValueError(f"Page {num} out of range (1-{total})")
    _append_pages(writer, reader, [num - 1 for num in order])
    _keep_metadata(reader, writer)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def delete_pdf_pages(stream: BinaryIO, pages_str: str) -> bytes:
    """Delete specific pages. pages_str like '2,5,7-10' (1-based)."""
    reader = PdfReader(stream)
    total = len(reader.pages)
    to_delete = _page_set(pages_str, total)
    if len(to_delete) >= total:
        raise ValueError("Cannot delete all pages")
    writer = PdfWriter()
    _append_pages(writer, reader, [i for i in range(total) if i not in to_delete])
    _keep_metadata(reader, writer)
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


def set_pdf_metadata(stream: BinaryIO, title: str | None = "", author: str | None = "",
                     subject: str | None = "", keywords: str | None = None,
                     creator: str | None = None) -> bytes:
    """Set PDF metadata. Returns new PDF bytes. A field passed as None keeps
    whatever the PDF already had; "" clears it."""
    reader = PdfReader(stream)
    writer = _whole_writer(reader)
    meta = {k: v for k, v in (reader.metadata or {}).items() if isinstance(v, str)}
    for key, value in (("/Title", title), ("/Author", author), ("/Subject", subject),
                       ("/Keywords", keywords), ("/Creator", creator)):
        if value is not None:
            meta[key] = value
    writer.add_metadata(meta)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# Helvetica advance widths (1/1000 em) for ASCII 32 to 126, so text can be
# centered without embedding a font.
_HELVETICA_WIDTHS = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)


def _helvetica_width(text: str, size: float) -> float:
    total = 0
    for ch in text:
        code = ord(ch)
        total += _HELVETICA_WIDTHS[code - 32] if 32 <= code <= 126 else 556
    return total * size / 1000.0


def _pdf_escape(text: str) -> bytes:
    """Encode text for a PDF literal string using WinAnsi (standard-font) encoding."""
    try:
        raw = text.encode("cp1252")
    except UnicodeEncodeError:
        # The built-in PDF fonts only cover Western European letters; anything
        # else used to come out as "????" with no warning.
        raise ValueError("PDF text stamps support Western European characters only "
                         "(no Hebrew, Arabic, Chinese, emoji…) for now.")
    out = bytearray()
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):  # ( ) backslash
            out += b"\\"
        out.append(byte)
    return bytes(out)


def _text_overlay_pdf(width: float, height: float, items: list) -> bytes:
    """Build a one-page PDF containing only text, with a transparent background.

    Each item is (x, y, size, text, gray, alpha) with y measured from the bottom
    in PDF user space. The page has no background fill, so merging it over a
    real page leaves the original content visible.
    """
    ops = bytearray()
    for x, y, size, text, gray, alpha in items:
        ops += b"q\n/GS0 gs\n" if alpha < 1 else b"q\n"
        ops += f"BT\n/F1 {size:.2f} Tf\n{gray:.3f} g\n{x:.2f} {y:.2f} Td\n".encode("ascii")
        ops += b"(" + _pdf_escape(text) + b") Tj\nET\nQ\n"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
         f"/Resources << /Font << /F1 4 0 R >> /ExtGState << /GS0 5 0 R >> >> "
         f"/Contents 6 0 R >>").encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        f"<< /Type /ExtGState /ca {min(items[0][5] if items else 1, 1):.3f} >>".encode("ascii"),
        b"<< /Length " + str(len(ops)).encode("ascii") + b" >>\nstream\n" + bytes(ops) + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode("ascii")
    return bytes(out)


def _view_box(page):
    """(width, height, transform) of the page as the reader sees it: the
    cropbox, turned by /Rotate. The transform takes a point in that upright
    space (origin bottom-left) to the page's own coordinates, so an overlay
    lands where it looks right and the page itself is left alone. (Rotating
    the page's content instead leaves its links and form fields behind.)"""
    box = page.cropbox
    left, bottom = float(box.left), float(box.bottom)
    w, h = float(box.width), float(box.height)
    rot = int(page.rotation or 0) % 360
    if rot == 90:
        return h, w, Transformation().rotate(90).translate(left + w, bottom)
    if rot == 180:
        return w, h, Transformation().rotate(180).translate(left + w, bottom + h)
    if rot == 270:
        return h, w, Transformation().rotate(-90).translate(left, bottom + h)
    return w, h, Transformation().translate(left, bottom)


def watermark_pdf(stream: BinaryIO, text: str, font_size: int = 36,
                  opacity: float = 0.3, position: str = "center") -> bytes:
    """Add a text watermark to every page of a PDF."""
    reader = PdfReader(stream)
    # pypdf 7 only edits pages that already belong to a writer.
    writer = _whole_writer(reader)
    alpha = max(0.02, min(1.0, float(opacity)))

    for page in writer.pages:
        w, h, to_page = _view_box(page)

        tw = _helvetica_width(text, font_size)
        # Cap-height baseline offset, close enough for placement.
        th = font_size * 0.72
        margin = 40.0

        if position == "top-left":
            x, y = margin, h - margin - th
        elif position == "top-right":
            x, y = w - tw - margin, h - margin - th
        elif position == "bottom-left":
            x, y = margin, margin
        elif position == "bottom-right":
            x, y = w - tw - margin, margin
        else:  # center
            x, y = (w - tw) / 2, (h - th) / 2

        overlay = _text_overlay_pdf(w, h, [(x, y, float(font_size), text, 0.5, alpha)])
        page.merge_transformed_page(PdfReader(io.BytesIO(overlay)).pages[0], to_page)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── Image Tools ──

MAX_RESIZE_PIXELS = 300_000_000


def resize_image(img: Image.Image, mode: str = "dimensions",
                 width: int = 0, height: int = 0,
                 percentage: float = 100,
                 maintain_aspect: bool = True) -> Image.Image:
    if mode == "percentage":
        if not percentage > 0:
            raise ValueError("Percentage must be greater than 0")
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
    if new_w < 1 or new_h < 1:
        raise ValueError("Width and height must be at least 1 pixel")
    if new_w * new_h > MAX_RESIZE_PIXELS:
        # 100000 x 100000 would need 30 GB of memory and take the app down.
        raise ValueError(f"{new_w} x {new_h} is too large (limit {MAX_RESIZE_PIXELS // 1_000_000} megapixels)")
    return img.resize((new_w, new_h), Image.LANCZOS)


def compress_image(img: Image.Image, quality: int, fmt: str) -> bytes:
    """Compress image. quality: 0-100, fmt: file extension string."""
    buf = io.BytesIO()
    if fmt in ("jpg", "jpeg"):
        out = _for_format(img, "JPEG")
        out.save(buf, "JPEG", quality=quality, optimize=True, icc_profile=_icc_for(img, out))
    elif fmt == "webp":
        out = _for_format(_ensure_processable(img), "WEBP")
        out.save(buf, "WEBP", quality=quality, icc_profile=_icc_for(img, out))
    else:
        out = _for_format(_ensure_processable(img), "PNG")
        out.save(buf, "PNG", optimize=True, icc_profile=_icc_for(img, out))
    return buf.getvalue()


def convert_image(img: Image.Image, target: str) -> bytes:
    """Convert image to target format. target: 'png', 'jpg', 'webp'."""
    pil_fmt = "JPEG" if target in ("jpg", "jpeg") else target.upper()
    out = img
    if pil_fmt in ("PNG", "WEBP"):
        out = _ensure_processable(out)
    if pil_fmt in ("JPEG", "PNG", "WEBP", "GIF"):
        out = _for_format(out, pil_fmt)
    buf = io.BytesIO()
    out.save(buf, pil_fmt, icc_profile=_icc_for(img, out))
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
    if img.mode in ("P", "PA"):
        new_img.putpalette(img.getpalette())
    new_img.paste(img)  # pixels only, no metadata
    # These two are part of how the picture looks, not data about it: without
    # them a transparent GIF/PNG turns opaque and wide-gamut colours shift.
    for key in ("transparency", "icc_profile"):
        if key in img.info:
            new_img.info[key] = img.info[key]
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
    if img.mode in _DEEP_GRAY:
        return _gray8(img)
    # Keep transparency: "L" alone shows whatever colour hid under it.
    return img.convert("RGBA").convert("LA") if _has_alpha(img) else img.convert("L")


def blur_image(img: Image.Image, radius: float = 5.0) -> Image.Image:
    img = _ensure_filterable(img)
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

    src = img
    if img.mode != "RGBA":
        img = _ensure_filterable(img).convert("RGBA")
    result = Image.alpha_composite(img, overlay)
    return _keep_icc(src, result)


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
    src = img
    img = _ensure_filterable(img)
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return _keep_icc(src, img)


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


def _no_bom(text: str) -> str:
    """Files saved by Excel/Notepad start with an invisible byte-order mark,
    which otherwise ends up inside the first CSV header or breaks JSON."""
    return text[1:] if text[:1] == "\ufeff" else text


def _csv_cell(value):
    """Nested values as JSON and true/false as JSON spells them, not Python's
    {'a': 1} / True."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def csv_to_json_str(text: str) -> str:
    reader = csv.DictReader(io.StringIO(_no_bom(text)))
    rows = list(reader)
    return json.dumps(rows, indent=2, ensure_ascii=False)


def json_to_csv_str(text: str) -> str:
    data = json.loads(_no_bom(text))
    if not isinstance(data, list) or (data and not any(isinstance(obj, dict) for obj in data)):
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
            writer.writerow({k: _csv_cell(v) for k, v in obj.items()})
    return output.getvalue()


def _yaml_json_default(value):
    """YAML types JSON has no word for: dates, sets, binary."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    if isinstance(value, (bytes, bytearray)):
        import base64
        return base64.b64encode(value).decode("ascii")
    return str(value)


def _check_expansion(data, limit: int = 2_000_000) -> None:
    """YAML aliases can make a 1 KB file stand for billions of values ("billion
    laughs"); writing that out as JSON would fill memory. Count before dumping."""
    seen = 0
    containers = set()
    repeats = False
    stack = [data]
    while stack:
        item = stack.pop()
        seen += 1
        if repeats and seen > limit:
            raise ValueError("This YAML expands to too many values to convert (it repeats itself through aliases).")
        if isinstance(item, (dict, list)):
            if id(item) in containers:
                repeats = True
            else:
                containers.add(id(item))
            stack.extend(item.values() if isinstance(item, dict) else item)


def yaml_to_json_str(text: str) -> str:
    if not _YAML_AVAILABLE:
        raise RuntimeError("PyYAML not installed. Run: pip install PyYAML")
    data = _yaml.safe_load(text)
    _check_expansion(data)
    return json.dumps(data, indent=2, ensure_ascii=False, default=_yaml_json_default)


def json_to_yaml_str(text: str) -> str:
    if not _YAML_AVAILABLE:
        raise RuntimeError("PyYAML not installed. Run: pip install PyYAML")
    data = json.loads(_no_bom(text))
    # sort_keys=False: keep the keys in the order the JSON had them.
    return _yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


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

class FFmpegMissingError(RuntimeError):
    """Raised when no usable ffmpeg binary is available."""


def _friendly_ffmpeg_error(stderr: str) -> str:
    """Map ffmpeg stderr to a short message safe to show a user."""
    low = stderr.lower()
    if "invalid data found" in low or "moov atom not found" in low:
        return "That file could not be read. It may be corrupt or an unsupported format."
    if "no such file or directory" in low:
        return "The media file could not be opened."
    if "not divisible by 2" in low or "width/height" in low:
        return "Those dimensions are not valid for this video format. Try an even width and height."
    if "invalid too big or non positive size" in low:
        return "That area does not fit inside the video. Use a smaller size or offset."
    # "matches no streams", not "stream map": every ffmpeg run prints "Stream
    # mapping:", so nearly any failure used to be reported as a missing stream.
    if "does not contain any stream" in low or "matches no streams" in low:
        return "That file has no usable audio or video stream."
    if "permission denied" in low:
        return "Permission denied while writing the output file."
    if "unknown encoder" in low or "encoder not found" in low:
        return "This ffmpeg build cannot write that output format."
    if "conversion failed" in low:
        return "Conversion failed. The input may be unsupported or damaged."
    return "The media operation failed. Check that the file is a valid, complete media file."


# How long a real media job (convert, compress, trim, merge…) may run before we
# give up on it. Generous on purpose: a two-hour video takes a while, and the
# old 5-minute cap made long files fail halfway. This only guards against a
# truly stuck ffmpeg; quick probes keep their own short limits.
MEDIA_TIMEOUT = 6 * 3600


def run_ffmpeg(input_data: bytes, in_suffix: str, out_suffix: str,
               ffmpeg_args: list[str], timeout: int | None = None,
               pre_input_args: list[str] | None = None) -> bytes:
    """Run ffmpeg with input data, return output bytes."""
    _ffmpeg_exe()
    with _input_file(input_data, in_suffix) as inf_path:
        return _run_ffmpeg_file(inf_path, out_suffix, ffmpeg_args, timeout, pre_input_args)


def _run_ffmpeg_file(inf_path: str, out_suffix: str, ffmpeg_args: list[str],
                     timeout: int | None = None, pre_input_args: list[str] | None = None) -> bytes:
    """run_ffmpeg for an input that is already on disk."""
    exe = ffmpeg_for_output(out_suffix, ffmpeg_args)
    with tempfile.NamedTemporaryFile(suffix=out_suffix, delete=False) as outf:
        out_path = outf.name
    try:
        cmd = [exe, "-y"] + (pre_input_args or []) + ["-i", inf_path] + ffmpeg_args + [out_path]
        try:
            result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout or MEDIA_TIMEOUT)
        except FileNotFoundError:
            raise FFmpegMissingError("ffmpeg is not installed")
        except subprocess.TimeoutExpired:
            raise RuntimeError("The media operation timed out.")
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            # Log the real output for the operator, show the user a readable
            # line instead of an ffmpeg build banner.
            logger.error("ffmpeg failed: %s | stderr: %s", " ".join(cmd), stderr[-2000:])
            raise RuntimeError(_friendly_ffmpeg_error(stderr))
        return Path(out_path).read_bytes()
    finally:
        Path(out_path).unlink(missing_ok=True)


# Codec maps for AV operations
# The first audio track. "0:a" maps every track, and single-track formats
# (mp3, wav…) then refuse a file that has two, such as a dual-language video.
_FIRST_AUDIO = ("-map", "0:a:0")

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


# Even dimensions and 4:2:0 colour. A GIF, a screen recording or a 10-bit
# phone clip otherwise becomes "High 4:4:4"/"High 10" H.264, which QuickTime,
# Safari, phones and TVs will not play. A no-op for ordinary video.
EVEN_SCALE = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
_PLAYABLE_H264 = ("-vf", EVEN_SCALE, "-pix_fmt", "yuv420p")


def convert_audio(data: bytes, in_ext: str, out_fmt: str) -> bytes:
    if out_fmt not in AUDIO_CODEC_MAP:
        raise ValueError(f"Unsupported audio format: {out_fmt}")
    return run_ffmpeg(data, f".{in_ext}", f".{out_fmt}",
                      [*_FIRST_AUDIO] + AUDIO_CODEC_MAP[out_fmt])


def _trim_range(start, end) -> tuple[float, float | None]:
    """Start and optional end in seconds, checked."""
    begin = max(0.0, parse_timestamp(start)) if str(start or "").strip() else 0.0
    stop = parse_timestamp(end) if str(end or "").strip() else None
    if stop is not None and stop <= begin:
        raise ValueError("End time must be after start time")
    return begin, stop


def _trim(data: bytes, ext: str, begin: float, args: list[str], pre: list[str] | None = None) -> bytes:
    with _input_file(data, f".{ext}") as path:
        # A start past the end used to "succeed" with an empty audio file, or
        # with the whole video untouched.
        length = _probe_file(path)["duration"]
        if length and begin >= length:
            raise ValueError(f"Start time is past the end of the file (it is {length:.1f} seconds long)")
        return _run_ffmpeg_file(path, f".{ext}", args, MEDIA_TIMEOUT, pre)


def trim_audio(data: bytes, ext: str, start: str, end: str = "") -> bytes:
    begin, stop = _trim_range(start, end)
    args = ["-ss", f"{begin:.3f}"]
    if stop is not None:
        args += ["-to", f"{stop:.3f}"]
    args += ["-map", "0:a", "-c", "copy"]
    return _trim(data, ext, begin, args)


def audio_speed(data: bytes, ext: str, speed: float) -> bytes:
    if not 0.25 <= speed <= 4.0:
        raise ValueError("Speed must be between 0.25 and 4.0")
    if 0.5 <= speed <= 2.0:
        atempo_chain = f"atempo={speed}"
    elif speed < 0.5:
        atempo_chain = f"atempo=0.5,atempo={speed / 0.5:.4f}"
    else:
        atempo_chain = f"atempo=2.0,atempo={speed / 2.0:.4f}"
    out_ext = ext if ext in ("mp3", "wav", "ogg", "flac") else "mp3"
    return run_ffmpeg(data, f".{ext}", f".{out_ext}",
                      [*_FIRST_AUDIO, "-filter:a", atempo_chain])


def extract_audio(data: bytes, in_ext: str, out_fmt: str) -> bytes:
    if out_fmt not in AUDIO_CODEC_MAP:
        raise ValueError(f"Unsupported audio format: {out_fmt}")
    return run_ffmpeg(data, f".{in_ext}", f".{out_fmt}",
                      ["-vn", *_FIRST_AUDIO] + AUDIO_CODEC_MAP[out_fmt])


def parse_timestamp(value: str) -> float:
    """Parse SS, MM:SS, or HH:MM:SS (fractional seconds allowed) into seconds."""
    parts = str(value).strip().split(":")
    if len(parts) > 3:
        raise ValueError(f"Invalid timestamp: {value}")
    total = 0.0
    try:
        for part in parts:
            total = total * 60 + float(part or 0)
    except ValueError:
        raise ValueError(f"Invalid timestamp: {value}")
    if total != total or total in (float("inf"), float("-inf")):
        raise ValueError(f"Invalid timestamp: {value}")
    return total


def trim_video(data: bytes, ext: str, start: str, end: str = "") -> bytes:
    # A pre-input -ss rebases output timestamps to zero, so -to would be measured
    # from the cut point and produce a clip of length `end` instead of
    # `end - start`. Convert the range to an explicit duration instead.
    begin, stop = _trim_range(start, end)
    pre = ["-ss", f"{begin:.3f}"]
    args = []
    if stop is not None:
        args += ["-t", f"{stop - begin:.3f}"]
    args += ["-c", "copy"]
    return _trim(data, ext, begin, args, pre)


def compress_video(data: bytes, ext: str, quality: str = "medium") -> bytes:
    crf_map = {"high": "18", "medium": "23", "low": "28"}
    crf = crf_map.get(quality, "23")
    return run_ffmpeg(data, f".{ext}", ".mp4",
                      ["-vcodec", "libx264", "-crf", crf, "-preset", "fast", "-acodec", "aac", *_PLAYABLE_H264],
                      timeout=MEDIA_TIMEOUT)


def convert_video(data: bytes, in_ext: str, out_fmt: str) -> bytes:
    if out_fmt not in VIDEO_CODEC_MAP:
        raise ValueError(f"Unsupported video format: {out_fmt}")
    extra = {"mp4": _PLAYABLE_H264, "mov": _PLAYABLE_H264, "webm": ("-pix_fmt", "yuv420p")}.get(out_fmt, ())
    return run_ffmpeg(data, f".{in_ext}", f".{out_fmt}",
                      VIDEO_CODEC_MAP[out_fmt] + [*extra], timeout=MEDIA_TIMEOUT)


# ── Archive Tools ──

def _unique_name(name: str, used: set) -> str:
    """name, or name_2, name_3… if it's taken. Records the result in used."""
    if name in used:
        # Number the file, not a folder that happens to have a dot in it
        # ("docs.v2/readme" -> "docs.v2/readme_2").
        head, slash, tail = name.rpartition("/")
        stem, dot, suffix = tail.rpartition(".")
        if not stem:
            stem, dot, suffix = tail, "", ""
        n = 2
        while f"{head}{slash}{stem}_{n}{dot}{suffix}" in used:
            n += 1
        name = f"{head}{slash}{stem}_{n}{dot}{suffix}"
    used.add(name)
    return name


def _archive_name(name: str) -> str:
    """An archive entry's name as a plain relative path: no "..", no leading
    slash, no drive letter. Anything else can land outside the folder it is
    unpacked into ("C:\\x" does on Windows)."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if parts and re.fullmatch(r"[A-Za-z]:", parts[0]):
        parts = parts[1:]
    return "/".join(parts)


def create_zip(files: list[tuple[str, bytes]]) -> bytes:
    """Create a ZIP from list of (filename, data) tuples. Two files with the
    same name both go in ("notes.txt", "notes_2.txt"); a ZIP with duplicate
    entries extracts only one of them."""
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            name = _unique_name(_archive_name(name) or "file", used)
            if len(data) < 8 * 1024 * 1024 or isinstance(data, str):
                zf.writestr(name, data)
                continue
            # A big file goes in a megabyte at a time: writestr compresses it
            # into a second full-size buffer first (815 MB peak for a 200 MB
            # file, 420 MB this way).
            info = zipfile.ZipInfo(name, time.localtime()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            info.file_size = len(data)
            view = memoryview(data)
            with zf.open(info, "w") as dest:
                for i in range(0, len(view), 1 << 20):
                    dest.write(view[i:i + (1 << 20)])
    return buf.getvalue()


# Refuse archives that would expand past this: a small "zip bomb" upload can
# otherwise inflate to many GB in memory.
MAX_EXTRACTED_BYTES = 4 * 1024 ** 3


def extract_zip(data: bytes) -> list[tuple[str, bytes]]:
    """Extract ZIP. Returns list of (filename, data) tuples."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in zf.infolist()) > MAX_EXTRACTED_BYTES:
        raise ValueError("This archive expands to more than 4 GB, which is too large to open here.")
    results = []
    used = set()
    # By entry, not by name: reading by name returns the last of two entries
    # that share one, twice.
    for info in zf.infolist():
        if info.is_dir():
            continue
        # Keep the directory structure. Collapsing to the basename made
        # "a/config.json" and "b/config.json" collide and lose a file.
        name = _archive_name(info.filename)
        if not name:
            continue
        if info.flag_bits & 0x1:
            raise ValueError("This ZIP is password-protected, which is not supported.")
        results.append((_unique_name(name, used), zf.read(info)))
    return results


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
                # pypdf's name already carries an extension ("image.jpg"), so
                # take the stem and derive the extension from the bytes.
                name = Path((img.name or f"image_{img_num}").replace("/", "_").replace("\\", "_")).stem
                if data[:2] == b'\xff\xd8':
                    ext = "jpg"
                elif data[:8] == b'\x89PNG\r\n\x1a\n':
                    ext = "png"
                elif data[:12] in (b'\x00\x00\x00\x0cjP  \r\n\x87\n',) or data[:4] == b'\xff\x4f\xff\x51':
                    ext = "jp2"
                elif data[:4] in (b'II*\x00', b'MM\x00*'):
                    ext = "tif"
                elif data[:6] in (b'GIF87a', b'GIF89a'):
                    ext = "gif"
                else:
                    ext = Path(img.name or "").suffix.lstrip(".").lower() or "png"
                results.append((f"page{page_num}_{name}.{ext}", data))
        except Exception:
            continue
    return results


def number_pdf_pages(stream: BinaryIO, start: int = 1,
                     position: str = "bottom-center", font_size: int = 11) -> bytes:
    """Add page numbers to every page of a PDF."""
    reader = PdfReader(stream)
    writer = _whole_writer(reader)  # pages must belong to a writer before pypdf 7 edits them

    for i, page in enumerate(writer.pages):
        page_num = start + i
        w, h, to_page = _view_box(page)

        text = str(page_num)
        tw = _helvetica_width(text, font_size)
        y = 28.0  # from the bottom edge, in PDF user space

        if position == "bottom-right":
            x = w - tw - 40
        elif position == "bottom-left":
            x = 40.0
        else:  # bottom-center
            x = (w - tw) / 2

        overlay = _text_overlay_pdf(w, h, [(x, y, float(font_size), text, 0.0, 1.0)])
        page.merge_transformed_page(PdfReader(io.BytesIO(overlay)).pages[0], to_page)

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

        cmd = [ffmpeg_for_output(out_fmt, AUDIO_CODEC_MAP[out_fmt]), "-y"]
        for p in input_paths:
            cmd += ["-i", p]

        n = len(input_paths)
        filter_str = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[out]"
        cmd += ["-filter_complex", filter_str, "-map", "[out]"]
        cmd += AUDIO_CODEC_MAP[out_fmt] + [out_path]

        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=MEDIA_TIMEOUT)
        if result.returncode != 0:
            # The raw stderr has ffmpeg's build banner and temp paths; say what went wrong instead.
            raise RuntimeError(_friendly_ffmpeg_error(result.stderr.decode("utf-8", errors="replace")))

        return Path(out_path).read_bytes()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def normalize_volume(data: bytes, ext: str) -> bytes:
    """Normalize audio volume using ffmpeg loudnorm filter."""
    with _input_file(data, f".{ext}") as path:
        args = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", *_FIRST_AUDIO]
        # loudnorm works at 192 kHz and leaves the audio there, so a WAV came
        # back four times its size. Put the original rate back.
        rate = _probe_file(path)["sample_rate"]
        if rate:
            args += ["-ar", str(rate)]
        return _run_ffmpeg_file(path, f".{ext}", args)


def video_to_gif(data: bytes, ext: str, fps: int = 10, width: int = 480) -> bytes:
    """Convert a video to animated GIF."""
    return run_ffmpeg(data, f".{ext}", ".gif",
                      ["-vf", f"fps={fps},scale={width}:-1:flags=lanczos", "-loop", "0"],
                      timeout=MEDIA_TIMEOUT)


def reverse_audio(data: bytes, ext: str) -> bytes:
    """Reverse audio using ffmpeg areverse filter. Returns audio bytes."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      [*_FIRST_AUDIO, "-af", "areverse"])


def change_pitch(data: bytes, ext: str, semitones: float) -> bytes:
    """Change audio pitch without changing speed.

    semitones: -12 to 12 (negative = lower, positive = higher).
    Uses asetrate to shift pitch then atempo to compensate speed.
    """
    if semitones < -12 or semitones > 12:
        raise ValueError("Semitones must be between -12 and 12")
    semitone_ratio = 2 ** (semitones / 12)
    tempo_correction = 1 / semitone_ratio
    # asetrate needs the real sample rate. Resample to a known rate first so the
    # shift is correct for 48 kHz sources, then restore it after the tempo fix.
    af = (f"aresample=44100,asetrate=44100*{semitone_ratio:.6f},"
          f"atempo={tempo_correction:.6f},aresample=44100")
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      [*_FIRST_AUDIO, "-af", af])


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
                      [*_FIRST_AUDIO, "-af", af])


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
    if fade_out > 0:
        # A fade-out needs the total length. Callers often omit it, and silently
        # dropping the fade would report success without applying it.
        if duration <= 0:
            duration = probe_duration(data, ext)
        if duration <= 0:
            raise ValueError("Could not determine audio length for the fade-out")
        fade_start = max(0, duration - fade_out)
        filters.append(f"afade=t=out:st={fade_start}:d={fade_out}")
    if not filters:
        raise ValueError("Provide fade_in and/or fade_out duration")
    af = ",".join(filters)
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      [*_FIRST_AUDIO, "-af", af])


def crop_video(data: bytes, ext: str, width: int, height: int,
               x: int = 0, y: int = 0) -> bytes:
    """Crop video to specified dimensions.

    width/height: output dimensions in pixels.
    x/y: top-left corner offset of the crop area.
    """
    # h264 rejects odd dimensions, so round the crop box down to even.
    width -= width % 2
    height -= height % 2
    if width <= 0 or height <= 0:
        raise ValueError("Crop width and height must be at least 2 pixels")
    vf = f"crop={width}:{height}:{x}:{y}"
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", vf, "-c:a", "copy"], timeout=MEDIA_TIMEOUT)


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
                      ["-vf", vf, "-c:a", "copy"], timeout=MEDIA_TIMEOUT)


def resize_video(data: bytes, ext: str, width: int, height: int = -1) -> bytes:
    """Resize video to specified dimensions.

    width/height: target dimensions. Use -1 for either to auto-calculate
    based on aspect ratio.
    """
    # -2 keeps the auto-computed side even. h264 rejects odd dimensions, and a
    # -1 side lands on an odd number for most non-16:9 inputs.
    w = width if width <= 0 else width - (width % 2)
    h = height if height <= 0 else height - (height % 2)
    vf = f"scale={w if w > 0 else -2}:{h if h > 0 else -2}"
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", vf, "-c:a", "copy"], timeout=MEDIA_TIMEOUT)


def reverse_video(data: bytes, ext: str) -> bytes:
    """Reverse video and audio using ffmpeg reverse and areverse filters."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-vf", "reverse", "-af", "areverse"], timeout=MEDIA_TIMEOUT)


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
        cmd = [_ffmpeg_exe(), "-y", "-stream_loop", str(count - 1),
               "-i", inf_path, "-c", "copy", out_path]
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=MEDIA_TIMEOUT)
        if result.returncode != 0:
            # The raw stderr has ffmpeg's build banner and temp paths; say what went wrong instead.
            raise RuntimeError(_friendly_ffmpeg_error(result.stderr.decode("utf-8", errors="replace")))
        return Path(out_path).read_bytes()
    finally:
        Path(inf_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)


def mute_video(data: bytes, ext: str) -> bytes:
    """Strip audio track from video."""
    return run_ffmpeg(data, f".{ext}", f".{ext}",
                      ["-an", "-c:v", "copy"], timeout=MEDIA_TIMEOUT)


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

        # The audio codec the container takes (AAC cannot go into WebM), and
        # apad so audio shorter than the video is padded with silence: with
        # -shortest alone the video was cut down to the length of the audio.
        codecs = VIDEO_CODEC_MAP.get(video_ext.lower(), VIDEO_CODEC_MAP["mp4"])
        cmd = [
            _ffmpeg_exe(), "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", codecs[codecs.index("-acodec") + 1],
            "-af", "apad",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            out_path,
        ]
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=MEDIA_TIMEOUT)
        if result.returncode != 0:
            # The raw stderr has ffmpeg's build banner and temp paths; say what went wrong instead.
            raise RuntimeError(_friendly_ffmpeg_error(result.stderr.decode("utf-8", errors="replace")))

        return Path(out_path).read_bytes()
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _subtitles_utf8(data: bytes) -> bytes:
    """Subtitle text as UTF-8, which is all the subtitles filter reads. A file
    in a legacy code page (Hebrew cp1255, Cyrillic cp1251…) used to fail as
    "could not be read, it may be corrupt". Which code page it is cannot be
    told reliably from the bytes (a guess burns in gibberish), so say what to do."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace").encode("utf-8")
    try:
        return data.decode("utf-8-sig").encode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("These subtitles are not saved as UTF-8. Save the file as UTF-8 and try again.")


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
        Path(srt_path).write_bytes(_subtitles_utf8(srt_data))

        exe = ffmpeg_exe_with_filter("subtitles")
        if not exe:
            raise RuntimeError(
                "This ffmpeg build cannot burn in subtitles. Install an ffmpeg "
                "built with libass, then try again."
            )

        # Run inside the temp folder and name the file without its path: a
        # folder with ' , [ ] or ; in its name (a Windows user called O'Brien)
        # cannot be escaped reliably inside a filter description.
        cmd = [
            exe, "-y",
            "-i", video_path,
            "-vf", "subtitles=subs.srt",
            "-c:a", "copy",
            out_path,
        ]
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=MEDIA_TIMEOUT, cwd=tmpdir)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            logger.error("burn_subtitles failed: %s", stderr[-2000:])
            raise RuntimeError(_friendly_ffmpeg_error(stderr))

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
    data = json.loads(_no_bom(text))
    return json.dumps(data, indent=indent, ensure_ascii=False, sort_keys=False)


def json_minify(text: str) -> str:
    """Minify JSON string."""
    data = json.loads(_no_bom(text))
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def json_validate(text: str) -> dict:
    """Validate JSON and return info."""
    try:
        data = json.loads(_no_bom(text))
        info = {"valid": True, "type": type(data).__name__}
        if isinstance(data, list):
            info["length"] = len(data)
        elif isinstance(data, dict):
            info["keys"] = len(data)
        return info
    except json.JSONDecodeError as e:
        return {"valid": False, "error": str(e), "line": e.lineno, "column": e.colno}
    except RecursionError:
        return {"valid": False, "error": "Nested too deeply to parse", "line": 1, "column": 1}


def base64_encode(data: bytes) -> str:
    """Base64 encode binary data."""
    import base64
    return base64.b64encode(data).decode("ascii")


def base64_decode(text: str) -> bytes:
    """Base64 decode a string. Accepts what people actually paste: a data:
    URL, line breaks, the URL-safe alphabet (- and _), and missing = padding.
    Anything else is an error, not a silently shorter result."""
    import base64
    text = text.strip()
    if text[:5].lower() == "data:" and "," in text:
        text = text.split(",", 1)[1]
    text = "".join(text.split()).replace("-", "+").replace("_", "/").rstrip("=")
    return base64.b64decode(text + "=" * (-len(text) % 4), validate=True)


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
    text = text.replace("\r\n", "\n")  # browsers send textarea text with CRLF
    lines = text.split("\n")
    words = text.split()
    return {
        "characters": len(text),
        "characters_no_spaces": len(text.replace(" ", "").replace("\n", "")),
        "words": len(words),
        "lines": len(lines),
        "paragraphs": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
        "sentences": len([s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]),
    }


def text_diff(text1: str, text2: str) -> str:
    """Generate a unified diff between two texts."""
    import difflib
    # Without line endings on the lines themselves: a last line with no
    # newline used to run into the next one ("-b+c").
    diff = list(difflib.unified_diff(text1.splitlines(), text2.splitlines(),
                                     fromfile="Original", tofile="Modified", lineterm=""))
    return "\n".join(diff) + "\n" if diff else ""


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


# ── Transcription ──

def _check_transcribe_deps():
    """Return (whisper_available, diarize_available) booleans."""
    whisper_ok = False
    diarize_ok = False
    try:
        import faster_whisper
        whisper_ok = True
    except ImportError:
        pass
    try:
        from pyannote.audio import Pipeline
        diarize_ok = True
    except ImportError:
        pass
    return whisper_ok, diarize_ok


def extract_audio_for_transcription(input_path: str, output_path: str):
    """Extract audio from any input to 16kHz mono WAV for Whisper."""
    cmd = [
        _ffmpeg_exe(), "-y", "-i", input_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        output_path
    ]
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=MEDIA_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr.decode('utf-8', errors='replace')[:500]}")


def transcribe_audio(audio_path: str, model_size: str = "base",
                     language: str | None = None, progress_cb=None):
    """Transcribe audio using faster-whisper. Returns (segments, detected_language)."""
    from faster_whisper import WhisperModel

    if progress_cb:
        progress_cb(5, "loading_model", f"Loading {model_size} model...")

    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    if progress_cb:
        progress_cb(15, "transcribing", "Starting transcription...")

    segments_iter, info = model.transcribe(
        audio_path, language=language, word_timestamps=True, beam_size=5,
    )

    detected_language = info.language
    duration = info.duration

    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word})

        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": words,
        })

        if progress_cb and duration > 0:
            pct = min(int(15 + (seg.end / duration) * 55), 70)
            progress_cb(pct, "transcribing", f"Transcribing... {pct}%")

    return segments, detected_language


def diarize_audio(audio_path: str, hf_token: str,
                  num_speakers: int | None = None, progress_cb=None):
    """Run speaker diarization using pyannote.audio."""
    from pyannote.audio import Pipeline

    if progress_cb:
        progress_cb(72, "diarizing", "Loading diarization model...")

    # pyannote.audio 4 renamed use_auth_token to token.
    import inspect
    auth = "token" if "token" in inspect.signature(Pipeline.from_pretrained).parameters else "use_auth_token"
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", **{auth: hf_token})

    if progress_cb:
        progress_cb(78, "diarizing", "Identifying speakers...")

    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers

    diarization = pipeline(audio_path, **kwargs)
    # pyannote.audio 4 wraps the speaker turns in a result object.
    diarization = getattr(diarization, "speaker_diarization", diarization)

    if progress_cb:
        progress_cb(90, "diarizing", "Processing speaker labels...")

    result = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        result.append({"start": round(turn.start, 3), "end": round(turn.end, 3), "speaker": speaker})

    return result


def merge_transcription_and_diarization(segments: list[dict], diarization: list[dict]):
    """Assign speaker labels to transcription segments by maximum time overlap."""
    for seg in segments:
        best_speaker = "Speaker 1"
        best_overlap = 0.0
        seg_start, seg_end = seg["start"], seg["end"]

        for d in diarization:
            overlap = max(0.0, min(seg_end, d["end"]) - max(seg_start, d["start"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = d["speaker"]

        if best_speaker.startswith("SPEAKER_"):
            try:
                best_speaker = f"Speaker {int(best_speaker.split('_')[-1]) + 1}"
            except ValueError:
                pass
        seg["speaker"] = best_speaker

    return segments


def _fmt_ts(seconds: float, sep: str = ".") -> str:
    """Convert seconds to HH:MM:SS.mmm format."""
    # Whole milliseconds first: int((2.3 % 1) * 1000) is 299, not 300.
    total_ms = max(0, int(round(seconds * 1000)))
    s, ms = divmod(total_ms, 1000)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}{sep}{ms:03d}"


def _srt_ts(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    return _fmt_ts(seconds, ",")


def _cue_text(text: str) -> str:
    """A blank line ends a subtitle cue, so one inside the text would cut it short."""
    return "\n".join(line for line in text.splitlines() if line.strip())


def _clean_segments(segments) -> list[dict]:
    """Segments as sent back by the transcript page can be edited or partial;
    fill the fields every exporter needs instead of crashing on a missing one."""
    out = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        try:
            start, end = float(seg.get("start") or 0), float(seg.get("end") or 0)
        except (TypeError, ValueError):
            start = end = 0.0
        out.append({**seg, "start": start, "end": end, "text": str(seg.get("text") or "")})
    return out


def export_transcript_txt(segments: list[dict], include_speakers: bool = True) -> str:
    segments = _clean_segments(segments)
    lines = []
    for seg in segments:
        prefix = f"[{seg.get('speaker', '')}] " if include_speakers and seg.get('speaker') else ""
        lines.append(f"{prefix}{seg['text']}")
    return "\n".join(lines)


def export_transcript_srt(segments: list[dict]) -> str:
    segments = _clean_segments(segments)
    lines = []
    for i, seg in enumerate(segments, 1):
        speaker = f"[{seg.get('speaker', '')}] " if seg.get('speaker') else ""
        lines.append(f"{i}")
        lines.append(f"{_srt_ts(seg['start'])} --> {_srt_ts(seg['end'])}")
        lines.append(f"{speaker}{_cue_text(seg['text'])}")
        lines.append("")
    return "\n".join(lines)


def export_transcript_vtt(segments: list[dict]) -> str:
    segments = _clean_segments(segments)
    lines = ["WEBVTT", ""]
    for seg in segments:
        speaker = f"<v {seg.get('speaker', 'Speaker')}>" if seg.get('speaker') else ""
        lines.append(f"{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}")
        lines.append(f"{speaker}{_cue_text(seg['text'])}")
        lines.append("")
    return "\n".join(lines)


def export_transcript_csv(segments: list[dict]) -> str:
    segments = _clean_segments(segments)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["start", "end", "speaker", "text"])
    for seg in segments:
        writer.writerow([_fmt_ts(seg["start"]), _fmt_ts(seg["end"]), seg.get("speaker", ""), seg["text"]])
    return output.getvalue()
