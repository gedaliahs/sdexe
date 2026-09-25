"""`sdexe pdf|image|audio|video|convert|file ...`: the local tools from the terminal.

COMMANDS is the single description of every command. Argument parsing, help,
output handling, the MCP server (`sdexe mcp`) and the agent skill
(`sdexe skill`) are all generated from it, so adding a row adds it everywhere.

Conventions, shared with `sdexe download`:
  - Outputs land in the current folder as <name>-<action>.<ext>, never over an
    existing file. -o sets a folder, or an exact file name for one input.
  - stdout carries only results: saved paths (one per line) when piped, the
    text itself for text commands, one JSON document with --json.
  - Exit 0 when every input succeeded, 1 if any failed, 2 on bad usage.
"""

import argparse
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sdexe import tools
from sdexe.cli import UsageError, fmt_size, parse_time, _escape

# ── Table types ──


@dataclass
class Arg:
    flag: str                      # "--angle"
    type: type = str               # str, int, float, bool (a switch)
    default: object = None
    required: bool = False
    choices: tuple | None = None
    help: str = ""
    short: str | None = None       # "-f"

    @property
    def dest(self):
        return self.flag.lstrip("-").replace("-", "_")


@dataclass
class Result:
    data: bytes | None = None      # one output file
    ext: str | None = None
    name: str | None = None        # output stem, when it shouldn't follow the input
    files: list | None = None      # [(name, bytes)] written into a folder
    text: str | None = None        # printed to stdout
    obj: dict | None = None        # printed as key: value, or JSON


@dataclass
class Cmd:
    group: str
    name: str                      # "" for a group with a single command (convert)
    summary: str
    run: Callable                  # (path, args) -> Result, or (paths, args) for many/pair
    inputs: str = "each"           # each: 1+ files, one result per file | many: all files, one result
                                   # pair: exactly two files | none: no files
    args: list = field(default_factory=list)
    suffix: str = ""               # output stem is <input>-<suffix>
    example: str = ""
    inputs_help: str = "FILE ..."
    text_arg: str | None = None    # for inputs="none": a positional text argument

    @property
    def full(self):
        return f"{self.group} {self.name}".strip()

    @property
    def tool_name(self):
        return f"{self.group}_{self.name}".strip("_").replace("-", "_")


# ── Helpers the table uses ──

def _read(p: Path) -> bytes:
    return Path(p).read_bytes()


def _ext(p: Path) -> str:
    return Path(p).suffix.lstrip(".").lower()


def _img(p: Path):
    from PIL import Image
    from sdexe import tools_images2  # noqa: F401  registers the HEIC opener
    img = Image.open(p)
    img.load()
    return img


def _img_ext(p: Path) -> str:
    ext = _ext(p)
    return ext if ext in tools._PIL_FMT_MAP else "png"


def _img_result(img, p: Path) -> Result:
    ext = _img_ext(p)
    return Result(tools._save_image(img, ext), ext)


def _ts(value: str | None) -> str:
    """Any time the CLI accepts, as seconds for ffmpeg."""
    return "" if value in (None, "") else f"{parse_time(value):g}"


def _pdf_stream(p: Path):
    return io.BytesIO(_read(p))


def _unzip(data: bytes) -> list:
    return tools.extract_zip(data)


# ── Command implementations that need more than one call ──

def _pdf_pages(p, a):
    from pypdf import PdfReader, PdfWriter
    from sdexe import tools_pdf2
    reader = PdfReader(str(p))
    writer = PdfWriter()
    for i in tools_pdf2.parse_pages(a.pages, len(reader.pages)):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return Result(buf.getvalue(), "pdf")


def _pdf_info(p, a):
    info = {"pages": tools.pdf_page_count(_pdf_stream(p)), "size_bytes": p.stat().st_size}
    try:
        info.update({k: v for k, v in tools.get_pdf_metadata(_pdf_stream(p)).items() if v})
    except Exception as e:  # noqa: BLE001 - encrypted files still have a page count
        info["metadata_error"] = str(e)
    return Result(obj=info)


def _pdf_reorder(p, a):
    try:
        order = [int(x) for x in a.order.replace(" ", "").split(",") if x]
    except ValueError:
        raise ValueError("--order takes page numbers like 3,1,2")
    return Result(tools.reorder_pdf(_pdf_stream(p), order), "pdf")


def _image_resize(p, a):
    if not (a.width or a.height or a.percent):
        raise ValueError("Give --width, --height or --percent.")
    mode = "percentage" if a.percent else "dimensions"
    img = tools.resize_image(_img(p), mode, width=a.width or 0, height=a.height or 0,
                             percentage=a.percent or 100, maintain_aspect=not a.stretch)
    return _img_result(img, p)


def _image_compress(p, a):
    q = {"high": 85, "medium": 60, "low": 30}.get(str(a.quality).lower())
    if q is None:
        try:
            q = int(a.quality)
        except ValueError:
            raise ValueError("--quality takes 1-100 or high, medium, low")
    if not 1 <= q <= 100:
        raise ValueError("--quality must be between 1 and 100")
    ext = _img_ext(p)
    return Result(tools.compress_image(_img(p), q, ext), ext)


def _image_crop(p, a):
    return _img_result(tools.crop_image(_img(p), a.x, a.y, a.x + a.width, a.y + a.height), p)


def _image_info(p, a):
    from sdexe import tools_images2
    with open(p, "rb") as f:
        return Result(obj=tools_images2.read_exif(f, p.name, p.stat().st_size))


def _image_collage(paths, a):
    from sdexe import tools_images2
    sheet, _css = tools_images2.make_collage([(p.name, _img(p)) for p in paths], columns=a.columns,
                                             cell=a.cell, gap=a.gap, background=a.background)
    return Result(tools._save_image(sheet, "png"), "png", name="collage")


