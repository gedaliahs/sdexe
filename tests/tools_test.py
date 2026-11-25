#!/usr/bin/env python3
"""Edge-case tests for the pure tool functions in sdexe/tools*.py.

The smoke tests check that every route and command runs; this one checks the
results on awkward inputs: odd image modes, rotated/cropped/encrypted PDFs,
malformed data files, hostile archives, and audio/video with missing streams
or odd sizes. Each case is a regression test for a bug that was fixed.

Everything is generated here, nothing touches the network. Cases that need
ffmpeg or an optional library are reported as SKIP when it is missing.
DeprecationWarnings raised from sdexe's own calls count as failures, so the
same file can be run against older and newer pypdf / Pillow.

Usage:
    python tests/tools_test.py            # exits non-zero on any FAIL
    python tests/tools_test.py --verbose  # print every case
    python tests/tools_test.py image pdf  # only cases whose name contains a word
"""

import io
import json
import logging
import shutil
import sys
import tempfile
import traceback
import warnings
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

warnings.filterwarnings("error", category=DeprecationWarning, module=r"sdexe(\.|$)")
logging.getLogger("pypdf").setLevel(logging.ERROR)  # it logs every malformed fixture

from PIL import Image, ImageCms  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import (  # noqa: E402
    ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject,
    NumberObject, RectangleObject, TextStringObject,
)

from sdexe import tools, tools_av2 as av2, tools_convert2 as conv2, tools_images2 as img2, tools_pdf2 as pdf2  # noqa: E402

logging.getLogger("sdexe").setLevel(logging.CRITICAL)  # failed ffmpeg runs are expected here

VERBOSE = "--verbose" in sys.argv
ONLY = [a for a in sys.argv[1:] if not a.startswith("-")]
B = io.BytesIO

CASES = []


class Skip(Exception):
    pass


def case(name):
    def register(fn):
        CASES.append((name, fn))
        return fn
    return register


def eq(got, want, what=""):
    assert got == want, f"{what + ': ' if what else ''}got {got!r}, want {want!r}"


def near(got, want, tol, what=""):
    assert abs(got - want) <= tol, f"{what + ': ' if what else ''}got {got!r}, want {want!r} ±{tol}"


def raises(exc, fn, contains=""):
    try:
        fn()
    except exc as e:
        assert contains.lower() in str(e).lower(), f"error {str(e)!r} lacks {contains!r}"
        return e
    except Exception as e:
        raise AssertionError(f"raised {type(e).__name__}: {e}, want {exc.__name__}")
    raise AssertionError(f"did not raise {exc.__name__}")


# ── Image fixtures ──

def reopen(data: bytes) -> Image.Image:
    img = Image.open(B(data))
    img.load()
    return img


def image(mode: str, size=(40, 30)) -> Image.Image:
    if mode == "P+t":  # palette with a transparent colour, as in a GIF
        im = Image.new("RGBA", size, (255, 0, 0, 255))
        im.paste((0, 0, 0, 0), (0, 0, size[0] // 2, size[1]))
        buf = B()
        im.save(buf, "GIF")
        return reopen(buf.getvalue())
    fill = {"1": 1, "L": 128, "LA": (200, 100), "RGB": (10, 200, 30), "RGBA": (255, 0, 0, 0),
            "CMYK": (0, 255, 255, 0), "I": 30000, "I;16": 30000, "F": 0.5}
    if mode == "P":
        return Image.new("RGB", size, (10, 200, 30)).convert("P")
    if mode == "PA":
        return Image.new("RGBA", size, (255, 0, 0, 128)).convert("PA")
    return Image.new(mode, size, fill[mode])


MODES = ["1", "L", "LA", "P", "P+t", "PA", "RGB", "RGBA", "CMYK", "I", "I;16", "F"]


def srgb_profile() -> bytes:
    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


# ── Images ──

@case("image: every mode through every edit and every output format")
def _():
    ops = {
        "resize": lambda im: tools.resize_image(im, "dimensions", width=20),
        "crop": lambda im: tools.crop_image(im, 2, 2, 20, 20),
        "rotate": lambda im: tools.rotate_image(im, 45),
        "strip": tools.strip_exif,
        "flip": tools.flip_image,
        "gray": tools.grayscale_image,
        "blur": lambda im: tools.blur_image(im, 2),
        "watermark": lambda im: tools.watermark_image(im, "hi"),
        "adjust": lambda im: tools.adjust_image(im, 1.2, 1.2, 1.2),
        "adjust2": lambda im: img2.adjust_image_full(im, 120, 120, 120, 120),
        "border": lambda im: img2.add_border(im, 5),
        "upscale": lambda im: img2.upscale_image(im, 2),
        "collage": lambda im: img2.make_collage([("a.png", im), ("b.png", im)])[0],
    }
    bad = []
    for mode in MODES:
        for name, op in ops.items():
            try:
                out = op(image(mode))
                for fmt in ("png", "jpg", "webp", "gif"):
                    reopen(tools._save_image(out, tools.output_image_format("x." + fmt, out)))
            except Exception as e:
                bad.append(f"{mode} {name}: {e}")
        for fmt in ("png", "jpg", "webp"):
            try:
                reopen(tools.compress_image(image(mode), 80, fmt))
                reopen(tools.convert_image(image(mode), fmt))
            except Exception as e:
                bad.append(f"{mode} -> {fmt}: {e}")
        for name, fn in (("ascii", lambda im: img2.image_to_ascii(im, 20)), ("ico", tools.image_to_ico),
                         ("favicon", img2.favicon_set), ("pdf", lambda im: tools.images_to_pdf([im]))):
            try:
                fn(image(mode))
            except Exception as e:
                bad.append(f"{mode} {name}: {e}")
    assert not bad, "; ".join(bad[:6])


@case("image: transparency becomes white, not black, in a JPEG")
def _():
    clear = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    for label, data in (("convert", tools.convert_image(clear, "jpg")),
                        ("compress", tools.compress_image(clear, 80, "jpg")),
                        ("save", tools._save_image(clear, "jpg")),
                        ("save palette", tools._save_image(image("P+t"), "jpg"))):
        px = reopen(data).getpixel((1, 1))
        assert min(px) > 240, f"{label}: {px}"


@case("image: 16-bit gray is scaled to 8 bits, not clipped to white")
def _():
    deep = Image.new("I;16", (8, 8), 30000)  # mid gray
    near(reopen(tools.convert_image(deep, "jpg")).getpixel((0, 0)), 117, 3, "convert jpg")
    near(reopen(tools.compress_image(deep, 80, "jpg")).getpixel((0, 0)), 117, 3, "compress jpg")
    near(tools.grayscale_image(deep).getpixel((0, 0)), 117, 3, "grayscale")
    near(img2.upscale_image(deep, 2).getpixel((0, 0)), 117, 3, "upscale")
    near(reopen(tools._save_image(Image.new("I", (4, 4), 30000), "png")).getpixel((0, 0)), 117, 3, "mode I png")
    eq(reopen(tools.compress_image(deep, 80, "png")).mode, "I;16", "PNG keeps 16 bits")


@case("image: colour profile survives JPEG/WebP saves and edits")
def _():
    im = Image.new("RGB", (8, 8), (200, 10, 10))
    im.info["icc_profile"] = srgb_profile()
    outs = {
        "save jpg": tools._save_image(im, "jpg"), "save webp": tools._save_image(im, "webp"),
        "compress jpg": tools.compress_image(im, 80, "jpg"), "convert webp": tools.convert_image(im, "webp"),
        "resize": tools._save_image(tools.resize_image(im, width=4), "jpg"),
        "adjust": tools._save_image(tools.adjust_image(im, 1.2), "jpg"),
        "adjust2": tools._save_image(img2.adjust_image_full(im, 120), "jpg"),
        "border": tools._save_image(img2.add_border(im, 2), "jpg"),
        "watermark": tools._save_image(tools.watermark_image(im, "x"), "png"),
        "strip exif": tools._save_image(tools.strip_exif(im), "jpg"),
    }
    lost = [k for k, v in outs.items() if not reopen(v).info.get("icc_profile")]
    assert not lost, f"profile lost by: {lost}"
    # An RGB profile must not be attached to a gray image.
    assert not reopen(tools._save_image(tools.grayscale_image(im), "jpg")).info.get("icc_profile")


@case("image: strip_exif keeps transparency and removes EXIF")
def _():
    for fmt in ("gif", "png"):
        out = reopen(tools._save_image(tools.strip_exif(image("P+t")), fmt))
        eq(out.convert("RGBA").getpixel((0, 0))[3], 0, f"{fmt} alpha")
    photo = Image.new("RGB", (40, 20), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6       # orientation: rotate 90
    exif[0x010F] = "Cam"   # make
    buf = B()
    photo.save(buf, "JPEG", exif=exif)
    upright = tools.open_image(B(buf.getvalue()))
    eq(upright.size, (20, 40), "EXIF rotation applied")
    eq(dict(reopen(tools._save_image(tools.strip_exif(upright), "jpg")).getexif()), {}, "exif")


@case("image: grayscale keeps transparency")
def _():
    out = tools.grayscale_image(Image.new("RGBA", (4, 4), (255, 0, 0, 0)))
    eq(out.mode, "LA")
    eq(out.getpixel((0, 0))[1], 0, "alpha")
    eq(tools.grayscale_image(Image.new("RGB", (4, 4))).mode, "L")
    for fmt in ("png", "webp", "gif"):   # the CLI saves in the input's own format
        eq(reopen(tools._save_image(out, fmt)).convert("RGBA").getpixel((0, 0))[3], 0, fmt)
    assert min(reopen(tools._save_image(out, "jpg")).getpixel((0, 0))) > 240


@case("image: resize rejects sizes that are zero, negative or enormous")
def _():
    im = Image.new("RGB", (10, 10))
    raises(ValueError, lambda: tools.resize_image(im, "percentage", percentage=-10), "percentage")
    raises(ValueError, lambda: tools.resize_image(im, "percentage", percentage=0), "percentage")
    raises(ValueError, lambda: tools.resize_image(im, "percentage", percentage=400000), "too large")
    raises(ValueError, lambda: tools.resize_image(im, width=-5))
    eq(tools.resize_image(im, width=20).size, (20, 20))
    eq(tools.resize_image(Image.new("RGB", (1, 1)), "percentage", percentage=50).size, (1, 1))


@case("image: HEIC conversion keeps the colour profile and flattens on white")
def _():
    if not img2.HEIF_AVAILABLE:
        raise Skip("pillow-heif not installed")
    buf = B()
    try:
        Image.new("RGB", (64, 64), (200, 10, 10)).save(buf, "HEIF", icc_profile=srgb_profile())
    except Exception as e:
        raise Skip(f"no HEIF encoder: {e}")
    for fmt in ("jpg", "png"):
        assert reopen(img2.heic_to_image(B(buf.getvalue()), fmt)).info.get("icc_profile"), fmt
    buf = B()
    Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(buf, "HEIF")
    assert min(reopen(img2.heic_to_image(B(buf.getvalue()), "jpg")).getpixel((5, 5))) > 240


@case("image: a file that is not an image gives a plain error, with no object addresses in it")
def _():
    import tempfile as tf
    upload = tf.SpooledTemporaryFile()   # what an upload stream looks like
    upload.write(b"definitely not an image")
    upload.seek(0)
    logo = B()
    Image.new("RGB", (4, 4)).save(logo, "PNG")
    for name, fn in (("open_image", lambda: tools.open_image(upload)),
                     ("empty file", lambda: tools.open_image(B(b""))),
                     ("read_exif", lambda: img2.read_exif(B(b"nope"))),
                     ("heic", lambda: img2.heic_to_image(B(b"nope"))),
                     ("stamp", lambda: pdf2.stamp_pdf(B(b""), B(b"nope"))),
                     ("ocr", lambda: _ocr_with_fake_tesseract(b"nope"))):
        if name == "heic" and not img2.HEIF_AVAILABLE:
            continue
        e = raises(ValueError, fn, "not an image")
        assert "0x" not in str(e) and "<" not in str(e), f"{name}: {e}"
    eq(tools.open_image(B(logo.getvalue())).size, (4, 4))


def _ocr_with_fake_tesseract(data: bytes):
    saved = pdf2.tesseract_path
    pdf2.tesseract_path = lambda: "tesseract"
    try:
        return pdf2.ocr_document(B(data), "scan.png")
    except ImportError:
        raise ValueError("not an image (pytesseract missing, nothing to test)")
    finally:
        pdf2.tesseract_path = saved


# ── PDF fixtures ──

def make_pdf(n=3, size=(200, 300), rotate=0, cropbox=None, mediabox=None, text=True) -> bytes:
    """n pages, each with "Page N" near its top-left corner."""
    w = PdfWriter()
    for i in range(n):
        page = w.add_blank_page(width=size[0], height=size[1])
        if mediabox:
            page.mediabox = RectangleObject(mediabox)
        if text:
            st = DecodedStreamObject()
            st.set_data(f"BT /F1 24 Tf 20 {size[1] - 40} Td (Page {i + 1}) Tj ET".encode())
            page[NameObject("/Contents")] = w._add_object(st)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        if cropbox:
            page.cropbox = RectangleObject(cropbox)
        if rotate:
            page[NameObject("/Rotate")] = NumberObject(rotate)
    buf = B()
    w.write(buf)
    return buf.getvalue()


def _block_appearance(w, width, height):
    ap = DecodedStreamObject()
    ap.set_data(f"0 g 0 0 {width} {height} re f".encode())
    ap.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
               NameObject("/BBox"): ArrayObject([FloatObject(v) for v in (0, 0, width, height)])})
    return w._add_object(ap)


def with_annotation(pdf: bytes, rect=(20, 20, 60, 50)) -> bytes:
    """Add a black square annotation (pdfium draws it) to page 1."""
    w = PdfWriter(clone_from=PdfReader(B(pdf)))
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Square"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]), NameObject("/F"): NumberObject(4),
        NameObject("/AP"): DictionaryObject(
            {NameObject("/N"): _block_appearance(w, rect[2] - rect[0], rect[3] - rect[1])}),
    })
    w.pages[0][NameObject("/Annots")] = ArrayObject([w._add_object(annot)])
    buf = B()
    w.write(buf)
    return buf.getvalue()


