"""Additional image tools: HEIC conversion, adjustments, EXIF reading, borders,
favicon sets, upscaling, collages/sprite sheets, and ASCII art.

Pure functions only. No Flask imports. Called by routes_images2.py.
"""

import io
import json
import math
from fractions import Fraction

from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageOps
from PIL.ExifTags import TAGS, GPSTAGS

from sdexe.tools import _ensure_processable, _save_image, create_zip

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    HEIF_AVAILABLE = False


# ── Helpers ──

def _parse_hex(color: str, default=(255, 255, 255)) -> tuple:
    """Parse '#rgb', '#rrggbb', or '#rrggbbaa' into an RGB(A) tuple."""
    if not color:
        return default
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) not in (6, 8):
        raise ValueError(f"Invalid color: {color}")
    try:
        vals = tuple(int(c[i:i + 2], 16) for i in range(0, len(c), 2))
    except ValueError:
        raise ValueError(f"Invalid color: {color}")
    return vals


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── HEIC → JPG / PNG ──

def heic_to_image(stream, fmt: str = "jpg", quality: int = 90) -> bytes:
    """Decode a HEIC/HEIF stream and re-encode as JPG or PNG bytes."""
    if not HEIF_AVAILABLE:
        raise ValueError("HEIC support is not installed (pillow-heif missing)")
    img = Image.open(stream)
    img.load()
    img = ImageOps.exif_transpose(img)
    fmt = "png" if fmt == "png" else "jpg"
    buf = io.BytesIO()
    if fmt == "jpg":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(buf, "JPEG", quality=int(_clamp(quality, 1, 100)), optimize=True)
    else:
        img = _ensure_processable(img)
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ── Adjust ──

def adjust_image_full(img: Image.Image, brightness: float = 100, contrast: float = 100,
                      saturation: float = 100, sharpness: float = 100) -> Image.Image:
    """Adjust brightness/contrast/saturation/sharpness. Values are percents; 100 = unchanged."""
    img = _ensure_processable(img)
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA")
    factors = [
        (ImageEnhance.Brightness, brightness),
        (ImageEnhance.Contrast, contrast),
        (ImageEnhance.Color, saturation),
        (ImageEnhance.Sharpness, sharpness),
    ]
    for enhancer, pct in factors:
        factor = _clamp(float(pct), 0, 200) / 100.0
        if abs(factor - 1.0) > 1e-6:
            img = enhancer(img).enhance(factor)
    return img


# ── EXIF Viewer ──