def _hash(p):
    with open(p, "rb") as f:
        return _lazy("tools_convert2", "checksum")(f)


def _av_media_info(p, a):
    from sdexe import tools_av2
    return Result(obj=tools_av2.media_info_path(str(p)))


def _av_tuple(result) -> Result:
    data, ext = result
    return Result(data, ext)


def _audio_split(p, a):
    from sdexe import tools_av2
    mode, value = ("count", a.parts) if a.parts else ("duration", parse_time(a.every) if a.every else None)
    if value is None:
        raise ValueError("Give --every LENGTH (e.g. 5:00) or --parts N.")
    return Result(files=_unzip(tools_av2.split_audio(_read(p), _ext(p), mode, value, p.stem)))


def _video_frames(p, a):
    from sdexe import tools_av2
    if a.at is not None:
        mode = "single"
    elif a.count:
        mode = "count"
    else:
        mode = "interval"
    data, name, mime = tools_av2.extract_frames(
        _read(p), _ext(p), mode, p.stem, time=parse_time(a.at) if a.at else 0,
        interval=parse_time(a.every) if a.every else 1, count=a.count or 10, fmt=a.format)
    if mime == "application/zip":
        return Result(files=_unzip(data))
    return Result(data, Path(name).suffix.lstrip("."), name=Path(name).stem)


def _video_merge(paths, a):
    from sdexe import tools_av2
    return Result(tools_av2.merge_videos([(p.name, _read(p)) for p in paths]), "mp4", name="merged")


# Data conversions: (from, to) -> function over text, or over bytes when
# the source is binary.
_TEXT_CONVERSIONS = {
    ("csv", "json"): tools.csv_to_json_str,
    ("json", "csv"): tools.json_to_csv_str,
    ("yaml", "json"): tools.yaml_to_json_str,
    ("yml", "json"): tools.yaml_to_json_str,
    ("json", "yaml"): tools.json_to_yaml_str,
    ("csv", "tsv"): tools.csv_to_tsv_str,
    ("tsv", "csv"): tools.tsv_to_csv_str,
    ("xml", "json"): tools.xml_to_json_str,
    ("md", "html"): tools.md_to_html,
    ("markdown", "html"): tools.md_to_html,
}


def _convert2(name):
    def call(text):
        from sdexe import tools_convert2
        return getattr(tools_convert2, name)(text)
    return call


_TEXT_CONVERSIONS.update({
    ("json", "xml"): _convert2("json_to_xml_str"),
    ("toml", "json"): _convert2("toml_to_json_str"),
    ("json", "toml"): _convert2("json_to_toml_str"),
    ("html", "md"): _convert2("html_to_md_str"),
    ("htm", "md"): _convert2("html_to_md_str"),
})
_CONVERT_TARGETS = sorted({t for _, t in _TEXT_CONVERSIONS} | {"xlsx", "csv", "json", "pdf", "png", "jpg", "webp"})


def _convert(p, a):
    src, dst = _ext(p), a.format.lower().lstrip(".")
    if dst == "yml":
        dst = "yaml"
    if (src, dst) in _TEXT_CONVERSIONS:
        return Result(_TEXT_CONVERSIONS[(src, dst)](p.read_text(encoding="utf-8")).encode("utf-8"), dst)
    if src == "xlsx" and dst == "csv":
        from sdexe import tools_convert2
        sheets = tools_convert2.xlsx_to_csv(_read(p), a.sheet or "")
        if len(sheets) == 1:
            return Result(sheets[0][1].encode("utf-8"), "csv")
        return Result(files=[(f"{name}.csv", text.encode("utf-8")) for name, text in sheets])
    if src == "csv" and dst == "xlsx":
        from sdexe import tools_convert2
        return Result(tools_convert2.csv_to_xlsx([(p.name, p.read_text(encoding="utf-8"))]), "xlsx")
    if dst == "pdf" and src in ("doc", "docx", "odt", "rtf", "xls", "xlsx", "ods", "ppt", "pptx", "odp"):
        from sdexe import tools_pdf2
        with open(p, "rb") as f:
            return Result(tools_pdf2.office_to_pdf(f, p.name), "pdf")
    if dst in ("png", "jpg", "jpeg", "webp", "gif") and src in ("png", "jpg", "jpeg", "webp", "gif", "bmp",
                                                                 "tif", "tiff", "heic", "heif"):
        dst = "jpg" if dst == "jpeg" else dst
        return Result(tools.convert_image(_img(p), dst), dst)
    pairs = ", ".join(f"{s}→{t}" for s, t in sorted(_TEXT_CONVERSIONS) if s == src)
    hint = f" From .{src} this can make: {pairs}." if pairs else ""
    raise ValueError(f"Can't convert .{src} to .{dst}.{hint} For media use `sdexe audio convert` / `sdexe video convert`.")


# ── The table ──

_POS = ("center", "top-left", "top-right", "bottom-left", "bottom-right")
_CORNERS = ("bottom-right", "bottom-left", "top-right", "top-left")
_AUDIO_FMTS = tuple(tools.AUDIO_CODEC_MAP)
_VIDEO_FMTS = tuple(tools.VIDEO_CODEC_MAP)
_START = Arg("--start", default="0", help="start time: 90, 1:30, 1:02:03, 1m30s")
_END = Arg("--end", help="end time (default: the end)")


def _lazy(module, name):
    """Call sdexe.<module>.<name> without importing it at startup."""
    def call(*args, **kwargs):
        import importlib
        return getattr(importlib.import_module(f"sdexe.{module}"), name)(*args, **kwargs)
    return call


pdf2, img2, av2, conv2 = (lambda n: _lazy("tools_pdf2", n)), (lambda n: _lazy("tools_images2", n)), \
    (lambda n: _lazy("tools_av2", n)), (lambda n: _lazy("tools_convert2", n))