def book_pdf() -> bytes:
    """Four pages with a bookmark each, a title, and a filled form field on page 1."""
    w = PdfWriter(clone_from=PdfReader(B(make_pdf(4))))
    page = w.pages[0]
    field = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject("name"),
        NameObject("/V"): TextStringObject("HELLO"),
        NameObject("/Rect"): ArrayObject([FloatObject(v) for v in (50, 100, 150, 140)]),
        NameObject("/F"): NumberObject(4), NameObject("/DA"): TextStringObject("/Helv 12 Tf 0 g"),
        NameObject("/AP"): DictionaryObject({NameObject("/N"): _block_appearance(w, 100, 40)}),
        NameObject("/P"): page.indirect_reference,
    })
    ref = w._add_object(field)
    page[NameObject("/Annots")] = ArrayObject([ref])
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([ref]), NameObject("/DA"): TextStringObject("/Helv 12 Tf 0 g")})
    for i in range(4):
        w.add_outline_item(title=f"Chapter {i + 1}", page_number=i)
    w.add_metadata({"/Title": "Book", "/Author": "Me"})
    buf = B()
    w.write(buf)
    return buf.getvalue()


def encrypted(pdf: bytes, user="", owner="owner") -> bytes:
    w = PdfWriter(clone_from=PdfReader(B(pdf)))
    w.encrypt(user_password=user, owner_password=owner)
    buf = B()
    w.write(buf)
    return buf.getvalue()


def render(pdf: bytes, page=0) -> Image.Image:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise Skip("pypdfium2 not installed")
    doc = pdfium.PdfDocument(pdf)
    doc.init_forms()
    try:
        return doc[page].render(scale=1).to_pil().convert("RGB")
    finally:
        doc.close()


def ink(img: Image.Image, box=None):
    """Where the dark pixels are, as fractions of the image: (x0, y0, x1, y1).
    box limits the search to part of the image (also in fractions)."""
    w, h = img.size
    if box:
        img = img.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    bbox = img.convert("L").point(lambda v: 255 if v < 200 else 0).getbbox()
    if not bbox:
        return None
    ox, oy = (box[0] * w, box[1] * h) if box else (0, 0)
    return ((bbox[0] + ox) / w, (bbox[1] + oy) / h, (bbox[2] + ox) / w, (bbox[3] + oy) / h)


def corner(bbox) -> str:
    assert bbox, "nothing was drawn"
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return ("top" if cy < 0.5 else "bottom") + "-" + ("left" if cx < 0.5 else "right")


def describe(pdf: bytes) -> dict:
    r = PdfReader(B(pdf))
    return {"pages": [p.extract_text() for p in r.pages],
            "fields": sorted((r.get_fields() or {}).keys()),
            "bookmarks": [(o.title, r.get_destination_page_number(o)) for o in r.outline],
            "title": r.metadata.title if r.metadata else None}