def _exif_value_to_json(value):
    if isinstance(value, bytes):
        if len(value) > 64:
            return f"<{len(value)} bytes>"
        try:
            return value.decode("utf-8").strip("\x00")
        except Exception:
            return value.hex()
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, (tuple, list)):
        return [_exif_value_to_json(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _exif_value_to_json(v) for k, v in value.items()}
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    try:
        # IFDRational and friends
        return float(value)
    except Exception:
        return str(value)


def _dms_to_decimal(dms, ref) -> float | None:
    try:
        d, m, s = (float(x) for x in dms)
    except Exception:
        return None
    dec = d + m / 60.0 + s / 3600.0
    if ref in ("S", "W"):
        dec = -dec
    return round(dec, 6)


def read_exif(stream, filename: str = "", file_size: int = 0) -> dict:
    """Return a JSON-friendly dict of image info and readable EXIF tags."""
    img = Image.open(stream)
    result = {
        "file": {
            "name": filename,
            "size_bytes": file_size,
            "format": img.format or "unknown",
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
        },
        "exif": {},
        "gps": None,
    }
    try:
        exif = img.getexif()
    except Exception:
        exif = None
    if not exif:
        return result

    tags = {}
    for tag_id, value in exif.items():
        name = TAGS.get(tag_id, f"Tag{tag_id}")
        if name in ("GPSInfo", "ExifOffset", "MakerNote"):
            continue
        tags[name] = _exif_value_to_json(value)

    # Sub-IFD (ExposureTime, FNumber, ISO, LensModel, etc.)
    try:
        sub = exif.get_ifd(0x8769)
        for tag_id, value in sub.items():
            name = TAGS.get(tag_id, f"Tag{tag_id}")
            if name in ("MakerNote", "UserComment"):
                continue
            tags[name] = _exif_value_to_json(value)
    except Exception:
        pass

    # GPS
    try:
        gps_ifd = exif.get_ifd(0x8825)
    except Exception:
        gps_ifd = None
    if gps_ifd:
        gps = {GPSTAGS.get(k, f"GPS{k}"): _exif_value_to_json(v) for k, v in gps_ifd.items()}
        lat = _dms_to_decimal(gps_ifd.get(2), gps_ifd.get(1)) if gps_ifd.get(2) else None
        lon = _dms_to_decimal(gps_ifd.get(4), gps_ifd.get(3)) if gps_ifd.get(4) else None
        alt = gps_ifd.get(6)
        gps_out = {"raw": gps}
        if lat is not None and lon is not None:
            gps_out["latitude"] = lat
            gps_out["longitude"] = lon
            gps_out["maps_url"] = f"https://www.google.com/maps?q={lat},{lon}"
        if alt is not None:
            try:
                alt_val = float(alt)
                if gps_ifd.get(5) == 1:
                    alt_val = -alt_val
                gps_out["altitude_m"] = round(alt_val, 2)
            except Exception:
                pass
        result["gps"] = gps_out

    result["exif"] = tags
    return result


# ── Border / Padding ──

def _round_corners(img: Image.Image, radius: int) -> Image.Image:
    """Apply rounded corners (transparent outside) to an RGBA image."""
    if radius <= 0:
        return img
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius=radius, fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def add_border(img: Image.Image, size: int = 20, color: str = "#ffffff",
               mode: str = "border", radius: int = 0, transparent: bool = False) -> Image.Image:
    """Add a solid frame (border) or padding around an image.

    mode='border': solid color frame around the image.
    mode='padding': transparent padding when `transparent` is True (PNG output),
                    otherwise a colored padding.
    radius: optional rounded corners applied to the inner image (padding) or
            the whole result (border).
    """
    size = int(_clamp(size, 0, 2000))
    radius = int(_clamp(radius, 0, 2000))
    img = _ensure_processable(img)
    rgb = _parse_hex(color)[:3]

    if mode == "padding" and transparent:
        inner = _round_corners(img.convert("RGBA"), radius) if radius else img.convert("RGBA")
        canvas = Image.new("RGBA", (inner.width + 2 * size, inner.height + 2 * size), (0, 0, 0, 0))
        canvas.paste(inner, (size, size), inner)
        return canvas

    has_alpha = img.mode in ("RGBA", "LA")
    if mode == "padding":
        inner = _round_corners(img.convert("RGBA"), radius) if radius else img.convert("RGBA")
        canvas = Image.new("RGBA", (inner.width + 2 * size, inner.height + 2 * size), rgb + (255,))
        canvas.paste(inner, (size, size), inner)
        return canvas if has_alpha else canvas.convert("RGB")

    # border: solid frame, rounded corners apply to the full result
    base = img.convert("RGBA")
    canvas = Image.new("RGBA", (base.width + 2 * size, base.height + 2 * size), rgb + (255,))
    canvas.paste(base, (size, size), base)
    if radius:
        return _round_corners(canvas, radius)
    return canvas if has_alpha else canvas.convert("RGB")


# ── Favicon Set ──

def _center_square(img: Image.Image) -> Image.Image:
    side = min(img.width, img.height)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


_FAVICON_MANIFEST = {
    "name": "",
    "short_name": "",
    "icons": [
        {"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"},
    ],
    "theme_color": "#ffffff",
    "background_color": "#ffffff",
    "display": "standalone",
}

_FAVICON_SNIPPET = """<link rel="icon" type="image/x-icon" href="/favicon.ico">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#ffffff">
"""


def favicon_set(img: Image.Image) -> bytes:
    """Build a ZIP with a full favicon set from a single image."""
    img = ImageOps.exif_transpose(_ensure_processable(img)).convert("RGBA")
    square = _center_square(img)

    def sized(n: int) -> Image.Image:
        return square.resize((n, n), Image.LANCZOS)

    def png_bytes(n: int) -> bytes:
        buf = io.BytesIO()
        sized(n).save(buf, "PNG", optimize=True)
        return buf.getvalue()

    ico_buf = io.BytesIO()
    sized(48).save(ico_buf, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    files = [
        ("favicon.ico", ico_buf.getvalue()),
        ("favicon-16x16.png", png_bytes(16)),
        ("favicon-32x32.png", png_bytes(32)),
        ("apple-touch-icon.png", png_bytes(180)),
        ("android-chrome-192x192.png", png_bytes(192)),
        ("android-chrome-512x512.png", png_bytes(512)),
        ("site.webmanifest", json.dumps(_FAVICON_MANIFEST, indent=2).encode("utf-8")),
        ("snippet.html", _FAVICON_SNIPPET.encode("utf-8")),
    ]
    return create_zip(files)


# ── Upscale ──

MAX_UPSCALE_PIXELS = 80_000_000  # ~80 MP output cap


def upscale_image(img: Image.Image, factor: int = 2) -> Image.Image:
    """Resampling upscale (LANCZOS) followed by a light unsharp mask."""
    factor = int(factor)
    if factor not in (2, 3, 4):
        raise ValueError("Factor must be 2, 3, or 4")
    img = _ensure_processable(img)
    new_w, new_h = img.width * factor, img.height * factor
    if new_w * new_h > MAX_UPSCALE_PIXELS:
        raise ValueError(f"Output would be {new_w}×{new_h}, which exceeds the "
                         f"{MAX_UPSCALE_PIXELS // 1_000_000} megapixel limit")
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA")
    out = img.resize((new_w, new_h), Image.LANCZOS)
    out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    return out


# ── Collage / Sprite Sheet ──

def _fit_cell(img: Image.Image, cell: int, fit: str) -> Image.Image:
    """Scale an image into a cell x cell box. contain keeps whole image; cover fills and crops."""
    if fit == "cover":
        return ImageOps.fit(img, (cell, cell), Image.LANCZOS, centering=(0.5, 0.5))
    ratio = min(cell / img.width, cell / img.height)
    w = max(1, int(round(img.width * ratio)))
    h = max(1, int(round(img.height * ratio)))
    return img.resize((w, h), Image.LANCZOS)


def _css_class_name(name: str, idx: int) -> str:
    base = name.rsplit(".", 1)[0] if "." in name else name
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in base).strip("-").lower()
    if not cleaned or not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"sprite-{idx + 1}" if not cleaned else f"s-{cleaned}"
    return cleaned


def make_collage(images: list[tuple[str, Image.Image]], columns: int = 0, cell: int = 256,
                 gap: int = 0, background: str = "#ffffff", fit: str = "contain",
                 transparent: bool = False) -> tuple[Image.Image, str]:
    """Arrange images into a grid. Returns (sheet, css) where css maps each
    image to a sprite class with background-position."""
    n = len(images)
    if n == 0:
        raise ValueError("No images provided")
    cell = int(_clamp(cell, 8, 2048))
    gap = int(_clamp(gap, 0, 512))
    columns = int(columns) if columns else 0
    if columns <= 0:
        columns = max(1, math.ceil(math.sqrt(n)))
    columns = min(columns, n)
    rows = math.ceil(n / columns)

    sheet_w = columns * cell + (columns - 1) * gap
    sheet_h = rows * cell + (rows - 1) * gap
    if sheet_w * sheet_h > MAX_UPSCALE_PIXELS:
        raise ValueError("Sheet is too large; reduce the cell size or number of images")

    if transparent:
        bg = (0, 0, 0, 0)
    else:
        bg = _parse_hex(background)[:3] + (255,)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), bg)

    css_lines = [
        f".sprite {{ background-image: url('sprite.png'); background-repeat: no-repeat; "
        f"display: inline-block; width: {cell}px; height: {cell}px; }}",
    ]
    used_names = set()
    for i, (name, img) in enumerate(images):
        img = _ensure_processable(img).convert("RGBA")
        thumb = _fit_cell(img, cell, fit)
        r, c = divmod(i, columns)
        x0 = c * (cell + gap)
        y0 = r * (cell + gap)
        ox = x0 + (cell - thumb.width) // 2
        oy = y0 + (cell - thumb.height) // 2
        sheet.paste(thumb, (ox, oy), thumb)

        cls = _css_class_name(name, i)
        if cls in used_names:
            cls = f"{cls}-{i + 1}"
        used_names.add(cls)
        px = lambda v: f"-{v}px" if v else "0"
        css_lines.append(f".sprite.{cls} {{ background-position: {px(x0)} {px(y0)}; }}")

    css = "\n".join(css_lines) + "\n"
    if not transparent:
        sheet = sheet.convert("RGB")
    return sheet, css