COMMANDS: list[Cmd] = [
    # PDF
    Cmd("pdf", "merge", "combine PDFs into one, in the order given", inputs="many", inputs_help="FILE FILE ...",
        run=lambda ps, a: Result(tools.merge_pdfs([_pdf_stream(p) for p in ps]), "pdf", name="merged"),
        example="sdexe pdf merge intro.pdf body.pdf -o book.pdf"),
    Cmd("pdf", "split", "split into one PDF per page, or per range", suffix="split",
        args=[Arg("--ranges", help="page ranges like 1-3,4-6 (default: every page)")],
        run=lambda p, a: Result(files=tools.split_pdf(_pdf_stream(p), a.ranges or "")),
        example="sdexe pdf split report.pdf --ranges 1-2,3-10"),
    Cmd("pdf", "pages", "keep only some pages", suffix="pages",
        args=[Arg("--pages", required=True, help="pages to keep, like 1-3,5")],
        run=_pdf_pages, example="sdexe pdf pages report.pdf --pages 1-3"),
    Cmd("pdf", "delete", "remove pages", suffix="trimmed",
        args=[Arg("--pages", required=True, help="pages to remove, like 2,5-7")],
        run=lambda p, a: Result(tools.delete_pdf_pages(_pdf_stream(p), a.pages), "pdf")),
    Cmd("pdf", "reorder", "put pages in a new order", suffix="reordered",
        args=[Arg("--order", required=True, help="the new order, like 3,1,2")], run=_pdf_reorder),
    Cmd("pdf", "rotate", "rotate pages", suffix="rotated",
        args=[Arg("--angle", int, 90, choices=(90, 180, 270), help="degrees clockwise"),
              Arg("--pages", default="all", help="which pages, like 1,3-4")],
        run=lambda p, a: Result(tools.rotate_pdf(_pdf_stream(p), a.angle, a.pages), "pdf")),
    Cmd("pdf", "compress", "shrink a PDF", suffix="compressed",
        run=lambda p, a: Result(tools.compress_pdf(_pdf_stream(p)), "pdf")),
    Cmd("pdf", "text", "extract the text", run=lambda p, a: Result(text=tools.pdf_to_text(_pdf_stream(p))),
        example="sdexe pdf text report.pdf > report.txt"),
    Cmd("pdf", "ocr", "read text from a scanned PDF or image (needs tesseract)",
        args=[Arg("--lang", default="eng", help="tesseract language code(s), like eng or eng+deu")],
        run=lambda p, a: Result(text=pdf2("ocr_document")(_pdf_stream(p), p.name, a.lang)[0])),
    Cmd("pdf", "info", "page count and metadata", run=_pdf_info),
    Cmd("pdf", "encrypt", "add a password", suffix="locked",
        args=[Arg("--password", required=True)],
        run=lambda p, a: Result(tools.add_pdf_password(_pdf_stream(p), a.password), "pdf")),
    Cmd("pdf", "decrypt", "remove a password", suffix="unlocked",
        args=[Arg("--password", required=True)],
        run=lambda p, a: Result(tools.remove_pdf_password(_pdf_stream(p), a.password), "pdf")),
    Cmd("pdf", "watermark", "stamp text on every page", suffix="watermarked",
        args=[Arg("--text", required=True), Arg("--size", int, 36, help="font size"),
              Arg("--opacity", float, 0.3, help="0 to 1"), Arg("--position", default="center", choices=_POS)],
        run=lambda p, a: Result(tools.watermark_pdf(_pdf_stream(p), a.text, a.size, a.opacity, a.position), "pdf")),
    Cmd("pdf", "number", "add page numbers", suffix="numbered",
        args=[Arg("--start", int, 1, help="first page number"),
              Arg("--position", default="bottom-center", choices=("bottom-center", "bottom-left", "bottom-right")),
              Arg("--size", int, 11, help="font size")],
        run=lambda p, a: Result(tools.number_pdf_pages(_pdf_stream(p), a.start, a.position, a.size), "pdf")),
    Cmd("pdf", "images", "render pages as images", suffix="pages",
        args=[Arg("--format", default="png", choices=("png", "jpg"), short="-f"),
              Arg("--dpi", int, 150, choices=(72, 150, 300)),
              Arg("--pages", default="all", help="which pages, like 1-3")],
        run=lambda p, a: Result(files=pdf2("pdf_to_images")(_pdf_stream(p), a.format, a.dpi, a.pages))),
    Cmd("pdf", "extract-images", "save the images embedded in a PDF", suffix="images",
        run=lambda p, a: Result(files=tools.extract_images_from_pdf(_pdf_stream(p)))),
    Cmd("pdf", "from-images", "make one PDF from images, one per page", inputs="many",
        run=lambda ps, a: Result(tools.images_to_pdf([_img(p) for p in ps]), "pdf", name="images"),
        example="sdexe pdf from-images scan1.jpg scan2.jpg -o scans.pdf"),
    Cmd("pdf", "from-office", "convert Word, Excel, PowerPoint or ODF to PDF (needs LibreOffice)",
        run=lambda p, a: Result(pdf2("office_to_pdf")(_pdf_stream(p), p.name), "pdf")),
    Cmd("pdf", "flatten", "bake forms and annotations into the page", suffix="flat",
        args=[Arg("--dpi", int, 150)], run=lambda p, a: Result(pdf2("flatten_pdf")(_pdf_stream(p), a.dpi), "pdf")),
    Cmd("pdf", "resize", "fit every page to a paper size", suffix="resized",
        args=[Arg("--size", default="a4", choices=("a3", "a4", "a5", "letter", "legal")),
              Arg("--fit", default="fit", choices=("fit", "fill", "stretch"))],
        run=lambda p, a: Result(pdf2("resize_pdf_pages")(_pdf_stream(p), a.size, a.fit), "pdf")),
    Cmd("pdf", "stamp", "place an image (logo, signature) on pages", inputs="pair", inputs_help="PDF IMAGE",
        suffix="stamped",
        args=[Arg("--position", default="bottom-right", choices=_CORNERS + ("center",)),
              Arg("--scale", float, 25, help="width as a % of the page"), Arg("--opacity", float, 100),
              Arg("--pages", default="all")],
        run=lambda ps, a: Result(pdf2("stamp_pdf")(_pdf_stream(ps[0]), _pdf_stream(ps[1]), a.position, a.scale,
                                                   a.opacity, a.pages), "pdf")),

    # Images
    Cmd("image", "resize", "resize by pixels or percent", suffix="resized",
        args=[Arg("--width", int, help="pixels"), Arg("--height", int, help="pixels"),
              Arg("--percent", float, help="scale, like 50"),
              Arg("--stretch", bool, help="ignore aspect ratio when both width and height are given")],
        run=_image_resize, example="sdexe image resize *.jpg --width 1200"),
    Cmd("image", "compress", "smaller file, same format", suffix="compressed",
        args=[Arg("--quality", default="60", help="1-100, or high / medium / low")], run=_image_compress),
    Cmd("image", "convert", "change format (reads HEIC too)",
        args=[Arg("--format", required=True, choices=("png", "jpg", "webp", "gif"), short="-f")],
        run=lambda p, a: Result(tools.convert_image(_img(p), a.format), a.format),
        example="sdexe image convert IMG_0001.heic -f jpg"),
    Cmd("image", "crop", "cut out a rectangle", suffix="cropped",
        args=[Arg("--x", int, 0), Arg("--y", int, 0), Arg("--width", int, required=True),
              Arg("--height", int, required=True)], run=_image_crop),
    Cmd("image", "rotate", "rotate clockwise", suffix="rotated",
        args=[Arg("--angle", int, 90, help="degrees clockwise")],
        run=lambda p, a: _img_result(tools.rotate_image(_img(p), a.angle), p)),
    Cmd("image", "flip", "mirror", suffix="flipped",
        args=[Arg("--direction", default="horizontal", choices=("horizontal", "vertical"))],
        run=lambda p, a: _img_result(tools.flip_image(_img(p), a.direction), p)),
    Cmd("image", "grayscale", "black and white", suffix="gray",
        run=lambda p, a: _img_result(tools.grayscale_image(_img(p)), p)),
    Cmd("image", "blur", "gaussian blur", suffix="blurred", args=[Arg("--radius", float, 5.0)],
        run=lambda p, a: _img_result(tools.blur_image(_img(p), a.radius), p)),
    Cmd("image", "strip-exif", "remove EXIF metadata (location, camera)", suffix="clean",
        run=lambda p, a: _img_result(tools.strip_exif(_img(p)), p)),
    Cmd("image", "watermark", "draw text on the image", suffix="watermarked",
        args=[Arg("--text", required=True), Arg("--position", default="center", choices=_POS),
              Arg("--opacity", int, 128, help="0-255"), Arg("--size", int, 36, help="font size")],
        run=lambda p, a: _img_result(tools.watermark_image(_img(p), a.text, a.position, a.opacity, a.size), p)),
    Cmd("image", "adjust", "brightness, contrast, saturation, sharpness", suffix="adjusted",
        args=[Arg("--brightness", float, 100, help="percent, 100 = unchanged"), Arg("--contrast", float, 100),
              Arg("--saturation", float, 100), Arg("--sharpness", float, 100)],
        run=lambda p, a: _img_result(img2("adjust_image_full")(_img(p), a.brightness, a.contrast, a.saturation,
                                                                a.sharpness), p)),
    Cmd("image", "border", "add a border or padding", suffix="bordered",
        args=[Arg("--size", int, 20, help="pixels"), Arg("--color", default="#ffffff"),
              Arg("--radius", int, 0, help="corner radius")],
        run=lambda p, a: _img_result(img2("add_border")(_img(p), a.size, a.color, "border", a.radius), p)),
    Cmd("image", "upscale", "enlarge with sharpening", suffix="upscaled",
        args=[Arg("--factor", int, 2, choices=(2, 3, 4))],
        run=lambda p, a: _img_result(img2("upscale_image")(_img(p), a.factor), p)),
    Cmd("image", "info", "size, format and EXIF", run=_image_info),
    Cmd("image", "ico", "make a Windows .ico", args=[Arg("--sizes", default="16,32,48,64,128,256")],
        run=lambda p, a: Result(tools.image_to_ico(_img(p), [int(s) for s in a.sizes.split(",")]), "ico")),
    Cmd("image", "favicon", "a full favicon set for a website", suffix="favicon",
        run=lambda p, a: Result(files=_unzip(img2("favicon_set")(_img(p))))),
    Cmd("image", "collage", "arrange images in a grid", inputs="many",
        args=[Arg("--columns", int, 0, help="0 picks automatically"), Arg("--cell", int, 256, help="cell size, pixels"),
              Arg("--gap", int, 0), Arg("--background", default="#ffffff")],
        run=_image_collage),
    Cmd("image", "ascii", "turn an image into ASCII art",
        args=[Arg("--width", int, 100, help="characters per line"), Arg("--invert", bool)],
        run=lambda p, a: Result(text=img2("image_to_ascii")(_img(p), a.width, "standard", a.invert))),
    Cmd("image", "qr", "make a QR code PNG", inputs="none", text_arg="text", inputs_help="TEXT",
        args=[Arg("--box-size", int, 10), Arg("--border", int, 4)],
        run=lambda _, a: Result(tools.generate_qr(a.text, a.box_size, a.border), "png", name="qr"),
        example='sdexe image qr "https://example.com" -o qr.png'),

    # Audio
    Cmd("audio", "convert", "change format",
        args=[Arg("--format", required=True, choices=_AUDIO_FMTS, short="-f")],
        run=lambda p, a: Result(tools.convert_audio(_read(p), _ext(p), a.format), a.format),
        example="sdexe audio convert song.wav -f mp3"),
    Cmd("audio", "trim", "keep a section", suffix="trimmed", args=[_START, _END],
        run=lambda p, a: Result(tools.trim_audio(_read(p), _ext(p), _ts(a.start), _ts(a.end)), _ext(p)),
        example="sdexe audio trim podcast.mp3 --start 1:00 --end 2:30"),
    Cmd("audio", "speed", "faster or slower, pitch kept", suffix="speed",
        args=[Arg("--speed", float, required=True, help="0.25 to 4, like 1.5")],
        run=lambda p, a: Result(tools.audio_speed(_read(p), _ext(p), a.speed),
                                _ext(p) if _ext(p) in ("mp3", "wav", "ogg", "flac") else "mp3")),
    Cmd("audio", "normalize", "even out loudness (EBU R128)", suffix="normalized",
        run=lambda p, a: Result(tools.normalize_volume(_read(p), _ext(p)), _ext(p))),
    Cmd("audio", "fade", "fade in and/or out", suffix="faded",
        args=[Arg("--in", float, 0, help="seconds"), Arg("--out", float, 0, help="seconds")],
        run=lambda p, a: Result(tools.audio_fade(_read(p), _ext(p), getattr(a, "in"), a.out,
                                                 tools.probe_duration(_read(p), _ext(p))), _ext(p))),
    Cmd("audio", "pitch", "shift pitch, speed kept", suffix="pitched",
        args=[Arg("--semitones", float, required=True, help="-12 to 12")],
        run=lambda p, a: Result(tools.change_pitch(_read(p), _ext(p), a.semitones), _ext(p))),
    Cmd("audio", "eq", "bass / mid / treble", suffix="eq",
        args=[Arg("--bass", float, 0, help="dB"), Arg("--mid", float, 0), Arg("--treble", float, 0)],
        run=lambda p, a: Result(tools.audio_equalizer(_read(p), _ext(p), a.bass, a.mid, a.treble), _ext(p))),
    Cmd("audio", "reverse", "play backwards", suffix="reversed",
        run=lambda p, a: Result(tools.reverse_audio(_read(p), _ext(p)), _ext(p))),
    Cmd("audio", "silence", "remove silent parts", suffix="nosilence",
        args=[Arg("--threshold", float, -40, help="dB below which counts as silence"),
              Arg("--min", float, 0.5, help="shortest gap to cut, seconds")],
        run=lambda p, a: _av_tuple(av2("remove_silence")(_read(p), _ext(p), a.threshold, a.min))),
    Cmd("audio", "channels", "mono, stereo, left, right or swap", suffix="channels",
        args=[Arg("--mode", required=True, choices=("mono", "stereo", "left", "right", "swap"))],
        run=lambda p, a: _av_tuple(av2("audio_channels")(_read(p), _ext(p), a.mode))),
    Cmd("audio", "bitrate", "re-encode at a bitrate", suffix="bitrate",
        args=[Arg("--kbps", int, required=True, choices=(64, 96, 128, 160, 192, 256, 320))],
        run=lambda p, a: _av_tuple(av2("audio_bitrate")(_read(p), _ext(p), a.kbps))),
    Cmd("audio", "merge", "join audio files end to end", inputs="many",
        args=[Arg("--format", default="mp3", choices=_AUDIO_FMTS, short="-f")],
        run=lambda ps, a: Result(tools.merge_audio_files([(_ext(p), _read(p)) for p in ps], a.format), a.format,
                                 name="merged")),
    Cmd("audio", "split", "cut into parts", suffix="parts",
        args=[Arg("--every", help="part length, like 5:00"), Arg("--parts", int, help="number of equal parts")],
        run=_audio_split),
    Cmd("audio", "info", "duration, codec, bitrate, tags", run=_av_media_info),

    # Video
    Cmd("video", "convert", "change container/codec",
        args=[Arg("--format", required=True, choices=_VIDEO_FMTS, short="-f")],
        run=lambda p, a: Result(tools.convert_video(_read(p), _ext(p), a.format), a.format)),
    Cmd("video", "trim", "keep a section (no re-encode)", suffix="trimmed", args=[_START, _END],
        run=lambda p, a: Result(tools.trim_video(_read(p), _ext(p), _ts(a.start), _ts(a.end)), _ext(p)),
        example="sdexe video trim talk.mp4 --start 10:00 --end 12:30"),
    Cmd("video", "compress", "smaller H.264 MP4", suffix="compressed",
        args=[Arg("--quality", default="medium", choices=("high", "medium", "low"))],
        run=lambda p, a: Result(tools.compress_video(_read(p), _ext(p), a.quality), "mp4")),
    Cmd("video", "audio", "extract the soundtrack",
        args=[Arg("--format", default="mp3", choices=_AUDIO_FMTS, short="-f")],
        run=lambda p, a: Result(tools.extract_audio(_read(p), _ext(p), a.format), a.format)),
    Cmd("video", "gif", "animated GIF",
        args=[Arg("--fps", int, 10), Arg("--width", int, 480)],
        run=lambda p, a: Result(tools.video_to_gif(_read(p), _ext(p), a.fps, a.width), "gif")),
    Cmd("video", "resize", "change resolution", suffix="resized",
        args=[Arg("--width", int, required=True), Arg("--height", int, -1, help="-1 keeps the aspect ratio")],
        run=lambda p, a: Result(tools.resize_video(_read(p), _ext(p), a.width, a.height), _ext(p))),
    Cmd("video", "rotate", "rotate clockwise", suffix="rotated",
        args=[Arg("--angle", int, 90, choices=(90, 180, 270))],
        run=lambda p, a: Result(tools.rotate_video(_read(p), _ext(p), a.angle), _ext(p))),
    Cmd("video", "crop", "cut out a rectangle", suffix="cropped",
        args=[Arg("--width", int, required=True), Arg("--height", int, required=True), Arg("--x", int, 0),
              Arg("--y", int, 0)],
        run=lambda p, a: Result(tools.crop_video(_read(p), _ext(p), a.width, a.height, a.x, a.y), _ext(p))),
    Cmd("video", "mute", "remove the audio", suffix="muted",
        run=lambda p, a: Result(tools.mute_video(_read(p), _ext(p)), _ext(p))),
    Cmd("video", "speed", "faster or slower", suffix="speed",
        args=[Arg("--speed", float, required=True, help="like 2 or 0.5"),
              Arg("--no-pitch-fix", bool, help="let the audio pitch shift with the speed")],
        run=lambda p, a: _av_tuple(av2("video_speed")(_read(p), _ext(p), a.speed, not a.no_pitch_fix))),
    Cmd("video", "reverse", "play backwards", suffix="reversed",
        run=lambda p, a: Result(tools.reverse_video(_read(p), _ext(p)), _ext(p))),
    Cmd("video", "loop", "repeat N times", suffix="looped", args=[Arg("--count", int, 2)],
        run=lambda p, a: Result(tools.loop_video(_read(p), _ext(p), a.count), _ext(p))),
    Cmd("video", "stabilize", "reduce camera shake", suffix="stable",
        args=[Arg("--strength", default="medium", choices=("low", "medium", "high"))],
        run=lambda p, a: _av_tuple(av2("stabilize_video")(_read(p), _ext(p), a.strength))),
    Cmd("video", "merge", "join clips end to end (sizes are matched)", inputs="many", run=_video_merge),
    Cmd("video", "frames", "save still frames", suffix="frames",
        args=[Arg("--at", help="one frame at this time, like 1:05"), Arg("--every", help="one frame every N, like 10s"),
              Arg("--count", int, help="N frames spread evenly"),
              Arg("--format", default="png", choices=("png", "jpg"), short="-f")],
        run=_video_frames, example="sdexe video frames clip.mp4 --every 5s"),
    Cmd("video", "add-audio", "replace the soundtrack", inputs="pair", inputs_help="VIDEO AUDIO", suffix="dubbed",
        run=lambda ps, a: Result(tools.add_audio_to_video(_read(ps[0]), _ext(ps[0]), _read(ps[1]), _ext(ps[1])),
                                 _ext(ps[0]))),
    Cmd("video", "subtitles", "burn an .srt into the picture", inputs="pair", inputs_help="VIDEO SRT",
        suffix="subtitled",
        run=lambda ps, a: Result(tools.burn_subtitles(_read(ps[0]), _ext(ps[0]), _read(ps[1])), _ext(ps[0]))),
    Cmd("video", "watermark", "overlay an image (logo)", inputs="pair", inputs_help="VIDEO IMAGE",
        suffix="watermarked",
        args=[Arg("--position", default="bottom-right", choices=_CORNERS + ("center",)),
              Arg("--scale", float, 15, help="width as a % of the video"), Arg("--opacity", float, 100)],
        run=lambda ps, a: _av_tuple(av2("video_watermark")(_read(ps[0]), _ext(ps[0]), _read(ps[1]), _ext(ps[1]),
                                                           a.position, a.scale, a.opacity))),
    Cmd("video", "info", "duration, resolution, codecs", run=_av_media_info),

    # Data conversion
    Cmd("convert", "", "convert data and documents by extension", run=_convert,
        args=[Arg("--format", required=True, short="-f",
                  help="target: " + ", ".join(_CONVERT_TARGETS)),
              Arg("--sheet", help="xlsx → csv: one sheet by name (default: all)")],
        example="sdexe convert data.csv -f json"),

    # Files
    Cmd("file", "hash", "MD5, SHA-1, SHA-256, SHA-512",
        run=lambda p, a: Result(obj=_hash(p))),
    Cmd("file", "zip", "pack files into a .zip", inputs="many",
        run=lambda ps, a: Result(tools.create_zip([(p.name, _read(p)) for p in ps]), "zip", name="archive")),
    Cmd("file", "unzip", "extract .zip, .7z, .tar, .tar.gz, .rar", suffix="",
        run=lambda p, a: Result(files=conv2("extract_archive")(_read(p), p.name))),
    Cmd("file", "split", "cut a large file into parts", suffix="parts",
        args=[Arg("--size", float, 100, help="part size in MB")],
        run=lambda p, a: Result(files=conv2("split_file")(_read(p), p.name, a.size))),
]