def black_png(size=(60, 30)) -> bytes:
    buf = B()
    Image.new("RGB", size, (0, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


PAGE_SHAPES = {
    "plain": dict(),
    "rotated 90": dict(rotate=90),
    "rotated 180": dict(rotate=180),
    "rotated 270": dict(rotate=270),
    "cropped": dict(cropbox=(40, 60, 190, 280)),
    "cropped + rotated": dict(cropbox=(40, 60, 190, 280), rotate=90),
    "box off origin + rotated": dict(mediabox=(100, 100, 300, 400), rotate=270),
}


# ── PDF ──

@case("pdf: page ranges: typos are errors, never a silent no-op")
def _():
    pdf = make_pdf(3)
    for bad in ("3-1", "0", "a", "99", "0-2", "1.5", "2-"):
        raises(ValueError, lambda: tools.rotate_pdf(B(pdf), 90, bad), "page range")
        raises(ValueError, lambda: tools.delete_pdf_pages(B(pdf), bad), "page range")
        raises(ValueError, lambda: tools.split_pdf(B(pdf), bad), "page range")
        raises(ValueError, lambda: pdf2.parse_pages(bad, 3), "page range")
    raises(ValueError, lambda: tools.delete_pdf_pages(B(pdf), " "), "no pages")
    raises(ValueError, lambda: tools.delete_pdf_pages(B(pdf), "1-999"), "all pages")
    raises(ValueError, lambda: tools.split_pdf(B(pdf), " "))
    eq([p.rotation for p in PdfReader(B(tools.rotate_pdf(B(pdf), 90, "2"))).pages], [0, 90, 0])
    eq([p.rotation for p in PdfReader(B(tools.rotate_pdf(B(pdf), 90, "all"))).pages], [90, 90, 90])
    eq(describe(tools.delete_pdf_pages(B(pdf), "2-99"))["pages"], ["Page 1"])
    eq([len(PdfReader(B(d)).pages) for _, d in tools.split_pdf(B(pdf), "1-999, 2")], [3, 1])
    eq(len(tools.split_pdf(B(pdf))), 3)
    eq(describe(tools.reorder_pdf(B(pdf), [3, 3, 1]))["pages"], ["Page 3", "Page 3", "Page 1"])
    raises(ValueError, lambda: tools.reorder_pdf(B(pdf), [0]), "out of range")
    raises(ValueError, lambda: tools.reorder_pdf(B(pdf), [4]), "out of range")


@case("pdf: bookmarks, form fields and title survive every whole-document tool")
def _():
    book = book_pdf()
    want = {"fields": ["name"], "title": "Book", "bookmarks": [(f"Chapter {i + 1}", i) for i in range(4)]}
    outs = {
        "compress": tools.compress_pdf(B(book)),
        "encrypt+decrypt": tools.remove_pdf_password(B(tools.add_pdf_password(B(book), "pw")), "pw"),
        "rotate": tools.rotate_pdf(B(book), 90),
        "watermark": tools.watermark_pdf(B(book), "x"),
        "number": tools.number_pdf_pages(B(book)),
        "stamp": pdf2.stamp_pdf(B(book), B(black_png())),
    }
    for name, out in outs.items():
        got = describe(out)
        for key, value in want.items():
            eq(got[key], value, f"{name} {key}")
    got = describe(tools.set_pdf_metadata(B(book), title="New", author=None))
    eq((got["title"], got["bookmarks"], got["fields"]), ("New", want["bookmarks"], ["name"]), "set metadata")
    eq(PdfReader(B(tools.set_pdf_metadata(B(book), title="New", author=None))).metadata.author, "Me")
    got = describe(tools.delete_pdf_pages(B(book), "2"))
    eq(got["bookmarks"], [("Chapter 1", 0), ("Chapter 3", 1), ("Chapter 4", 2)], "delete")
    eq((got["title"], got["fields"]), ("Book", ["name"]), "delete")
    got = describe(tools.reorder_pdf(B(book), [4, 1]))
    eq(got["bookmarks"], [("Chapter 1", 1), ("Chapter 4", 0)], "reorder")
    got = describe(tools.merge_pdfs([B(book), B(make_pdf(2))]))
    eq((len(got["pages"]), got["fields"], got["bookmarks"]), (6, ["name"], want["bookmarks"]), "merge")
    eq(len(PdfReader(B(tools.merge_pdfs([B(book), B(book)]))).pages), 8, "same file twice")
    # If pypdf chokes on a document's bookmarks part-way, the pages are still copied, once.
    real = PdfWriter.append

    def flaky(self, *args, **kwargs):
        real(self, *args, **kwargs)
        raise RuntimeError("damaged outline")
    PdfWriter.append = flaky
    try:
        eq(describe(tools.merge_pdfs([B(book), B(make_pdf(2))]))["pages"],
           ["Page 1", "Page 2", "Page 3", "Page 4", "Page 1", "Page 2"], "fallback")
        eq(describe(tools.delete_pdf_pages(B(book), "2"))["pages"], ["Page 1", "Page 3", "Page 4"], "fallback")
    finally:
        PdfWriter.append = real


@case("pdf: encrypted and empty documents")
def _():
    pdf = make_pdf(3)
    locked = encrypted(pdf, user="", owner="o")     # opens without a password
    eq(tools.pdf_page_count(B(locked)), 3)
    eq(len(PdfReader(B(tools.watermark_pdf(B(locked), "x"))).pages), 3)
    assert not PdfReader(B(tools.remove_pdf_password(B(locked), ""))).is_encrypted
    secret = encrypted(pdf, user="u", owner="o")
    raises(ValueError, lambda: tools.remove_pdf_password(B(secret), "bad"), "password")
    assert not PdfReader(B(tools.remove_pdf_password(B(secret), "u"))).is_encrypted
    raises(Exception, lambda: tools.merge_pdfs([B(secret)]), "decrypt")
    out = PdfReader(B(tools.add_pdf_password(B(pdf), "pw")))
    assert out.is_encrypted and not out.decrypt("") and out.decrypt("pw")
    empty = make_pdf(0)
    eq(tools.split_pdf(B(empty)), [])
    eq(tools.pdf_to_text(B(empty)), "")
    eq(tools.get_pdf_metadata(B(empty))["pages"], 0)
    raises(ValueError, lambda: pdf2.flatten_pdf(B(empty)), "no pages")
    raises(ValueError, lambda: pdf2.pdf_to_images(B(empty)), "no pages")
    raises(Exception, lambda: tools.pdf_page_count(B(b"not a pdf")))
    eq(tools.get_pdf_metadata(B(pdf))["title"], "")


@case("pdf: watermark, page number and stamp land in the right corner of rotated/cropped pages")
def _():
    for shape, kw in PAGE_SHAPES.items():
        pdf = make_pdf(1, text=False, **kw)
        for position in ("top-left", "bottom-right"):
            out = tools.watermark_pdf(B(pdf), "WM", 20, 1.0, position)
            eq(corner(ink(render(out))), position, f"watermark, {shape}")
            out = pdf2.stamp_pdf(B(pdf), B(black_png()), position, 25, 100)
            eq(corner(ink(render(out))), position, f"stamp, {shape}")
            eq(render(out).size, render(pdf).size, f"stamp keeps the page shape, {shape}")
        out = tools.number_pdf_pages(B(pdf), 1, "bottom-left", 20)
        eq(corner(ink(render(out))), "bottom-left", f"page number, {shape}")
        eq(PdfReader(B(out)).pages[0].rotation, kw.get("rotate", 0), f"rotation kept, {shape}")


@case("pdf: numbering a rotated page leaves its links and form fields where they were")
def _():
    pdf = with_annotation(make_pdf(1, text=False, rotate=90))
    before = ink(render(pdf))
    after = ink(render(tools.number_pdf_pages(B(pdf), 1, "bottom-right", 6)), box=(0, 0, 0.6, 0.6))
    assert after, "annotation moved out of its corner"
    for a, b in zip(before, after):
        near(b, a, 0.02, "annotation position")


@case("pdf: text stamps reject characters the built-in font cannot draw")
def _():
    pdf = make_pdf(1)
    raises(ValueError, lambda: tools.watermark_pdf(B(pdf), "שלום"), "characters")
    assert "(a\\(b\\)\\\\c)" in tools._text_overlay_pdf(10, 10, [(0, 0, 8.0, "a(b)\\c", 0, 1)]).decode("latin-1")
    assert "café" in PdfReader(B(tools.watermark_pdf(B(pdf), "café"))).pages[0].extract_text()


@case("pdf: flatten and PDF-to-images keep filled-in form values")
def _():
    book = book_pdf()
    field = (0.25, 0.5, 0.75, 0.7)  # where the filled field sits on the page
    assert ink(render(book), box=field), "fixture: the field should render"
    flat = pdf2.flatten_pdf(B(book))
    assert ink(render(flat), box=field), "flatten dropped the field's value"
    eq(PdfReader(B(flat)).get_fields(), None, "flatten leaves no live fields")
    eq(len(PdfReader(B(flat)).pages), 4)
    page1 = reopen(pdf2.pdf_to_images(B(book), "png", 72, "1")[0][1])
    assert ink(page1, box=field), "pdf_to_images dropped the field's value"


@case("pdf: resize and flatten work on the visible (cropped) page")
def _():
    # 200x300 page cropped to its top-left 120x100, which holds "Page 1".
    pdf = make_pdf(1, cropbox=(0, 200, 120, 300))
    src = ink(render(pdf))
    for fit in ("fit", "fill"):
        out = render(pdf2.resize_pdf_pages(B(pdf), "a4", fit))
        assert out.width > out.height, f"{fit}: a landscape crop belongs on a landscape sheet"
        got = ink(out)
        near(got[0], src[0], 0.08, f"{fit} left")
        near(got[2], src[2], 0.08, f"{fit} right")
    turned = make_pdf(1, cropbox=(0, 200, 120, 300), rotate=90)
    out = render(pdf2.resize_pdf_pages(B(turned), "letter"))
    assert out.height > out.width
    for a, b in zip(ink(render(turned)), ink(out)):
        near(b, a, 0.08, "rotated crop")
    for doc in (pdf, turned):
        flat = render(pdf2.flatten_pdf(B(doc), 72))
        eq(flat.size, render(doc).size, "flatten size")
        for a, b in zip(ink(render(doc)), ink(flat)):
            near(b, a, 0.03, "flatten position")
    raises(ValueError, lambda: pdf2.resize_pdf_pages(B(pdf), "a9"))


@case("pdf: an EXIF-rotated photo is stamped upright")
def _():
    photo = Image.new("RGB", (60, 20), (0, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = B()
    photo.save(buf, "JPEG", exif=exif)
    box = ink(render(pdf2.stamp_pdf(B(make_pdf(1, text=False)), B(buf.getvalue()), "center", 20, 100)))
    assert (box[3] - box[1]) * 300 > (box[2] - box[0]) * 200, "stamp is sideways"
    raises(ValueError, lambda: pdf2.stamp_pdf(B(make_pdf(1)), B(black_png()), "center", 0, 100), "scale")
    raises(ValueError, lambda: pdf2.stamp_pdf(B(make_pdf(1)), B(black_png()), "middle"))
    raises(ValueError, lambda: pdf2.stamp_pdf(B(make_pdf(1)), B(black_png()), pages_str="7"), "page range")


@case("pdf: a giant page is rendered at a lower resolution instead of exhausting memory")
def _():
    render(make_pdf(1))  # skip if pdfium is missing
    name, data = pdf2.pdf_to_images(B(make_pdf(1, size=(14400, 14400), text=False)), "jpg", 150)[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        w, h = Image.open(B(data)).size
    assert w * h <= pdf2.MAX_RENDER_PIXELS * 1.01, (w, h)
    eq(reopen(pdf2.pdf_to_images(B(make_pdf(1)), "png", 72)[0][1]).size, (200, 300))
    eq([n for n, _ in pdf2.pdf_to_images(B(make_pdf(3)), "jpg", 72, "3,1")], ["page_1.jpg", "page_3.jpg"])
    raises(ValueError, lambda: pdf2.pdf_to_images(B(make_pdf(1)), "png", 100), "dpi")


@case("pdf: OCR gets an upright image on a white background")
def _():
    try:
        import pytesseract
    except ImportError:
        raise Skip("pytesseract not installed")
    seen = []
    saved = pdf2.tesseract_path, pytesseract.image_to_string
    pdf2.tesseract_path = lambda: "tesseract"
    pytesseract.image_to_string = lambda img, lang=None: seen.append(img) or " text "
    try:
        buf = B()
        Image.new("RGBA", (40, 20), (0, 0, 0, 0)).save(buf, "PNG")
        eq(pdf2.ocr_document(B(buf.getvalue()), "a.png"), ("text", 1))
        assert min(seen[-1].getpixel((1, 1))) > 240, "transparent areas should be white"
        exif = Image.Exif()
        exif[0x0112] = 6
        buf = B()
        Image.new("RGB", (60, 20)).save(buf, "JPEG", exif=exif)
        pdf2.ocr_document(B(buf.getvalue()), "a.jpg")
        eq(seen[-1].size, (20, 60), "EXIF rotation")
        try:
            eq(pdf2.ocr_document(B(make_pdf(2)), "a.pdf"), ("--- Page 1 ---\ntext\n\n--- Page 2 ---\ntext", 2))
        except ImportError:
            pass
        raises(ValueError, lambda: pdf2.ocr_document(B(buf.getvalue()), "a.jpg", "eng; rm"), "language")
    finally:
        pdf2.tesseract_path, pytesseract.image_to_string = saved


@case("pdf: images to PDF and back")
def _():
    pdf = tools.images_to_pdf([Image.new("RGB", (30, 30), (255, 0, 0)), Image.new("RGBA", (30, 30), (0, 255, 0, 0)),
                               image("P+t"), image("1"), image("CMYK"), image("I;16")])
    eq(len(PdfReader(B(pdf)).pages), 6)
    assert min(render(pdf, 1).getpixel((5, 5))) > 240, "transparent image should sit on white"
    found = tools.extract_images_from_pdf(B(pdf))
    eq(len(found), 6)
    for name, data in found:
        assert name.count(".") == 1 and name.endswith(".jpg"), name
        reopen(data)


# ── Data conversion ──

@case("convert: CSV with a byte-order mark, quotes, embedded newlines and ragged rows")
def _():
    eq(json.loads(tools.csv_to_json_str("\ufeffname,age\nA,1\n")), [{"name": "A", "age": "1"}])
    eq(json.loads(tools.csv_to_json_str('a,b\n"x ""q"" y","l1\nl2"\n')), [{"a": 'x "q" y', "b": "l1\nl2"}])
    eq(json.loads(tools.csv_to_json_str("a,b\n1\n"))[0], {"a": "1", "b": None})
    eq(tools.csv_to_json_str(""), "[]")
    eq(tools.tsv_to_csv_str(tools.csv_to_tsv_str('a,"b\tc"\n1,"x,y"\n')), 'a,b\tc\r\n1,"x,y"\r\n')


@case("convert: JSON to CSV writes nested values as JSON and refuses non-tables")
def _():
    out = tools.json_to_csv_str('[{"a": {"x": 1}, "b": [1, 2], "c": true, "d": null}, {"e": "z"}]')
    eq(out, 'a,b,c,d,e\r\n"{""x"": 1}","[1, 2]",true,,\r\n,,,,z\r\n')
    raises(ValueError, lambda: tools.json_to_csv_str('{"a": 1}'), "array of objects")
    raises(ValueError, lambda: tools.json_to_csv_str('[1, 2, "x"]'), "array of objects")
    raises(ValueError, lambda: tools.json_to_csv_str(""))
    eq(tools.json_to_csv_str('\ufeff[{"a": 1}]'), "a\r\n1\r\n")


@case("convert: YAML dates, sets and binary; key order; alias bombs")
def _():
    if not tools._YAML_AVAILABLE:
        raise Skip("PyYAML not installed")
    got = json.loads(tools.yaml_to_json_str("d: 2024-01-01\nt: 2024-01-01T10:00:00Z\ns: !!set {a, b}\nb: !!binary aGVsbG8=\n"))
    eq(got, {"d": "2024-01-01", "t": "2024-01-01T10:00:00+00:00", "s": ["a", "b"], "b": "aGVsbG8="})
    eq(json.loads(tools.yaml_to_json_str("a: &a [1, 2]\nb: *a\n")), {"a": [1, 2], "b": [1, 2]})
    eq(tools.yaml_to_json_str(""), "null")
    raises(Exception, lambda: tools.yaml_to_json_str('a: !!python/object/apply:os.system ["true"]'))
    eq(tools.json_to_yaml_str('{"b": 1, "a": {"z": 1, "y": 2}}'), "b: 1\na:\n  z: 1\n  y: 2\n")
    levels = "abcdefghij"
    bomb = "a: &a [x,x,x,x,x,x,x,x,x]\n" + "".join(
        f"{levels[i + 1]}: &{levels[i + 1]} [{','.join(['*' + levels[i]] * 9)}]\n" for i in range(9))
    raises(ValueError, lambda: tools.yaml_to_json_str(bomb), "too many")


@case("convert: XML entities, and entity bombs are refused")
def _():
    eq(json.loads(tools.xml_to_json_str('<r a="1"><x>1</x><x>2</x><y>t &amp; u</y></r>')),
       {"r": {"@a": "1", "x": [{"_text": "1"}, {"_text": "2"}], "y": {"_text": "t & u"}}})
    laughs = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a0 "lol">'
              + "".join(f'<!ENTITY a{i} "{("&a%d;" % (i - 1)) * 10}">' for i in range(1, 10)) + "]><l>&a9;</l>")
    raises(Exception, lambda: tools.xml_to_json_str(laughs))
    raises(Exception, lambda: tools.xml_to_json_str(
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>'))
    raises(Exception, lambda: tools.xml_to_json_str(""))


@case("convert: JSON to XML stays well-formed for control characters and non-Latin keys")
def _():
    import xml.etree.ElementTree as ET
    root = ET.fromstring(conv2.json_to_xml_str('{"a": "x\\u0001y", "שלום": "1", "名前": "2", "1st": 3, "a b": [1, 2], "<": "<&>"}'))
    eq(root.find("a").text, "xy")
    eq([el.tag for el in root], ["a", "שלום", "名前", "_1st", "a_b", "a_b", "_"])
    eq(root.find("_").text, "<&>")
    eq(ET.fromstring(conv2.json_to_xml_str("5")).text, "5")
    eq(ET.fromstring(conv2.json_to_xml_str("{}", root="my root!")).tag, "my_root_")


@case("convert: JSON helpers accept a byte-order mark and survive deep nesting")
def _():
    eq(tools.json_minify('\ufeff [1, 2 , {"a" : "b c"}] '), '[1,2,{"a":"b c"}]')
    eq(tools.json_validate('\ufeff{"a": 1}'), {"valid": True, "type": "dict", "keys": 1})
    eq(tools.json_validate('{"a":}')["valid"], False)
    assert "valid" in tools.json_validate("[" * 100000 + "]" * 100000)  # no RecursionError
    eq(json.loads(tools.json_format('{"n": 12345678901234567890123, "u": "\\u00e9"}')), {"n": 12345678901234567890123, "u": "é"})


@case("convert: TOML both ways")
def _():
    got = json.loads(conv2.toml_to_json_str('a = 1\nd = 2024-01-01T10:00:00Z\n[x.y]\nz = [1, "a", {k = 1}]\n[[arr]]\nq = 1\n'))
    eq(got, {"a": 1, "d": "2024-01-01T10:00:00+00:00", "x": {"y": {"z": [1, "a", {"k": 1}]}}, "arr": [{"q": 1}]})
    raises(ValueError, lambda: conv2.toml_to_json_str("a = "), "invalid toml")
    if conv2._TOMLW_AVAILABLE:
        text = conv2.json_to_toml_str('{"a": {"b": [{"c": 1}]}, "s": "multi\\nline"}')
        eq(json.loads(conv2.toml_to_json_str(text)), {"a": {"b": [{"c": 1}]}, "s": "multi\nline"})
        raises(ValueError, lambda: conv2.json_to_toml_str('{"a": [1, {"b": null}]}'), "$.a[1].b")
        raises(ValueError, lambda: conv2.json_to_toml_str("[1]"), "top-level")


def _sheet_cells(data: bytes) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(B(data))
    return {ws.title: [[(c.value, c.data_type) for c in row] for row in ws.iter_rows()] for ws in wb}


@case("convert: CSV to Excel keeps phone numbers, long IDs and '=' text as text")
def _():
    if not conv2._OPENPYXL_AVAILABLE:
        raise Skip("openpyxl not installed")
    import openpyxl
    out = conv2.csv_to_xlsx([("d.csv", "\ufeffid;phone;zip;n;note;big\n1;+14155552671;007;1.50;=== Totals ===;1234567890123456789\n")])
    eq(_sheet_cells(out)["d"][1], [(1, "n"), ("+14155552671", "s"), ("007", "s"), (1.5, "n"),
                                  ("=== Totals ===", "s"), ("1234567890123456789", "s")])
    eq(_sheet_cells(conv2.csv_to_xlsx([("d.csv", '=cmd|"/c calc"!A1\n')], header=False))["d"][0][0][1], "s")
    eq(_sheet_cells(conv2.csv_to_xlsx([("d.csv", "a\nx\x0by\x1b[0m\n")]))["d"][1][0][0], "xy[0m")
    eq(_sheet_cells(conv2.csv_to_xlsx([("d.csv", 'a,b\n"x ""q"" y","l1\nl2"\n')]))["d"][1], [('x "q" y', "s"), ("l1\nl2", "s")])
    wb = openpyxl.load_workbook(B(conv2.csv_to_xlsx([("a.csv", "name,n\nlonger value,1\n"), ("a.csv", ""), ("[x]:*.csv", "z")])))
    eq(wb.sheetnames, ["a", "a_2", "_x___"])
    ws = wb["a"]
    eq((ws.freeze_panes, ws["A1"].font.bold, ws["A2"].font.bold, ws.column_dimensions["A"].width), ("A2", True, False, 14))
    eq(conv2.xlsx_to_csv(conv2.csv_to_xlsx([("d.csv", "a,b\n1,x\n")]))[0], ("d", "a,b\n1,x\n"))


@case("convert: Excel to CSV handles dates, chart sheets and missing sheets")
def _():
    if not conv2._OPENPYXL_AVAILABLE:
        raise Skip("openpyxl not installed")
    import datetime
    import openpyxl
    from openpyxl.chart import BarChart, Reference
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S1"
    ws.append(["a", "b", "c"])
    ws.append([1.0, True, datetime.datetime(2024, 1, 1)])
    ws.append(["x,y", 'q"q', datetime.datetime(2024, 1, 1, 9, 30)])
    ws.append([None, None, None])
    chart = BarChart()
    chart.add_data(Reference(ws, min_col=1, min_row=1, max_row=2))
    wb.create_chartsheet("Chart").add_chart(chart)
    buf = B()
    wb.save(buf)
    want = 'a,b,c\n1,TRUE,2024-01-01\n"x,y","q""q",2024-01-01T09:30:00\n'
    eq(conv2.xlsx_to_csv(buf.getvalue()), [("S1", want)])
    eq(conv2.xlsx_to_csv(buf.getvalue(), "S1"), [("S1", want)])
    raises(ValueError, lambda: conv2.xlsx_to_csv(buf.getvalue(), "Chart"), "not found")
    raises(ValueError, lambda: conv2.xlsx_to_csv(b"PK\x03\x04junk"), "could not open")


@case("convert: SQL minify leaves quoted strings and names alone")
def _():
    if not conv2._SQLPARSE_AVAILABLE:
        raise Skip("sqlparse not installed")
    out = conv2.sql_format("select a , b from t where x = 'a  ,  ( b )' and y in ( 1 , 2 ) -- c\n; select \"col  name\" , 'it''s' from t", minify=True)
    eq(out, "SELECT a, b FROM t WHERE x = 'a  ,  ( b )' AND y IN(1, 2); SELECT \"col  name\", 'it''s' FROM t")
    assert "'a  ,  b'" in conv2.sql_format("select a from t where x='a  ,  b'")


@case("convert: HTML to Markdown and Markdown to HTML")
def _():
    if conv2._HTML2TEXT_AVAILABLE:
        md = conv2.html_to_md_str("<h1>T</h1><p>a <b>b</b></p><script>alert(1)</script>")
        eq(md, "# T\n\na **b**\n")
        eq(conv2.html_to_md_str(""), "\n")
    html = tools.md_preview("|a|b|\n|-|-|\n|1|2|\n\n```py\nx<y\n```")
    assert "<table>" in html and "x&lt;y" in html
    assert "<title>" in tools.md_to_html("# h")


@case("text: diff, stats, base64, hashes, passwords")
def _():
    eq(tools.text_diff("a\nb", "a\nc"), "--- Original\n+++ Modified\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n")
    eq(tools.text_diff("a\n", "a\n"), "")
    stats = tools.text_stats("Hello world. How are you?\r\n\r\nNew para")
    eq((stats["paragraphs"], stats["lines"], stats["words"]), (2, 3, 7))
    eq(tools.text_stats("")["words"], 0)
    for text in ("aGVsbG8gd29ybGQ=", "aGVsbG8gd29ybGQ", "aGVsbG8g\nd29ybGQ=", "data:text/plain;base64,aGVsbG8gd29ybGQ="):
        eq(tools.base64_decode(text), b"hello world", text)
    eq(tools.base64_decode("-_-_"), b"\xfb\xff\xbf", "URL-safe alphabet")
    raises(ValueError, lambda: tools.base64_decode("!!!!"))
    eq(tools.base64_decode(tools.base64_encode(bytes(range(256)))), bytes(range(256)))
    eq(tools.generate_hash(b"abc", "all")["sha1"], "a9993e364706816aba3e25717850c26c9cd0d89d")
    eq(conv2.checksum(B(b"abc")), {**tools.generate_hash(b"abc", "all"), "size": 3})
    raises(ValueError, lambda: tools.generate_hash(b"", "crc32"))
    eq([len(p) for p in tools.generate_password(12, count=3)], [12, 12, 12])
    eq(len(set(tools.generate_uuid(4, 5))), 5)
    assert reopen(tools.generate_qr("hello")).size[0] > 20
    raises(ValueError, lambda: tools.generate_qr("x" * 5000))


@case("transcript: timestamps round to the millisecond and cues stay intact")
def _():
    eq([tools._srt_ts(v) for v in (0, 1.001, 2.3, 3599.9996, -1.5)],
       ["00:00:00,000", "00:00:01,001", "00:00:02,300", "01:00:00,000", "00:00:00,000"])
    eq(tools._fmt_ts(360000.5), "100:00:00.500")
    segs = [{"start": 0, "end": 2.3, "text": "hi\n\nthere", "speaker": "A"}, {"text": None}, "junk",
            {"start": "x", "end": None, "text": 5}]
    eq(tools.export_transcript_srt(segs).split("\n")[:4], ["1", "00:00:00,000 --> 00:00:02,300", "[A] hi", "there"])
    eq(tools.export_transcript_vtt(segs).split("\n")[:4], ["WEBVTT", "", "00:00:00.000 --> 00:00:02.300", "<v A>hi"])
    eq(tools.export_transcript_txt(segs), "[A] hi\n\nthere\n\n5")
    eq(tools.export_transcript_csv(segs).splitlines()[0], "start,end,speaker,text")
    merged = tools.merge_transcription_and_diarization(
        [{"start": 0, "end": 2, "text": "a"}, {"start": 5, "end": 6, "text": "b"}],
        [{"start": 0, "end": 1.5, "speaker": "SPEAKER_01"}])
    eq([s["speaker"] for s in merged], ["Speaker 2", "Speaker 1"])


# ── Archives and files ──

def make_zip(entries) -> bytes:
    buf = B()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # "Duplicate name", which is the point
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in entries:
                zf.writestr(name, data)
    return buf.getvalue()


HOSTILE = [("../../evil.txt", b"1"), ("/abs/path.txt", b"2"), ("C:\\win\\x.txt", b"3"), ("ok/dir/f.txt", b"5"),
           ("dir/", b""), ("dup.txt", b"first"), ("dup.txt", b"second"), ("noext", b"a"), ("noext", b"b"),
           ("noext", b"c"), ("d.v2/readme", b"x"), ("d.v2/readme", b"y")]


@case("archive: unzip never yields a path that leaves the folder, and keeps both of two same-named files")
def _():
    for label, got in (("extract_zip", tools.extract_zip(make_zip(HOSTILE))),
                       ("extract_archive", conv2.extract_archive(make_zip(HOSTILE), "e.zip"))):
        names = [n for n, _ in got]
        eq(len(names), len(set(names)), f"{label} unique names")
        for n in names:
            assert not n.startswith("/") and ".." not in n.split("/") and ":" not in n and "\\" not in n, f"{label}: {n}"
        files = dict(got)
        eq((files["dup.txt"], files["dup_2.txt"]), (b"first", b"second"), label)
        eq((files["noext"], files["noext_2"], files["noext_3"]), (b"a", b"b", b"c"), label)
        eq((files["d.v2/readme"], files["d.v2/readme_2"]), (b"x", b"y"), label)
        eq(files["ok/dir/f.txt"], b"5", label)
    eq([e["name"] for e in conv2.archive_list(make_zip(HOSTILE), "e.zip")][0], "ok/dir/f.txt")


@case("archive: create_zip renames duplicates and cleans entry names")
def _():
    out = tools.create_zip([("a.txt", b"1"), ("a.txt", b"2"), ("d.v2/readme", b"1"), ("d.v2/readme", b"2"),
                            ("x", b""), ("x", b""), ("../up.txt", b""), ("/abs.txt", b""), ("", b"")])
    eq(zipfile.ZipFile(B(out)).namelist(),
       ["a.txt", "a_2.txt", "d.v2/readme", "d.v2/readme_2", "x", "x_2", "up.txt", "abs.txt", "file"])
    eq(tools.extract_zip(tools.create_zip([("a.txt", b"1"), ("a.txt", b"2")])), [("a.txt", b"1"), ("a_2.txt", b"2")])
    big = bytes(range(256)) * (9 * 4096)   # 9 MB: takes the chunked path for large files
    eq(tools.extract_zip(tools.create_zip([("big.bin", big), ("small.txt", b"s")])), [("big.bin", big), ("small.txt", b"s")])


@case("archive: zip bombs are refused from the sizes the archive declares, before unpacking")
def _():
    bomb = make_zip([(f"z{i}", b"\0" * (4 * 1024 * 1024)) for i in range(3)])
    saved = conv2.ARCHIVE_CAP, tools.MAX_EXTRACTED_BYTES
    conv2.ARCHIVE_CAP = tools.MAX_EXTRACTED_BYTES = 6 * 1024 * 1024
    real_read = zipfile.ZipFile.read
    reads = []
    zipfile.ZipFile.read = lambda self, *a, **k: reads.append(1) or real_read(self, *a, **k)
    try:
        raises(ValueError, lambda: conv2.extract_archive(bomb, "b.zip"), "limit")
        raises(ValueError, lambda: tools.extract_zip(bomb), "too large")
        eq(reads, [], "entries unpacked before the size check")
    finally:
        zipfile.ZipFile.read = real_read
        conv2.ARCHIVE_CAP, tools.MAX_EXTRACTED_BYTES = saved


@case("archive: tar links, devices and unsafe paths are skipped; damaged files give a plain error")
def _():
    import gzip
    import tarfile
    buf = B()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def add(name, data=b"x", kind=tarfile.REGTYPE, linkname=""):
            info = tarfile.TarInfo(name)
            info.type, info.linkname = kind, linkname
            info.size = len(data) if kind == tarfile.REGTYPE else 0
            tf.addfile(info, B(data) if kind == tarfile.REGTYPE else None)
        add("ok.txt")
        add("../up.txt")
        add("/abs.txt")
        add("sym", kind=tarfile.SYMTYPE, linkname="/etc/passwd")
        add("hard", kind=tarfile.LNKTYPE, linkname="ok.txt")
        add("dev", kind=tarfile.CHRTYPE)
        add("dir/sub/f.txt", b"hello")
        add("ok.txt", b"second")
    tgz = buf.getvalue()
    want = [("ok.txt", b"x"), ("dir/sub/f.txt", b"hello"), ("ok_2.txt", b"second")]
    eq(conv2.extract_archive(tgz, "a.tar.gz"), want)
    eq(conv2.extract_archive(tgz, "no-extension"), want, "detected from the bytes")
    eq([e["name"] for e in conv2.archive_list(tgz, "a.tgz")], ["ok.txt", "dir/sub/f.txt", "ok.txt"])
    for data, name in ((gzip.compress(b"just text"), "notes.txt.gz"), (tgz[:len(tgz) // 2], "a.tgz"), (b"hello", "x.zip"),
                       (b"7z\xbc\xaf\x27\x1cjunkjunkjunk", "x.7z")):
        for fn in (conv2.extract_archive, conv2.archive_list):
            e = raises(ValueError, lambda: fn(data, name), "could not read")
            assert "\n" not in str(e), str(e)
    raises(ValueError, lambda: conv2.extract_archive(b"hello", "x.bin"), "unsupported")
    raises(ValueError, lambda: conv2.extract_archive(make_zip([]), "x.zip"), "empty")
    eq([conv2.archive_base_name(n) for n in ("a.tar.gz", "b.ZIP", ".zip", "x", "a.b.7z")], ["a", "b", "archive", "x", "a.b"])


@case("archive: 7z extraction, password-protected archives")
def _():
    if not conv2._PY7ZR_AVAILABLE:
        raise Skip("py7zr not installed")
    import py7zr
    work = Path(tempfile.mkdtemp(prefix="sdexe-tools-test-"))
    try:
        with py7zr.SevenZipFile(work / "a.7z", "w") as z:
            z.writestr(b"one", "a.txt")
            z.writestr(b"two", "dir/b.txt")
        data = (work / "a.7z").read_bytes()
        eq(conv2.extract_archive(data, "a.7z"), [("a.txt", b"one"), ("dir/b.txt", b"two")])
        eq(conv2.archive_list(data, "a.7z"), [{"name": "a.txt", "size": 3}, {"name": "dir/b.txt", "size": 3}])
        with py7zr.SevenZipFile(work / "e.7z", "w", password="pw") as z:
            z.writestr(b"one", "a.txt")
        e = raises(ValueError, lambda: conv2.extract_archive((work / "e.7z").read_bytes(), "e.7z"), "password")
        assert len(str(e)) < 100, str(e)
        with py7zr.SevenZipFile(work / "h.7z", "w", password="pw", header_encryption=True) as z:
            z.writestr(b"one", "a.txt")
        for fn in (conv2.extract_archive, conv2.archive_list):   # even the file list is encrypted
            e = raises(ValueError, lambda: fn((work / "h.7z").read_bytes(), "h.7z"), "password")
            assert len(str(e)) < 100, str(e)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    # A ZIP entry with the "encrypted" flag set.
    plain = make_zip([("s.txt", b"secret")])
    locked = bytearray(plain)
    for sig, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        at = locked.index(sig) + offset
        locked[at] |= 1
    raises(ValueError, lambda: tools.extract_zip(bytes(locked)), "password")
    raises(ValueError, lambda: conv2.extract_archive(bytes(locked), "s.zip"), "password")


@case("file: split writes commands that survive awkward names; join sorts by part number")
def _():
    import os
    import shlex
    data = os.urandom(3 * 1024 * 1024 + 5)
    name = "my video's $HOME.mp4"
    parts = conv2.split_file(data, name, 1)
    eq([n for n, _ in parts], [f"{name}.00{i}" for i in (1, 2, 3, 4)] + ["JOIN.txt"])
    line = next(l for l in parts[-1][1].decode().splitlines() if l.strip().startswith("cat "))
    eq(shlex.split(line), ["cat"] + [f"{name}.00{i}" for i in (1, 2, 3, 4)] + [">", name])
    eq(conv2.join_files(list(reversed(parts))), (name, data))
    raises(ValueError, lambda: conv2.join_files([parts[0], parts[2]]), "consecutive")
    raises(ValueError, lambda: conv2.join_files([("a.001", b"1"), ("b.002", b"2")]), "part of")
    raises(ValueError, lambda: conv2.join_files([("JOIN.txt", b"")]), "no part")
    eq(conv2.join_files([(f"a.{i}", bytes([i % 256])) for i in (1001, 999, 1000)])[1], bytes([231, 232, 233]))
    raises(ValueError, lambda: conv2.split_file(b"x", "a", 1), "nothing to split")
    raises(ValueError, lambda: conv2.split_file(data, "a", 0))


@case("file: batch rename")
def _():
    eq(conv2.batch_rename_names(["a.txt", "a.txt", ".bashrc", "noext", "dir/b.JPG"], "{n:03}_{name}.{ext}", case="upper"),
       ["001_A.txt", "002_A.txt", "003_.BASHRC", "004_NOEXT", "005_B.JPG"])
    eq(conv2.batch_rename_names(["a.txt", "b.txt"], "same"), ["same", "same_2"])
    eq(conv2.batch_rename_names(["a.txt"], ".."), ["a.txt"])
    eq(conv2.rename_one("a.txt", 7, "{n:0999999999}"), "0" * 19 + "7")
    eq(conv2.rename_one("a b.txt", 1, "{date}_{name}.{ext}", find=" ", replace="-", date_str="2024-01-01"), "2024-01-01_a-b.txt")


# ── Audio and video ──

AV = {}  # fixture name -> bytes, built once


def ffmpeg_make(args: list, ext: str) -> bytes:
    import subprocess
    work = Path(tempfile.mkdtemp(prefix="sdexe-tools-test-"))
    try:
        out = work / f"out.{ext}"
        r = subprocess.run([tools.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-nostdin", *args, str(out)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise Skip(f"ffmpeg could not build a fixture: {r.stderr.strip()[-120:]}")
        return out.read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def av(name: str) -> bytes:
    if not tools.ffmpeg_available():
        raise Skip("ffmpeg not installed")
    if name not in AV:
        tone = lambda secs, rate=44100, freq=440: ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={secs}:sample_rate={rate}"]
        pattern = lambda size, secs=3: ["-f", "lavfi", "-i", f"testsrc=size={size}:rate=25:duration={secs}"]
        h264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        recipes = {
            "tone.wav": (tone(3) + ["-ac", "2"], "wav"),
            "short.wav": (tone(2, 22050, 880), "wav"),
            "tone.flac": (tone(3, 48000), "flac"),
            "tone.m4a": (tone(3) + ["-metadata", "title=Old"], "m4a"),
            "tone.mp3": (tone(3), "mp3"),
            "clip.mp4": (pattern("320x240") + tone(3) + h264 + ["-c:a", "aac", "-shortest"], "mp4"),
            "silent.mp4": (pattern("320x240") + h264, "mp4"),
            # Odd size and 4:4:4 colour, like a screen recording or a GIF.
            "odd.mkv": (pattern("321x241", 2) + tone(2) + ["-c:v", "libx264", "-pix_fmt", "yuv444p", "-c:a", "aac", "-shortest"], "mkv"),
            "odd.gif": (["-f", "lavfi", "-i", "testsrc=size=161x121:rate=10:duration=1"], "gif"),
            "two-tracks.mkv": (pattern("320x240", 2) + tone(2) + tone(2, 44100, 880)
                               + ["-map", "0", "-map", "1", "-map", "2"] + h264 + ["-c:a", "aac"], "mkv"),
            # Brightness climbs with time, so a frame's gray level says when it is from.
            "ramp.mp4": (["-f", "lavfi", "-i", "color=black:s=64x64:r=25:d=10,format=gray,geq=lum='16+T*20'"] + h264 + ["-g", "5"], "mp4"),
        }
        if name == "portrait.mp4":  # stored 320x240 with a "rotate 90" note, as phones do
            work = Path(tempfile.mkdtemp(prefix="sdexe-tools-test-"))
            try:
                (work / "in.mp4").write_bytes(av("clip.mp4"))
                AV[name] = ffmpeg_make(["-display_rotation", "90", "-i", str(work / "in.mp4"), "-c", "copy"], "mp4")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        elif name == "tone.ogg":
            if "libvorbis" not in tools._ffmpeg_encoders(tools.ffmpeg_for_output("ogg")):
                raise Skip("no ffmpeg here can encode Vorbis")
            AV[name] = av2.write_tags(tools.convert_audio(av("tone.wav"), "wav", "ogg"), "ogg",
                                      {"title": "Old", "artist": "Someone"})[0]
        else:
            args, ext = recipes[name]
            AV[name] = ffmpeg_make(args, ext)
    return AV[name]


def info(data: bytes, ext: str) -> dict:
    """{"duration", "size": (w, h) as displayed, "pix_fmt", "vcodec", "acodec", "rate", "channels", "tracks"}"""
    i = av2.media_info(data, ext)
    v, a = i["video"], i["audio"]
    return {"duration": i["duration"], "size": av2._display_size(v) if v else None, "pix_fmt": v and v.get("pix_fmt"),
            "vcodec": v and v["codec"], "acodec": a and a["codec"], "rate": a and a.get("sample_rate"),
            "channels": a and a.get("channels"), "tracks": sum(s["type"] == "audio" for s in i["streams"])}


def zip_names(data: bytes) -> list:
    return zipfile.ZipFile(B(data)).namelist()


@case("audio: trimming rejects impossible ranges instead of returning an empty or untouched file")
def _():
    wav, clip = av("tone.wav"), av("clip.mp4")
    near(info(tools.trim_audio(wav, "wav", "1", "2"), "wav")["duration"], 1.0, 0.1)
    near(info(tools.trim_audio(wav, "wav", "0:01", "0:02.5"), "wav")["duration"], 1.5, 0.1)
    near(info(tools.trim_audio(wav, "wav", "1", "99"), "wav")["duration"], 2.0, 0.1, "end past the end")
    near(info(tools.trim_audio(wav, "wav", "", "2"), "wav")["duration"], 2.0, 0.1, "no start")
    near(info(tools.trim_video(clip, "mp4", "1", "2"), "mp4")["duration"], 1.0, 0.4)
    near(info(tools.trim_video(clip, "mp4", "1", ""), "mp4")["duration"], 2.0, 0.4)
    for trim, data, ext in ((tools.trim_audio, wav, "wav"), (tools.trim_video, clip, "mp4")):
        raises(ValueError, lambda: trim(data, ext, "5", "9"), "past the end")
        raises(ValueError, lambda: trim(data, ext, "2", "1"), "after start")
        raises(ValueError, lambda: trim(data, ext, "abc", ""), "invalid timestamp")
        raises(ValueError, lambda: trim(data, ext, "nan", ""), "invalid timestamp")
    eq([tools.parse_timestamp(v) for v in ("90", "1:30", "1:00:00.5", " 2 ")], [90.0, 90.0, 3600.5, 2.0])
    raises(ValueError, lambda: tools.parse_timestamp("1:2:3:4"))


@case("audio: tools take the first track of a file that has two")
def _():
    two = av("two-tracks.mkv")
    eq(info(tools.convert_audio(two, "mkv", "mp3"), "mp3")["tracks"], 1)
    eq(info(tools.extract_audio(two, "mkv", "m4a"), "m4a")["tracks"], 1)
    out, ext = av2.remove_silence(two, "mkv")
    eq((ext, info(out, ext)["tracks"]), ("mp3", 1))
    e = raises(RuntimeError, lambda: tools.convert_audio(av("silent.mp4"), "mp4", "mp3"), "no usable audio")
    raises(ValueError, lambda: tools.convert_audio(two, "mkv", "xyz"), "unsupported")


@case("audio: normalize keeps the sample rate")
def _():
    for name, ext, rate in (("tone.wav", "wav", 44100), ("tone.flac", "flac", 48000)):
        out = tools.normalize_volume(av(name), ext)
        eq(info(out, ext)["rate"], rate, name)
    near(len(tools.normalize_volume(av("tone.wav"), "wav")), len(av("tone.wav")), 4096, "WAV size")


@case("audio: speed, pitch, fades, equalizer, reverse, merge")
def _():
    wav = av("tone.wav")
    for speed, want in ((0.25, 12.0), (0.5, 6.0), (2.0, 1.5), (4.0, 0.75)):
        near(info(tools.audio_speed(wav, "wav", speed), "wav")["duration"], want, 0.15, f"speed {speed}")
    for bad in (0.1, 5, float("nan")):
        raises(ValueError, lambda: tools.audio_speed(wav, "wav", bad), "between")
    for semitones in (-12, 12):
        near(info(tools.change_pitch(wav, "wav", semitones), "wav")["duration"], 3.0, 0.1)
    raises(ValueError, lambda: tools.change_pitch(wav, "wav", 13))
    near(info(tools.audio_fade(wav, "wav", 1, 1), "wav")["duration"], 3.0, 0.1)
    near(info(tools.audio_fade(wav, "wav", 10, 10), "wav")["duration"], 3.0, 0.1)
    raises(ValueError, lambda: tools.audio_fade(wav, "wav", 0, 0))
    near(info(tools.audio_equalizer(wav, "wav", 5, -5, 99), "wav")["duration"], 3.0, 0.1)
    near(info(tools.reverse_audio(wav, "wav"), "wav")["duration"], 3.0, 0.1)
    merged = tools.merge_audio_files([("wav", wav), ("wav", av("short.wav")), ("flac", av("tone.flac"))], "mp3")
    near(info(merged, "mp3")["duration"], 8.0, 0.2, "different rates and channel counts")
    near(tools.probe_duration(wav, "wav"), 3.0, 0.05)
    eq(tools.probe_duration(b"junk", "wav"), 0.0)


@case("audio: OGG output is Vorbis even when the system ffmpeg has no libvorbis")
def _():
    wav = av("tone.wav")
    if "libvorbis" not in tools._ffmpeg_encoders(tools.ffmpeg_for_output("ogg")):
        raise Skip("no ffmpeg here can encode Vorbis")
    out = tools.convert_audio(wav, "wav", "ogg")
    eq(info(out, "ogg")["acodec"], "vorbis")
    out, ext = av2.audio_bitrate(av("tone.wav"), "wav", 64, "ogg")
    eq((ext, info(out, "ogg")["acodec"]), ("ogg", "vorbis"))
    eq(zip_names(av2.split_audio(out, "ogg", "count", 2, "part")), ["part_01.ogg", "part_02.ogg"])
    raises(ValueError, lambda: av2.audio_bitrate(av("tone.wav"), "wav", 100))


@case("audio: tags read back from every container, and an existing Ogg title can be changed")
def _():
    eq(av2.read_tags(av("tone.ogg"), "ogg")["title"], "Old")
    for name in ("tone.mp3", "tone.m4a", "tone.ogg", "tone.flac", "tone.wav"):
        ext = name.rsplit(".", 1)[1]
        out, out_ext = av2.write_tags(av(name), ext, {"title": "New=Title; x", "artist": "A", "year": "2020"})
        got = av2.read_tags(out, out_ext)
        eq((got["title"], got["artist"], got["year"]), ("New=Title; x", "A", "2020"), name)
    cover = B()
    Image.new("RGBA", (101, 51), (255, 0, 0, 128)).save(cover, "PNG")
    with_cover, _ext = av2.write_tags(av("tone.mp3"), "mp3", {"title": "T"}, cover=cover.getvalue())
    assert av2.read_tags(with_cover, "mp3")["has_cover"]
    assert av2.read_tags(av2.write_tags(with_cover, "mp3", {"title": "U"})[0], "mp3")["has_cover"], "cover kept on a re-tag"


@case("audio: channels and split")
def _():
    wav = av("tone.wav")
    eq(info(av2.audio_channels(wav, "wav", "mono")[0], "wav")["channels"], 1)
    for mode in ("stereo", "swap", "left", "right"):
        eq(info(av2.audio_channels(av("short.wav"), "wav", mode)[0], "wav")["channels"], 2, f"{mode} from mono")
    raises(ValueError, lambda: av2.audio_channels(wav, "wav", "x"))
    eq(zip_names(av2.split_audio(wav, "wav", "count", 3, "t")), ["t_01.wav", "t_02.wav", "t_03.wav"])
    eq(zip_names(av2.split_audio(wav, "wav", "duration", 2, "my: 'tone'")), ["my: 'tone'_01.wav", "my: 'tone'_02.wav"])
    raises(ValueError, lambda: av2.split_audio(wav, "wav", "duration", 0.001, "t"), "too many")
    raises(ValueError, lambda: av2.split_audio(wav, "wav", "count", 1, "t"))


@case("audio to video: a still picture ends with the audio")
def _():
    picture = B()
    Image.new("RGB", (801, 601), (30, 90, 200)).save(picture, "JPEG")
    out = av2.audio_to_video(av("tone.wav"), "wav", "image", image=picture.getvalue(), image_ext="jpg", resolution="641x361")
    got = info(out, "mp4")
    eq((got["size"], got["acodec"]), ((640, 360), "aac"))
    near(got["duration"], 3.0, 0.15)
    for style in ("waveform", "spectrum"):
        near(info(av2.audio_to_video(av("tone.wav"), "wav", style, color="red;x", resolution="abc"), "mp4")["duration"], 3.0, 0.15)
    raises(ValueError, lambda: av2.audio_to_video(av("tone.wav"), "wav", "image"), "image is required")


@case("video: MP4 output is 4:2:0 with even sides, whatever goes in")
def _():
    odd, gif = av("odd.mkv"), av("odd.gif")
    outs = {
        "compress": (tools.compress_video(odd, "mkv"), "mp4"),
        "compress gif": (tools.compress_video(gif, "gif"), "mp4"),
        "convert mp4": (tools.convert_video(odd, "mkv", "mp4"), "mp4"),
        "convert mov": (tools.convert_video(odd, "mkv", "mov"), "mov"),
        "speed": av2.video_speed(odd, "mkv", 2),
        "speed gif": av2.video_speed(gif, "gif", 2),
        "stabilize": av2.stabilize_video(odd, "mkv", "high"),
        "gif to video": (av2.gif_to_video(gif, "mp4", 2), "mp4"),
        "picture in picture": (av2.picture_in_picture(odd, "mkv", av("clip.mp4"), "mp4"), "mp4"),
    }
    logo = B()
    Image.new("RGBA", (101, 51), (255, 0, 0, 128)).save(logo, "PNG")
    outs["watermark"] = av2.video_watermark(odd, "mkv", logo.getvalue(), "png")
    for name, (data, ext) in outs.items():
        got = info(data, ext)
        eq(got["pix_fmt"], "yuv420p", name)
        assert got["size"][0] % 2 == 0 and got["size"][1] % 2 == 0, f"{name}: {got['size']}"
    eq(info(tools.convert_video(odd, "mkv", "webm"), "webm")["pix_fmt"], "yuv420p", "webm")
    eq(info(tools.convert_video(odd, "mkv", "avi"), "avi")["vcodec"], "mpeg4")
    raises(ValueError, lambda: tools.convert_video(odd, "mkv", "xyz"))


@case("video: replacing the audio keeps the whole video, in any container")
def _():
    out = tools.add_audio_to_video(av("clip.mp4"), "mp4", av("short.wav"), "wav")   # 3 s video, 2 s audio
    near(info(out, "mp4")["duration"], 3.0, 0.15, "short audio is padded, video not cut")
    out = tools.add_audio_to_video(av("odd.mkv"), "mkv", av("tone.wav"), "wav")      # 2 s video, 3 s audio
    near(info(out, "mkv")["duration"], 2.0, 0.15, "long audio is cut")
    webm = tools.convert_video(av("silent.mp4"), "mp4", "webm")
    eq(info(tools.add_audio_to_video(webm, "webm", av("tone.wav"), "wav"), "webm")["acodec"], "opus")
    eq(info(tools.mute_video(av("clip.mp4"), "mp4"), "mp4")["acodec"], None)


@case("video: crop, rotate, resize, reverse, loop, GIF")
def _():
    clip, silent = av("clip.mp4"), av("silent.mp4")
    eq(info(tools.crop_video(clip, "mp4", 101, 101, 10, 10), "mp4")["size"], (100, 100))
    raises(RuntimeError, lambda: tools.crop_video(clip, "mp4", 1000, 1000), "does not fit")
    raises(ValueError, lambda: tools.crop_video(clip, "mp4", 1, 1))
    eq(info(tools.rotate_video(clip, "mp4", 90), "mp4")["size"], (240, 320))
    eq(info(tools.rotate_video(silent, "mp4", 180), "mp4")["size"], (320, 240))
    raises(ValueError, lambda: tools.rotate_video(clip, "mp4", 45))
    eq(info(tools.resize_video(clip, "mp4", 161, -1), "mp4")["size"], (160, 120))
    eq(info(tools.resize_video(clip, "mp4", -1, 101), "mp4")["size"], (134, 100))
    near(info(tools.reverse_video(silent, "mp4"), "mp4")["duration"], 3.0, 0.15, "no audio track")
    near(info(tools.reverse_video(clip, "mp4"), "mp4")["duration"], 3.0, 0.15)
    near(info(tools.loop_video(clip, "mp4", 3), "mp4")["duration"], 9.0, 0.3)
    raises(ValueError, lambda: tools.loop_video(clip, "mp4", 0))
    eq(reopen(tools.video_to_gif(clip, "mp4", 5, 160)).size, (160, 120))
    for speed, want in ((0.25, 12.0), (4.0, 0.75)):
        near(info(av2.video_speed(clip, "mp4", speed)[0], "mp4")["duration"], want, 0.3, f"speed {speed}")
    near(info(av2.video_speed(silent, "mp4", 2, keep_pitch=False)[0], "mp4")["duration"], 1.5, 0.2)
    raises(ValueError, lambda: av2.video_speed(clip, "mp4", 9))


@case("video: a failed job names the real problem, not a missing stream")
def _():
    eq(tools._friendly_ffmpeg_error("Stream mapping:\n  Stream #0:0 -> #0:0\n[libx264] width not divisible by 2 (321x241)"),
       "Those dimensions are not valid for this video format. Try an even width and height.")
    assert "stream" not in tools._friendly_ffmpeg_error("Stream mapping:\n  Stream #0:0 -> #0:0\nsomething else broke").lower()
    assert "no usable" in tools._friendly_ffmpeg_error("Stream map '0:a' matches no streams.")
    raises(RuntimeError, lambda: tools.convert_video(b"not a video", "mp4", "mp4"), "could not be read")
    eq([tools._ext_from_filename(n, "bin") for n in ("a.MP4", "a./x", "a.mp4 ", "a", "a.b c", "a.")],
       ["mp4", "bin", "mp4", "bin", "bin", "bin"])


@case("video: portrait phone clips stay portrait when merged or watermarked")
def _():
    portrait = av("portrait.mp4")
    eq(av2.media_info(portrait, "mp4")["video"]["rotation"] % 180, 90)
    eq(info(av2.merge_videos([("mp4", portrait), ("mp4", portrait)]), "mp4")["size"], (240, 320))
    got = info(av2.merge_videos([("mp4", av("clip.mp4")), ("mp4", av("silent.mp4")), ("mkv", av("odd.mkv"))]), "mp4")
    eq((got["size"], got["acodec"]), ((320, 240), "aac"))
    near(got["duration"], 8.0, 0.3, "a clip with no audio gets silence")
    raises(ValueError, lambda: av2.merge_videos([("mp4", av("clip.mp4")), ("wav", av("tone.wav"))]), "no video")
    raises(ValueError, lambda: av2.merge_videos([("mp4", av("clip.mp4"))]))
    logo = B()
    Image.new("RGB", (100, 100), (255, 255, 255)).save(logo, "PNG")
    # A white logo at 50% of the width, top-left with no margin, on the 240-wide picture.
    out, ext = av2.video_watermark(portrait, "mp4", logo.getvalue(), "png", "top-left", scale=50, margin=0)
    frame = reopen(av2.extract_frames(out, ext, "single", "f", time=1)[0]).convert("L")
    eq(frame.size, (240, 320))
    assert frame.getpixel((100, 60)) > 235 and frame.getpixel((140, 60)) < 235, "logo should be 120 px wide"
    raises(ValueError, lambda: av2.video_watermark(portrait, "mp4", logo.getvalue(), "png", position="x"))
    raises(ValueError, lambda: av2.picture_in_picture(portrait, "mp4", portrait, "mp4", position="center"))


@case("video: frames taken at an interval are from the times in their names")
def _():
    ramp = av("ramp.mp4")
    level = lambda png: reopen(png).convert("L").getpixel((5, 5)) / 20
    zero = level(av2.extract_frames(ramp, "mp4", "single", "r", time=0)[0])
    archive = zipfile.ZipFile(B(av2.extract_frames(ramp, "mp4", "interval", "r", interval=2)[0]))
    eq(archive.namelist(), ["r_0s.png", "r_2s.png", "r_4s.png", "r_6s.png", "r_8s.png"])
    for i, name in enumerate(archive.namelist()):
        near(level(archive.read(name)) - zero, i * 2, 0.3, name)
    archive = zipfile.ZipFile(B(av2.extract_frames(ramp, "mp4", "count", "r", count=4, fmt="jpg")[0]))
    eq(archive.namelist(), ["r_001_1.25s.jpg", "r_002_3.75s.jpg", "r_003_6.25s.jpg", "r_004_8.75s.jpg"])
    for name, t in zip(archive.namelist(), (1.25, 3.75, 6.25, 8.75)):
        near(level(archive.read(name)) - zero, t, 0.4, name)
    raises(RuntimeError, lambda: av2.extract_frames(ramp, "mp4", "single", "r", time=99), "no frame")
    raises(ValueError, lambda: av2.extract_frames(ramp, "mp4", "interval", "r", interval=0.001), "more than 1000")
    raises(ValueError, lambda: av2.extract_frames(ramp, "mp4", "count", "r", count=0))


@case("video: subtitles burn in from an awkward temp folder; legacy encodings get a clear error")
def _():
    if not tools.ffmpeg_exe_with_filter("subtitles"):
        raise Skip("no ffmpeg with the subtitles filter")
    srt = "1\n00:00:00,000 --> 00:00:02,000\nHello\n"
    clip = av("clip.mp4")
    work = Path(tempfile.mkdtemp(prefix="sdexe-tools-test-")) / "it's, a [dir]; x"
    work.mkdir()
    saved = tempfile.tempdir
    tempfile.tempdir = str(work)
    try:
        near(info(tools.burn_subtitles(clip, "mp4", srt.encode()), "mp4")["duration"], 3.0, 0.15)
    finally:
        tempfile.tempdir = saved
        shutil.rmtree(work.parent, ignore_errors=True)
    near(info(tools.burn_subtitles(clip, "mp4", srt.encode("utf-16")), "mp4")["duration"], 3.0, 0.15, "UTF-16")
    near(info(tools.burn_subtitles(clip, "mp4", b"\xef\xbb\xbf" + srt.encode()), "mp4")["duration"], 3.0, 0.15, "BOM")
    raises(ValueError, lambda: tools.burn_subtitles(clip, "mp4", srt.replace("Hello", "שלום").encode("cp1255")), "utf-8")


@case("video: probing without ffprobe, and a file name that starts with a dash")
def _():
    saved = av2.ffprobe_path
    try:
        results = []
        for probe in (saved, lambda: None):
            av2.ffprobe_path = probe
            results.append([info(av(name), name.rsplit(".", 1)[1]) for name in ("portrait.mp4", "tone.wav", "odd.mkv")]
                           + [av2.read_tags(av("tone.ogg"), "ogg")["title"]])
        for with_probe, without in zip(*results):
            if isinstance(with_probe, dict):
                near(without.pop("duration"), with_probe.pop("duration"), 0.1)
            eq(without, with_probe)
    finally:
        av2.ffprobe_path = saved
    work = Path(tempfile.mkdtemp(prefix="sdexe-tools-test-"))
    import os
    here = os.getcwd()
    try:
        (work / "-clip.mp4").write_bytes(av("clip.mp4"))
        os.chdir(work)
        near(av2.media_info_path("-clip.mp4")["duration"], 3.0, 0.1)
    finally:
        os.chdir(here)
        shutil.rmtree(work, ignore_errors=True)
    raises(RuntimeError, lambda: av2.media_info(b"junk", "mp4"), "could not read")


@case("pdf: pages left out are not kept hidden in the file through a link to them")
def _():
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Link
    from pypdf.generic import NameObject, DecodedStreamObject
    w = PdfWriter()
    for word in ("ALPHA", "SECRETPAGE", "GAMMA"):
        page = w.add_blank_page(200, 200)
        content = DecodedStreamObject()
        content.set_data(f"% {word}".encode())
        page[NameObject("/Contents")] = w._add_object(content)
    for n in (0, 2):
        w.add_annotation(n, Link(rect=(0, 0, 50, 50), target_page_index=1))
    buf = io.BytesIO()
    w.write(buf)
    src = buf.getvalue()

    def holds_secret(pdf):
        # Contents are uncompressed here, so the bytes show every object kept.
        return b"SECRETPAGE" in pdf

    eq(holds_secret(src), True, "fixture")
    outs = [d for _, d in tools.split_pdf(io.BytesIO(src), "1,3")]
    outs += [tools.delete_pdf_pages(io.BytesIO(src), "2"), tools.reorder_pdf(io.BytesIO(src), [3, 1])]
    import argparse
    from sdexe import cli_tools
    tmp = Path(tempfile.mkdtemp(prefix="sdexe-tools-test-"))
    try:
        (tmp / "in.pdf").write_bytes(src)
        outs.append(cli_tools._pdf_pages(tmp / "in.pdf", argparse.Namespace(pages="1,3")).data)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    eq([holds_secret(d) for d in outs], [False] * len(outs))
    eq([len(PdfReader(io.BytesIO(d)).pages) for d in outs], [1, 1, 2, 2, 2])


@case("every program the tools start has its own stdin")
def _():
    # ffmpeg reads keys from a terminal it inherits: pressing q during
    # `sdexe video compress` saved half the video and reported success.
    import ast
    bad = []
    for name in ("tools", "tools_av2", "tools_convert2", "tools_pdf2"):
        path = Path(tools.__file__).with_name(f"{name}.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("run", "Popen") and getattr(node.func.value, "id", "") == "subprocess"
                    and not any(k.arg in ("stdin", "input") for k in node.keywords)):
                bad.append(f"{name}.py:{node.lineno}")
    eq(bad, [])


@case("transcribe: speaker labels with the pyannote.audio 3 and 4 calls")
def _():
    import types

    class Turns:
        def itertracks(self, yield_label):
            yield types.SimpleNamespace(start=0.0, end=1.5), None, "SPEAKER_00"

    class V3:
        @classmethod
        def from_pretrained(cls, checkpoint, hparams_file=None, use_auth_token=None, cache_dir=None):
            eq(use_auth_token, "hf_x")
            return lambda path, **kw: Turns()

    class V4:
        @classmethod
        def from_pretrained(cls, checkpoint, revision=None, hparams_file=None, subfolder=None, token=None, cache_dir=None):
            eq(token, "hf_x")
            return lambda path, **kw: types.SimpleNamespace(speaker_diarization=Turns())

    saved = {k: sys.modules.get(k) for k in ("pyannote", "pyannote.audio")}
    try:
        for version in (V3, V4):
            sys.modules["pyannote"] = types.ModuleType("pyannote")
            sys.modules["pyannote.audio"] = types.SimpleNamespace(Pipeline=version)
            eq(tools.diarize_audio("x.wav", "hf_x"), [{"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"}])
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ── run ──

def main() -> int:
    rows = []
    for name, fn in CASES:
        if ONLY and not any(word.lower() in name.lower() for word in ONLY):
            continue
        try:
            fn()
            rows.append((name, "PASS", ""))
        except Skip as e:
            rows.append((name, "SKIP", str(e)))
        except AssertionError as e:
            rows.append((name, "FAIL", str(e) or traceback.format_exc(limit=-1).strip().splitlines()[-2].strip()))
        except Exception as e:
            where = traceback.extract_tb(e.__traceback__)[-1]
            rows.append((name, "FAIL", f"{type(e).__name__}: {e} ({Path(where.filename).name}:{where.lineno})"))

    width = max((len(r[0]) for r in rows), default=0) + 2
    for name, outcome, detail in rows:
        if VERBOSE or outcome != "PASS":
            print(f"  {outcome:4}  {name.ljust(width)}{detail}")
    counts = {k: sum(r[1] == k for r in rows) for k in ("PASS", "FAIL", "SKIP")}
    print(f"\n  {len(rows)} checks:  {counts['PASS']} PASS   {counts['FAIL']} FAIL   {counts['SKIP']} SKIP")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