def collage_zip(sheet: Image.Image, css: str) -> bytes:
    return create_zip([
        ("sprite.png", _save_image(sheet, "png")),
        ("sprite.css", css.encode("utf-8")),
    ])


# ── Image → ASCII ──

_ASCII_CHARSETS = {
    # dark → light
    "standard": "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. ",
    "blocks": "█▓▒░ ",
    "simple": "@%#*+=-:. ",
}


def image_to_ascii(img: Image.Image, width: int = 100, charset: str = "standard",
                   invert: bool = False) -> str:
    """Convert an image to ASCII art. Returns the text."""
    width = int(_clamp(width, 10, 400))
    chars = _ASCII_CHARSETS.get(charset, _ASCII_CHARSETS["standard"])
    if invert:
        chars = chars[::-1]

    img = _ensure_processable(img)
    if img.mode in ("RGBA", "LA"):
        # Flatten transparency on white so transparent areas read as light.
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img.convert("RGBA"), (0, 0), img.convert("RGBA"))
        img = bg
    gray = img.convert("L")

    # Monospace glyphs are roughly twice as tall as they are wide.
    aspect = gray.height / gray.width
    height = max(1, int(round(width * aspect * 0.5)))
    gray = gray.resize((width, height), Image.LANCZOS)

    n = len(chars)
    pixels = list(gray.getdata())
    lines = []
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        lines.append("".join(chars[min(n - 1, (p * n) // 256)] for p in row))
    return "\n".join(lines)