GROUPS = {
    "pdf": "merge, split, compress, extract text, OCR, rotate, watermark, encrypt",
    "image": "resize, compress, convert (incl. HEIC), crop, watermark, QR codes",
    "audio": "convert, trim, speed, normalize, fade, merge, split",
    "video": "convert, trim, compress, extract audio, GIF, resize, merge, frames",
    "convert": "data and documents: csv, json, yaml, xml, toml, md, html, xlsx, office → pdf",
    "file": "hash, zip, unzip, split",
}

_BY_NAME = {(c.group, c.name): c for c in COMMANDS}


# ── Parsing and help ──

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message[0].upper() + message[1:] + ".")


def build_parser(cmd: Cmd) -> argparse.ArgumentParser:
    p = _Parser(prog=f"sdexe {cmd.full}", add_help=False)
    if cmd.inputs == "none":
        p.add_argument(cmd.text_arg)
    else:
        p.add_argument("files", nargs="*")
    for arg in cmd.args:
        flags = [arg.flag] + ([arg.short] if arg.short else [])
        if arg.type is bool:
            p.add_argument(*flags, dest=arg.dest, action="store_true")
        else:
            p.add_argument(*flags, dest=arg.dest, type=arg.type, default=arg.default,
                           required=arg.required, choices=arg.choices)
    p.add_argument("-o", "--output")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    return p


