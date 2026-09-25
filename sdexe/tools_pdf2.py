"""Additional PDF tools: rasterising, OCR, Office conversion, image stamping,
page resizing and flattening. Pure functions, no Flask imports.
"""

import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject


# ── Shared helpers ──

PAGE_SIZES = {
    "a3": (841.89, 1190.55),
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}

OFFICE_EXTENSIONS = {
    ".doc", ".docx", ".dot", ".dotx", ".odt", ".ott", ".rtf", ".txt", ".wpd",
    ".xls", ".xlsx", ".xlsm", ".ods", ".ots", ".csv",
    ".ppt", ".pptx", ".pps", ".ppsx", ".odp", ".otp",
    ".html", ".htm", ".epub", ".pages", ".numbers", ".key",
}


def parse_pages(pages_str: str, total: int) -> list[int]:
    """Parse "all" or "1-3,5" into a sorted list of 0-based page indices.
    Raises ValueError on malformed input or a selection outside the document.
    """
    pages_str = (pages_str or "").strip().lower()
    if not pages_str or pages_str == "all":
        return list(range(total))
    indices: set[int] = set()
    for part in pages_str.split(","):
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
    return sorted(indices)


def _render_pages(pdf_bytes: bytes, dpi: int, indices: list[int] | None = None) -> list[Image.Image]:
    """Render selected pages (all by default) of a PDF to RGB PIL images."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        if indices is None:
            indices = list(range(len(doc)))
        scale = dpi / 72.0
        out = []
        for i in indices:
            page = doc[i]
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil()
            if img.mode != "RGB":
                img = img.convert("RGB")
            out.append(img)
            page.close()
        return out
    finally:
        doc.close()


def _find_binary(name: str, extra_paths: list[str]) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for p in extra_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def tesseract_path() -> str | None:
    return _find_binary("tesseract", [
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ])


def soffice_path() -> str | None:
    return _find_binary("soffice", [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
        "/snap/bin/libreoffice",
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ])


def _install_hint(what: str, brew: str, apt: str, url: str) -> str:
    if sys.platform == "darwin":
        return f"{what} is not installed. On Mac: brew install {brew}"
    if sys.platform.startswith("linux"):
        return f"{what} is not installed. On Linux: sudo apt install {apt}"
    return f"{what} is not installed. Download it from {url}"


# ── 1. PDF → Images ──

def pdf_to_images(stream: BinaryIO, fmt: str = "png", dpi: int = 150,
                  pages_str: str = "all") -> list[tuple[str, bytes]]:
    """Render PDF pages to images. Returns list of (filename, image_bytes)."""
    fmt = (fmt or "png").lower()
    if fmt not in ("png", "jpg"):
        raise ValueError("Format must be png or jpg")
    dpi = int(dpi)
    if dpi not in (72, 150, 300):
        raise ValueError("DPI must be 72, 150 or 300")
    data = stream.read()
    total = len(PdfReader(io.BytesIO(data)).pages)
    indices = parse_pages(pages_str, total)
    images = _render_pages(data, dpi, indices)
    results = []
    for idx, img in zip(indices, images):
        buf = io.BytesIO()
        if fmt == "jpg":
            img.save(buf, "JPEG", quality=90, optimize=True)
        else:
            img.save(buf, "PNG", optimize=True)
        results.append((f"page_{idx + 1}.{fmt}", buf.getvalue()))
    return results


# ── 2. OCR ──

def ocr_document(stream: BinaryIO, filename: str, language: str = "eng") -> tuple[str, int]:
    """OCR a PDF or image. Returns (text, page_count)."""
    tess = tesseract_path()
    if not tess:
        raise ValueError(_install_hint("Tesseract", "tesseract", "tesseract-ocr",
                                       "https://github.com/UB-Mannheim/tesseract/wiki"))
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tess

    language = (language or "eng").strip()
    if not language.replace("+", "").replace("_", "").isalnum():
        raise ValueError("Invalid language code")

    data = stream.read()
    is_pdf = filename.lower().endswith(".pdf") or data[:5] == b"%PDF-"
    if is_pdf:
        images = _render_pages(data, 300)
    else:
        img = Image.open(io.BytesIO(data))
        img.load()
        images = [img.convert("RGB") if img.mode not in ("RGB", "L") else img]

    if not images:
        raise ValueError("Document has no pages")

    chunks = []
    for i, img in enumerate(images, 1):
        try:
            text = pytesseract.image_to_string(img, lang=language)
        except pytesseract.TesseractError as e:
            msg = str(e)
            if "Failed loading language" in msg or "tessdata" in msg:
                raise ValueError(f"Tesseract language '{language}' is not installed.")
            raise ValueError(f"OCR failed: {msg}")
        text = text.strip()
        if len(images) > 1:
            chunks.append(f"--- Page {i} ---\n{text}")
        else:
            chunks.append(text)
    return "\n\n".join(chunks), len(images)


# ── 3. Office → PDF ──

def office_to_pdf(stream: BinaryIO, filename: str, timeout: int = 120) -> bytes:
    """Convert an Office document to PDF via LibreOffice headless."""
    ext = Path(filename).suffix.lower()
    if not ext:
        raise ValueError("File has no extension; cannot determine document type")
    if ext == ".pdf":
        raise ValueError("That file is already a PDF")
    if ext not in OFFICE_EXTENSIONS:
        raise ValueError(f"Unsupported document type: {ext}")

    soffice = soffice_path()
    if not soffice:
        raise ValueError(_install_hint("LibreOffice", "--cask libreoffice", "libreoffice",
                                       "https://www.libreoffice.org/download/"))

    with tempfile.TemporaryDirectory(prefix="sdexe_office_") as tmp:
        src = Path(tmp) / f"input{ext}"
        src.write_bytes(stream.read())
        outdir = Path(tmp) / "out"
        outdir.mkdir()
        # A private profile dir avoids clashes with a running LibreOffice GUI.
        profile = Path(tmp) / "profile"
        env = dict(os.environ, HOME=os.environ.get("HOME", tmp))
        cmd = [
            soffice, "--headless", "--norestore", "--nologo",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to", "pdf", "--outdir", str(outdir), str(src),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            raise ValueError(f"Conversion timed out after {timeout}s")
        out_pdf = outdir / "input.pdf"
        if proc.returncode != 0 or not out_pdf.exists():
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            detail = detail[-1] if detail else "LibreOffice produced no output"
            raise ValueError(f"Conversion failed: {detail}")
        return out_pdf.read_bytes()


# ── 4. Stamp Image ──

def _image_to_pdf_page(img: Image.Image, opacity: float) -> tuple[bytes, float, float]:
    """Turn an image into a single-page PDF with the given opacity baked into
    its alpha channel. Returns (pdf_bytes, width_pt, height_pt)."""
    img = img.convert("RGBA")
    if opacity < 1.0:
        alpha = img.getchannel("A").point(lambda a: int(a * opacity))
        img.putalpha(alpha)
    # Pillow drops alpha when writing PDF and pypdf cannot embed images, so
    # build a minimal one-page PDF by hand with the alpha channel as an SMask.
    w, h = img.size
    rgb = img.convert("RGB").tobytes()
    a = img.getchannel("A").tobytes()

    import zlib
    rgb_z = zlib.compress(rgb)
    a_z = zlib.compress(a)

    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] "
        f"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 6 0 R >>".encode()
    )
    objs.append(
        f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB "
        f"/BitsPerComponent 8 /Filter /FlateDecode /SMask 5 0 R /Length {len(rgb_z)} >>\nstream\n".encode()
        + rgb_z + b"\nendstream"
    )
    objs.append(
        f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray "
        f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(a_z)} >>\nstream\n".encode()
        + a_z + b"\nendstream"
    )
    content = f"q {w} 0 0 {h} 0 0 cm /Im0 Do Q".encode()
    objs.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue(), float(w), float(h)


def stamp_pdf(stream: BinaryIO, image_stream: BinaryIO, position: str = "bottom-right",
              scale: float = 25, opacity: float = 100, pages_str: str = "all") -> bytes:
    """Stamp an image (logo/signature) onto the selected pages of a PDF."""
    scale = float(scale)
    if not 1 <= scale <= 100:
        raise ValueError("Scale must be between 1 and 100 percent")
    opacity = max(0.0, min(100.0, float(opacity))) / 100.0
    if position not in ("top-left", "top-right", "bottom-left", "bottom-right", "center"):
        raise ValueError("Invalid position")

    img = Image.open(image_stream)
    img.load()
    stamp_pdf_bytes, iw, ih = _image_to_pdf_page(img, opacity)
    stamp_reader = PdfReader(io.BytesIO(stamp_pdf_bytes))
    stamp_page = stamp_reader.pages[0]

    reader = PdfReader(stream)
    writer = PdfWriter()
    total = len(reader.pages)
    targets = set(parse_pages(pages_str, total))
    margin = 24.0

    for i, page in enumerate(reader.pages):
        if i in targets:
            box = page.mediabox
            pw, ph = float(box.width), float(box.height)
            x0, y0 = float(box.left), float(box.bottom)
            target_w = pw * scale / 100.0
            factor = target_w / iw
            target_h = ih * factor
            if position == "top-left":
                x, y = x0 + margin, y0 + ph - margin - target_h
            elif position == "top-right":
                x, y = x0 + pw - margin - target_w, y0 + ph - margin - target_h
            elif position == "bottom-left":
                x, y = x0 + margin, y0 + margin
            elif position == "bottom-right":
                x, y = x0 + pw - margin - target_w, y0 + margin
            else:
                x, y = x0 + (pw - target_w) / 2, y0 + (ph - target_h) / 2
            t = Transformation().scale(factor, factor).translate(x, y)
            page.merge_transformed_page(stamp_page, t, over=True)
        writer.add_page(page)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── 5. Resize Pages ──

def resize_pdf_pages(stream: BinaryIO, size: str = "a4", fit: str = "fit") -> bytes:
    """Scale every page onto a target paper size, content centred.
    fit="fit" keeps the whole page visible; fit="fill" covers the page and crops."""
    size = (size or "a4").lower()
    if size not in PAGE_SIZES:
        raise ValueError("Size must be one of: " + ", ".join(PAGE_SIZES))
    if fit not in ("fit", "fill"):
        raise ValueError("Fit must be fit or fill")
    tw, th = PAGE_SIZES[size]

    reader = PdfReader(stream)
    writer = PdfWriter()
    for src in reader.pages:
        # Honour /Rotate so a landscape-rotated page lands on a landscape sheet.
        rot = (src.rotation or 0) % 360
        if rot:
            src.transfer_rotation_to_content()
        box = src.mediabox
        sw, sh = float(box.width), float(box.height)
        landscape = sw > sh
        w, h = (th, tw) if landscape else (tw, th)
        ratio = (min if fit == "fit" else max)(w / sw, h / sh)
        dx = (w - sw * ratio) / 2 - float(box.left) * ratio
        dy = (h - sh * ratio) / 2 - float(box.bottom) * ratio
        dest = writer.add_blank_page(width=w, height=h)
        dest.merge_transformed_page(src, Transformation().scale(ratio, ratio).translate(dx, dy))
        dest.mediabox = RectangleObject((0, 0, w, h))
        dest.cropbox = RectangleObject((0, 0, w, h))
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── 6. Flatten ──

def flatten_pdf(stream: BinaryIO, dpi: int = 150) -> bytes:
    """Rasterise every page and rebuild the PDF from images, dropping forms,
    annotations and layers. Page dimensions in points are preserved."""
    data = stream.read()
    reader = PdfReader(io.BytesIO(data))
    sizes = []
    for p in reader.pages:
        rot = (p.rotation or 0) % 360
        w, h = float(p.mediabox.width), float(p.mediabox.height)
        sizes.append((h, w) if rot in (90, 270) else (w, h))
    images = _render_pages(data, dpi)
    if not images:
        raise ValueError("PDF has no pages")

    writer = PdfWriter()
    for img, (w, h) in zip(images, sizes):
        # Pillow embeds the image as JPEG; scale the resulting page back to
        # the original page dimensions so the flattened file has the same size.
        page_pdf = io.BytesIO()
        img.save(page_pdf, "PDF", resolution=dpi, quality=88)
        page_pdf.seek(0)
        src = PdfReader(page_pdf).pages[0]
        sw, sh = float(src.mediabox.width), float(src.mediabox.height)
        dest = writer.add_blank_page(width=w, height=h)
        dest.merge_transformed_page(src, Transformation().scale(w / sw, h / sh))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