def _arg_line(arg: Arg) -> tuple[str, str]:
    left = ", ".join(([arg.short] if arg.short else []) + [arg.flag])
    if arg.type is not bool:
        left += " " + ("|".join(map(str, arg.choices)) if arg.choices and len(arg.choices) <= 5
                       else arg.dest.upper())
    bits = [arg.help] if arg.help else []
    if arg.choices and len(arg.choices) > 5:
        bits.append("one of " + ", ".join(map(str, arg.choices)))
    if arg.required:
        bits.append("[bold]required[/bold]")
    elif arg.default not in (None, "", False) and arg.type is not bool:
        bits.append(f"[dim]default {arg.default}[/dim]")
    return left, "  ".join(bits)


def command_help(cmd: Cmd) -> str:
    out = [f"[bold]sdexe {cmd.full}[/bold] [dim]· {cmd.summary}[/dim]", "", "[bold]Usage[/bold]",
           f"  sdexe {cmd.full} [cyan]{cmd.inputs_help}[/cyan] \\[options]", ""]
    if cmd.inputs == "each":
        out += ["  Several files are processed one by one.", ""]
    rows = [_arg_line(a) for a in cmd.args]
    out_help = ("text goes to stdout; -o FILE saves it" if _is_text(cmd)
                else "folder, or a file name for a single input (default: current folder)")
    rows += [("-o, --output PATH", out_help), ("--json", "one JSON result document on stdout"),
             ("--quiet", "no progress output")]
    width = min(max(len(r[0]) for r in rows), 26) + 3
    out.append("[bold]Options[/bold]")
    for left, right in rows:
        if len(left) + 3 > width:
            out.append(f"  {left}")
            out.append(f"  {'':{width}}{right}")
        else:
            out.append(f"  {left.ljust(width)}{right}")
    if cmd.example:
        out += ["", "[bold]Example[/bold]", f"  {cmd.example}"]
    return "\n".join(out)


def _is_text(cmd: Cmd) -> bool:
    return cmd.name in ("text", "ocr", "ascii")


def group_help(group: str) -> str:
    cmds = [c for c in COMMANDS if c.group == group]
    width = max(len(c.name) for c in cmds) + 3
    out = [f"[bold]sdexe {group}[/bold] [dim]· {GROUPS[group]}[/dim]", "", "[bold]Commands[/bold]"]
    out += [f"  [cyan]{c.name.ljust(width)}[/cyan]{c.summary}" for c in cmds]
    out += ["", f"Run [cyan]sdexe {group} <command> --help[/cyan] for options."]
    return "\n".join(out)


def _print(markup: str):
    from rich.console import Console
    Console(highlight=False).print(markup, soft_wrap=True)


# ── Running ──

class Runner:
    def __init__(self, cmd: Cmd, args):
        self.cmd = cmd
        self.args = args
        self.results = []
        self.claimed = set()
        self.stdout_tty = sys.stdout.isatty()
        self.console = None
        if sys.stderr.isatty() and not args.quiet:
            from rich.console import Console
            self.console = Console(stderr=True, highlight=False)

    def _dest(self, stem: str, ext: str, sources: list, n_outputs: int) -> Path:
        out = self.args.output
        if out:
            o = Path(out).expanduser()
            if o.suffix and not o.is_dir():
                if n_outputs > 1:
                    raise UsageError(f"-o {o.name} names one file, but there are {n_outputs} inputs. Pass a folder.")
                o.parent.mkdir(parents=True, exist_ok=True)
                return o.resolve()
            folder = o
        else:
            folder = Path.cwd()
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{stem}.{ext}"
        n = 2
        inputs = {Path(s).resolve() for s in sources}
        while dest.exists() or dest in self.claimed or dest.resolve() in inputs:
            dest = folder / f"{stem} ({n}).{ext}"
            n += 1
        self.claimed.add(dest)
        return dest.resolve()

    def _folder(self, stem: str) -> Path:
        base = Path(self.args.output).expanduser() if self.args.output else Path.cwd() / stem
        folder, n = base, 2
        if not self.args.output:
            while folder.exists():
                folder = base.with_name(f"{base.name} ({n})")
                n += 1
        folder.mkdir(parents=True, exist_ok=True)
        return folder.resolve()

    def _save(self, res: Result, sources: list, n_outputs: int) -> dict:
        src = Path(sources[0]) if sources else None
        stem = res.name or (f"{src.stem}-{self.cmd.suffix}" if self.cmd.suffix else (src.stem if src else "output"))
        if res.files is not None:
            if not res.files:
                raise ValueError("Nothing to save: the result was empty.")
            folder = self._folder(stem)
            paths = []
            for name, data in res.files:
                safe = Path(name.replace("\\", "/")).parts
                target = folder.joinpath(*[p for p in safe if p not in ("..", "/")])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                paths.append(str(target))
            return {"folder": str(folder), "outputs": [{"path": p, "size_bytes": Path(p).stat().st_size}
                                                        for p in paths]}
        if res.data is not None:
            dest = self._dest(stem, res.ext or (src.suffix.lstrip(".") if src else "bin"), sources, n_outputs)
            tmp = dest.with_name(f".{dest.name}.sdexe-tmp")
            tmp.write_bytes(res.data)
            os.replace(tmp, dest)
            return {"outputs": [{"path": str(dest), "size_bytes": len(res.data)}]}
        if res.text is not None:
            if self.args.output:
                dest = Path(self.args.output).expanduser()
                if dest.is_dir():
                    dest = dest / f"{stem}.txt"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(res.text, encoding="utf-8")
                return {"outputs": [{"path": str(dest.resolve()), "size_bytes": dest.stat().st_size}]}
            return {"text": res.text}
        return {"data": res.obj}

    def _one(self, sources: list, call, n_outputs: int):
        label = ", ".join(Path(s).name for s in sources) or self.cmd.full
        entry = {"inputs": [str(Path(s).resolve()) for s in sources], "ok": False}
        try:
            if self.console:
                with self.console.status(f" [dim]{self.cmd.full}[/dim] {_escape(label)}", spinner="dots"):
                    res = call()
                    saved = self._save(res, sources, n_outputs)
            else:
                res = call()
                saved = self._save(res, sources, n_outputs)
            entry.update(saved, ok=True)
        except UsageError:
            raise
        except Exception as e:  # noqa: BLE001 - one bad file must not end the batch
            entry["error"] = _friendly(e)
        self.results.append(entry)
        self._report(entry, label, sources)

    def _report(self, entry, label, sources):
        if not entry["ok"]:
            msg = f"✗ {label}: {entry['error']}"
            if self.console:
                self.console.print(f" [red]✗[/red] {_escape(label)}  [red]{_escape(entry['error'])}[/red]")
            elif not self.args.json or not sys.stderr.isatty():
                print(msg, file=sys.stderr)
            return
        if self.args.json:
            return
        if "text" in entry:
            sys.stdout.write(entry["text"] if entry["text"].endswith("\n") else entry["text"] + "\n")
            return
        if "data" in entry:
            self._print_data(entry["data"], label)
            return
        outs = entry["outputs"]
        if not self.stdout_tty:
            for o in outs:
                print(o["path"], flush=True)
        if self.console:
            before = sum(Path(s).stat().st_size for s in sources) if sources else 0
            if "folder" in entry:
                where = _short(entry["folder"])
                self.console.print(f" [green]✓[/green] {_escape(label)} [dim]→[/dim] {_escape(where)}/ "
                                   f"[dim]({len(outs)} files)[/dim]")
            else:
                o = outs[0]
                sizes = f"{fmt_size(before)} → {fmt_size(o['size_bytes'])}" if before else fmt_size(o["size_bytes"])
                self.console.print(f" [green]✓[/green] {_escape(label)} [dim]→[/dim] "
                                   f"[link=file://{o['path']}]{_escape(_short(o['path']))}[/link]  [dim]{sizes}[/dim]")

    def _print_data(self, data, label):
        if not self.stdout_tty:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
            return
        from rich.console import Console
        c = Console(highlight=False)
        c.print(f" [bold]{_escape(label)}[/bold]")
        width = max((len(str(k)) for k in data), default=0) + 2
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False, default=str)
            c.print(f"   [dim]{str(k).ljust(width)}[/dim]{_escape(v)}", overflow="ellipsis", no_wrap=True)
        c.print()

    def run(self, files: list) -> int:
        cmd, a = self.cmd, self.args
        if cmd.inputs == "none":
            self._one([], lambda: cmd.run(None, a), 1)
        elif cmd.inputs == "each":
            for f in files:
                self._one([f], lambda f=f: cmd.run(Path(f), a), len(files))
        else:
            self._one(files, lambda: cmd.run([Path(f) for f in files], a), 1)

        if a.json:
            print(json.dumps({"ok": all(r["ok"] for r in self.results), "command": cmd.full,
                              "results": self.results}, indent=2, ensure_ascii=False, default=str))
        return 0 if all(r["ok"] for r in self.results) else 1


def _short(path: str) -> str:
    try:
        rel = Path(path).relative_to(Path.cwd())
        return f"./{rel}"
    except ValueError:
        return path.replace(str(Path.home()), "~", 1)


def _friendly(e: Exception) -> str:
    name = type(e).__name__
    msg = str(e).strip() or name
    if name == "FFmpegMissingError":
        return "ffmpeg is required. Install it (macOS: brew install ffmpeg) or run `sdexe` once."
    if name in ("PdfReadError", "EmptyFileError"):
        return f"Could not read this PDF: {msg}"
    if name == "FileNotDecryptedError":
        return "This PDF is password protected. Run `sdexe pdf decrypt FILE --password ...` first."
    if name == "UnidentifiedImageError":
        return "Not an image this tool can read."
    if isinstance(e, UnicodeDecodeError):
        return "This file is not UTF-8 text."
    return msg.splitlines()[0][:300]


def tools_main(argv) -> int:
    group = argv[0]
    rest = argv[1:]
    single = _BY_NAME.get((group, ""))
    if single:
        cmd = single
    else:
        if not rest or rest[0] in ("-h", "--help", "help"):
            _print(group_help(group))
            return 0 if rest else 2
        cmd = _BY_NAME.get((group, rest[0]))
        if not cmd:
            import difflib
            names = [c.name for c in COMMANDS if c.group == group]
            guess = difflib.get_close_matches(rest[0], names, n=1)
            hint = f" Did you mean `sdexe {group} {guess[0]}`?" if guess else f" Run `sdexe {group} --help`."
            print(f"sdexe {group}: unknown command '{rest[0]}'.{hint}", file=sys.stderr)
            return 2
        rest = rest[1:]

    try:
        args = build_parser(cmd).parse_args(rest)
        if args.help:
            _print(command_help(cmd))
            return 0
        files = [] if cmd.inputs == "none" else args.files
        if cmd.inputs != "none":
            if not files:
                raise UsageError(f"No input files. Usage: sdexe {cmd.full} {cmd.inputs_help}")
            missing = [f for f in files if not Path(f).expanduser().is_file()]
            if missing:
                raise UsageError(f"Not found: {missing[0]}")
            files = [str(Path(f).expanduser()) for f in files]
            if cmd.inputs == "pair" and len(files) != 2:
                raise UsageError(f"Needs exactly two files: {cmd.inputs_help}.")
            if cmd.inputs == "many" and len(files) < (1 if cmd.name in ("from-images", "zip", "collage") else 2):
                raise UsageError(f"Needs at least two files to {cmd.name}.")
        return Runner(cmd, args).run(files)
    except UsageError as e:
        print(f"sdexe {cmd.full}: {e}", file=sys.stderr)
        return 2
