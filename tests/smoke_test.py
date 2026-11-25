#!/usr/bin/env python3
"""End-to-end smoke test for every sdexe tool route.

Runs the Flask app via its test client (no live server, no network) and exercises
each tool endpoint with a tiny in-memory fixture, asserting it does not 5xx and
behaves sanely. A/V routes are skipped with a clear note when ffmpeg is absent.

Usage:
    python tests/smoke_test.py            # full run, exits non-zero on any FAIL
    python tests/smoke_test.py --quiet    # only the summary + failures

Pass criteria:
    - tool route given good input        -> 200 with a non-empty body  (PASS)
    - tool route that gracefully 4xx's   -> handled, never a crash      (PASS)
    - validation route given bad input   -> 4xx as expected             (PASS)
    - any 5xx (unhandled crash)          ->                             (FAIL)
    - a 4xx that only the catch-all ValueError/KeyError/TypeError handler
      produced (so possibly a bug in sdexe, not bad input)              (FAIL)
    - an /api/ route no check ever reached                              (FAIL)

Nothing here touches ~/.config/sdexe, the network, pip, brew or the desktop:
config and history go to a temp directory, and the routes that update, install
or open things run against stubs.
"""

import atexit
import io
import json
import logging
import os
import re
import shutil
import sys
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

# Allow running from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sdexe.app as webapp         # noqa: E402
from sdexe.app import app          # noqa: E402
from sdexe import tools            # noqa: E402
from flask import request, request_finished  # noqa: E402
from pypdf import PdfWriter        # noqa: E402
from PIL import Image              # noqa: E402

QUIET = "--quiet" in sys.argv

# The user's real settings and history are never read or written.
STATE = Path(tempfile.mkdtemp(prefix="sdexe_smoke_"))
atexit.register(shutil.rmtree, STATE, ignore_errors=True)
webapp.CONFIG_DIR = STATE / "config"
webapp.CONFIG_FILE = webapp.CONFIG_DIR / "config.json"
webapp.HISTORY_FILE = webapp.CONFIG_DIR / "history.json"

client = app.test_client()
results = []  # (group, name, outcome, detail)

# Every rule a request matched, to report the ones no check reached.
_rules_hit = set()


def _note_rule(sender, response, **_):
    if request.url_rule is not None and response.status_code < 500:
        _rules_hit.add(request.url_rule.rule)


request_finished.connect(_note_rule, app)


class _Fallbacks(logging.Handler):
    """Collects what the app logs. The catch-all handlers answer a ValueError,
    KeyError or TypeError with a 400 and an unhandled exception with a 500;
    both log, and a check during which either fired fails unless it said the
    catch-all was the point (expect="malformed")."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def drain(self):
        out, self.records = self.records, []
        return out


_fallbacks = _Fallbacks()
_log = logging.getLogger("sdexe")
_log.addHandler(_fallbacks)
_log.propagate = False  # collected above; keep expected errors off the terminal
app.logger.addHandler(logging.NullHandler())
app.logger.propagate = False


def _caught_by_fallback():
    return [r.getMessage() for r in _fallbacks.drain()
            if r.getMessage().startswith(("unhandled ",))]


# ── result recording ──

def _err(resp):
    try:
        j = resp.get_json(silent=True)
        if isinstance(j, dict) and "error" in j:
            return str(j["error"])[:140]
    except Exception:
        pass
    return resp.data[:140].decode("utf-8", "replace")


def check(group, name, resp, expect="ok"):
    """expect: 'ok' (want 200), 'ok_or_400' (200 or graceful 4xx), 'reject' (want 4xx),
    'malformed' (want 4xx, and the catch-all handler producing it is fine)."""
    code = resp.status_code
    caught = _caught_by_fallback()
    if caught and expect != "malformed":
        results.append((group, name, "FAIL", f"{code} came from the catch-all handler: {caught[0]}"))
        return
    if expect == "malformed":
        out = "PASS" if 400 <= code < 500 and caught else "FAIL"
        results.append((group, name, out, f"{code} (wanted a logged 4xx; logged: {bool(caught)})"))
        return
    if expect == "reject":
        out = "PASS" if 400 <= code < 500 else "FAIL"
        results.append((group, name, out, f"{code} (wanted 4xx) {_err(resp) if out=='FAIL' else ''}".strip()))
        return
    if code == 200:
        results.append((group, name, "PASS", f"200, {len(resp.data)}B"))
    elif 400 <= code < 500 and expect == "ok_or_400":
        results.append((group, name, "PASS", f"{code} handled: {_err(resp)}"))
    else:
        results.append((group, name, "FAIL", f"{code}: {_err(resp)}"))


def skip(group, name, reason):
    results.append((group, name, "SKIP", reason))


def expect_true(group, name, ok, detail=""):
    """A plain assertion, for regressions that are about state rather than a status code."""
    caught = _caught_by_fallback()
    if caught:
        ok, detail = False, f"catch-all handler fired: {caught[0]}"
    results.append((group, name, "PASS" if ok else "FAIL", str(detail)[:160]))


# ── fixtures ──

def make_pdf(pages=3):
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def make_png(w=96, h=96, color=(120, 80, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def fp(data, name):
    """A fresh file tuple for a multipart upload (stream is consumed per request)."""
    return (io.BytesIO(data), name)


def _ffmpeg_make(args, suffix):
    path = tools.ffmpeg_path()
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    cmd = [path, "-y"] + args + [tmp.name]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        Path(tmp.name).unlink(missing_ok=True)
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
    data = Path(tmp.name).read_bytes()
    Path(tmp.name).unlink(missing_ok=True)
    return data


PDF = make_pdf()
PNG = make_png()
SRT = b"1\n00:00:00,000 --> 00:00:00,400\nhello\n"


# ── PDF ──

def test_pdf():
    g = "pdf"
    check(g, "merge", client.post("/api/pdf/merge", data={"files": [fp(PDF, "a.pdf"), fp(PDF, "b.pdf")]}, content_type="multipart/form-data"))
    check(g, "merge (reject <2)", client.post("/api/pdf/merge", data={"files": [fp(PDF, "a.pdf")]}, content_type="multipart/form-data"), expect="reject")
    check(g, "split", client.post("/api/pdf/split", data={"file": fp(PDF, "d.pdf"), "ranges": "1-2"}, content_type="multipart/form-data"))
    check(g, "page-count", client.post("/api/pdf/page-count", data={"file": fp(PDF, "d.pdf")}, content_type="multipart/form-data"))
    check(g, "compress", client.post("/api/pdf/compress", data={"file": fp(PDF, "d.pdf")}, content_type="multipart/form-data"))
    check(g, "to-text", client.post("/api/pdf/to-text", data={"file": fp(PDF, "d.pdf")}, content_type="multipart/form-data"), expect="ok_or_400")
    check(g, "add-password", client.post("/api/pdf/add-password", data={"file": fp(PDF, "d.pdf"), "password": "secret"}, content_type="multipart/form-data"))
    check(g, "rotate", client.post("/api/pdf/rotate", data={"file": fp(PDF, "d.pdf"), "angle": "90", "pages": "all"}, content_type="multipart/form-data"))
    check(g, "reorder", client.post("/api/pdf/reorder", data={"file": fp(PDF, "d.pdf"), "order": "3,1,2"}, content_type="multipart/form-data"))
    check(g, "delete-pages", client.post("/api/pdf/delete-pages", data={"file": fp(PDF, "d.pdf"), "pages": "2"}, content_type="multipart/form-data"))
    check(g, "metadata-get", client.post("/api/pdf/metadata", data={"file": fp(PDF, "d.pdf"), "action": "get"}, content_type="multipart/form-data"))
    check(g, "metadata-set", client.post("/api/pdf/metadata", data={"file": fp(PDF, "d.pdf"), "title": "T", "author": "A"}, content_type="multipart/form-data"))
    check(g, "extract-images", client.post("/api/pdf/extract-images", data={"file": fp(PDF, "d.pdf")}, content_type="multipart/form-data"), expect="ok_or_400")
    check(g, "number-pages", client.post("/api/pdf/number-pages", data={"file": fp(PDF, "d.pdf"), "start": "1", "position": "bottom-center"}, content_type="multipart/form-data"))
    check(g, "watermark", client.post("/api/pdf/watermark", data={"file": fp(PDF, "d.pdf"), "text": "DRAFT"}, content_type="multipart/form-data"))
    check(g, "images-to-pdf", client.post("/api/pdf/images-to-pdf", data={"files": [fp(PNG, "a.png"), fp(PNG, "b.png")]}, content_type="multipart/form-data"))
    # round-trip: add then remove password
    add = client.post("/api/pdf/add-password", data={"file": fp(PDF, "d.pdf"), "password": "secret"}, content_type="multipart/form-data")
    if add.status_code == 200:
        check(g, "remove-password", client.post("/api/pdf/remove-password", data={"file": fp(add.data, "p.pdf"), "password": "secret"}, content_type="multipart/form-data"))
    else:
        skip(g, "remove-password", "add-password did not produce a file")


# ── Images ──

def test_images():
    g = "images"
    check(g, "resize", client.post("/api/images/resize", data={"file": fp(PNG, "i.png"), "mode": "dimensions", "width": "48", "height": "48"}, content_type="multipart/form-data"))
    check(g, "compress", client.post("/api/images/compress", data={"files": [fp(PNG, "i.png")], "quality": "medium"}, content_type="multipart/form-data"))
    check(g, "convert", client.post("/api/images/convert", data={"files": [fp(PNG, "i.png")], "format": "webp"}, content_type="multipart/form-data"))
    check(g, "crop", client.post("/api/images/crop", data={"file": fp(PNG, "i.png"), "left": "0", "top": "0", "right": "48", "bottom": "48"}, content_type="multipart/form-data"))
    check(g, "rotate", client.post("/api/images/rotate", data={"file": fp(PNG, "i.png"), "angle": "90"}, content_type="multipart/form-data"))
    check(g, "strip-exif", client.post("/api/images/strip-exif", data={"file": fp(PNG, "i.png")}, content_type="multipart/form-data"))
    check(g, "flip", client.post("/api/images/flip", data={"file": fp(PNG, "i.png"), "direction": "horizontal"}, content_type="multipart/form-data"))
    check(g, "grayscale", client.post("/api/images/grayscale", data={"file": fp(PNG, "i.png")}, content_type="multipart/form-data"))
    check(g, "blur", client.post("/api/images/blur", data={"file": fp(PNG, "i.png"), "radius": "3"}, content_type="multipart/form-data"))
    check(g, "to-ico", client.post("/api/images/to-ico", data={"file": fp(PNG, "i.png"), "sizes": "16,32,64"}, content_type="multipart/form-data"))
    check(g, "watermark", client.post("/api/images/watermark", data={"file": fp(PNG, "i.png"), "text": "X"}, content_type="multipart/form-data"))
    check(g, "qr-generate", client.post("/api/images/qr-generate", json={"text": "hello"}))
    check(g, "placeholder", client.post("/api/images/placeholder", json={"width": 120, "height": 80}))


# ── Convert ──

def test_convert():
    g = "convert"
    check(g, "md-to-html", client.post("/api/convert/md-to-html", data={"text": "# Hi\n\n- a\n- b"}))
    check(g, "md-preview", client.post("/api/convert/md-preview", data={"text": "# Hi"}))
    check(g, "csv-to-json", client.post("/api/convert/csv-to-json", data={"file": fp(b"a,b\n1,2\n3,4\n", "d.csv")}, content_type="multipart/form-data"))
    check(g, "json-to-csv", client.post("/api/convert/json-to-csv", data={"file": fp(b'[{"a":1,"b":2}]', "d.json")}, content_type="multipart/form-data"))
    check(g, "yaml-to-json", client.post("/api/convert/yaml-to-json", data={"file": fp(b"a: 1\nb: 2\n", "d.yaml")}, content_type="multipart/form-data"))
    check(g, "json-to-yaml", client.post("/api/convert/json-to-yaml", data={"file": fp(b'{"a":1,"b":2}', "d.json")}, content_type="multipart/form-data"))
    check(g, "csv-to-tsv", client.post("/api/convert/csv-to-tsv", data={"file": fp(b"a,b\n1,2\n", "d.csv")}, content_type="multipart/form-data"))
    check(g, "tsv-to-csv", client.post("/api/convert/tsv-to-csv", data={"file": fp(b"a\tb\n1\t2\n", "d.tsv")}, content_type="multipart/form-data"))
    check(g, "xml-to-json", client.post("/api/convert/xml-to-json", data={"file": fp(b"<r><a>1</a><b>2</b></r>", "d.xml")}, content_type="multipart/form-data"))
    check(g, "zip", client.post("/api/convert/zip", data={"files": [fp(b"hello", "a.txt"), fp(b"world", "b.txt")]}, content_type="multipart/form-data"))
    # round-trip: zip then unzip
    z = client.post("/api/convert/zip", data={"files": [fp(b"hello", "a.txt")]}, content_type="multipart/form-data")
    if z.status_code == 200:
        check(g, "unzip", client.post("/api/convert/unzip", data={"file": fp(z.data, "a.zip")}, content_type="multipart/form-data"))
    else:
        skip(g, "unzip", "zip did not produce a file")


# ── A/V (skipped when ffmpeg absent) ──

def _av_without_files(g, names, reason):
    """No ffmpeg (or no fixtures): the tools can't run, but each route is still
    reached, and must refuse a request with no file rather than crash."""
    for name in names:
        skip(g, name, reason)
        check(g, f"{name} (reject no file)", client.post(f"/api/av/{name}", data={}, content_type="multipart/form-data"), expect="reject")


def test_av():
    g = "av"
    names = ["convert-audio", "trim-audio", "audio-speed", "extract-audio", "trim-video",
             "compress-video", "convert-video", "merge-audio", "normalize-volume", "video-to-gif",
             "reverse-audio", "change-pitch", "audio-equalizer", "audio-fade", "crop-video",
             "rotate-video", "resize-video", "reverse-video", "loop-video", "mute-video",
             "add-audio", "burn-subtitles"]
    if not tools.ffmpeg_available():
        _av_without_files(g, names, "ffmpeg not available")
        return
    try:
        audio = _ffmpeg_make(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:a", "libmp3lame"], ".mp3")
        video = _ffmpeg_make(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15", "-f", "lavfi",
                              "-i", "sine=frequency=440:duration=0.5", "-t", "0.5", "-pix_fmt", "yuv420p",
                              "-c:v", "libx264", "-c:a", "aac"], ".mp4")
    except Exception as e:
        _av_without_files(g, names, f"fixture generation failed: {e}")
        return

    mp = "multipart/form-data"
    check(g, "convert-audio", client.post("/api/av/convert-audio", data={"file": fp(audio, "a.mp3"), "format": "wav"}, content_type=mp))
    check(g, "trim-audio", client.post("/api/av/trim-audio", data={"file": fp(audio, "a.mp3"), "start": "0", "end": "0.3"}, content_type=mp))
    check(g, "audio-speed", client.post("/api/av/audio-speed", data={"file": fp(audio, "a.mp3"), "speed": "1.5"}, content_type=mp))
    check(g, "extract-audio", client.post("/api/av/extract-audio", data={"file": fp(video, "v.mp4"), "format": "mp3"}, content_type=mp))
    check(g, "trim-video", client.post("/api/av/trim-video", data={"file": fp(video, "v.mp4"), "start": "0", "end": "0.3"}, content_type=mp))
    check(g, "compress-video", client.post("/api/av/compress-video", data={"file": fp(video, "v.mp4"), "quality": "medium"}, content_type=mp))
    check(g, "convert-video", client.post("/api/av/convert-video", data={"file": fp(video, "v.mp4"), "format": "mov"}, content_type=mp))
    check(g, "merge-audio", client.post("/api/av/merge-audio", data={"files": [fp(audio, "a.mp3"), fp(audio, "b.mp3")], "format": "mp3"}, content_type=mp))
    check(g, "normalize-volume", client.post("/api/av/normalize-volume", data={"file": fp(audio, "a.mp3")}, content_type=mp))
    check(g, "video-to-gif", client.post("/api/av/video-to-gif", data={"file": fp(video, "v.mp4"), "fps": "5", "width": "120"}, content_type=mp))
    check(g, "reverse-audio", client.post("/api/av/reverse-audio", data={"file": fp(audio, "a.mp3")}, content_type=mp))
    check(g, "change-pitch", client.post("/api/av/change-pitch", data={"file": fp(audio, "a.mp3"), "semitones": "2"}, content_type=mp))
    check(g, "audio-equalizer", client.post("/api/av/audio-equalizer", data={"file": fp(audio, "a.mp3"), "bass": "2", "mid": "0", "treble": "1"}, content_type=mp))
    check(g, "audio-fade", client.post("/api/av/audio-fade", data={"file": fp(audio, "a.mp3"), "fade_in": "0.1", "fade_out": "0.1", "duration": "0.5"}, content_type=mp))
    check(g, "crop-video", client.post("/api/av/crop-video", data={"file": fp(video, "v.mp4"), "width": "160", "height": "120", "x": "0", "y": "0"}, content_type=mp))
    check(g, "rotate-video", client.post("/api/av/rotate-video", data={"file": fp(video, "v.mp4"), "angle": "90"}, content_type=mp))
    check(g, "resize-video", client.post("/api/av/resize-video", data={"file": fp(video, "v.mp4"), "width": "160"}, content_type=mp))
    check(g, "reverse-video", client.post("/api/av/reverse-video", data={"file": fp(video, "v.mp4")}, content_type=mp))
    check(g, "loop-video", client.post("/api/av/loop-video", data={"file": fp(video, "v.mp4"), "count": "2"}, content_type=mp))
    check(g, "mute-video", client.post("/api/av/mute-video", data={"file": fp(video, "v.mp4")}, content_type=mp))
    check(g, "add-audio", client.post("/api/av/add-audio", data={"video": fp(video, "v.mp4"), "audio": fp(audio, "a.mp3")}, content_type=mp))
    check(g, "burn-subtitles", client.post("/api/av/burn-subtitles", data={"video": fp(video, "v.mp4"), "subtitles": fp(SRT, "s.srt")}, content_type=mp))


# ── Media (validation only — no network) ──

def test_media():
    g = "media"
    check(g, "info (reject empty)", client.post("/api/info", json={}), expect="reject")
    check(g, "info (reject non-http)", client.post("/api/info", json={"url": "ftp://x"}), expect="reject")
    check(g, "download (reject empty)", client.post("/api/download", json={}), expect="reject")
    check(g, "deps probe", client.get("/api/deps"))


# ── pages render ──

def test_pages():
    g = "pages"
    for path in ["/", "/media", "/pdf", "/images", "/convert", "/av", "/text", "/transcribe", "/about", "/settings"]:
        resp = client.get(path)
        check(g, f"GET {path}", resp)
        # A font or script from another site would tell it sdexe is open.
        outside = re.findall(rb'<(?:link|script|img)\b[^>]*(?:href|src)="(?:https?:)?//[^"]*', resp.data)
        expect_true(g, f"{path} loads nothing from outside", not outside, outside)
    css = client.get("/static/style.css").get_data(as_text=True)
    urls = re.findall(r'url\("?([^")]+)"?\)', css)
    fonts = [u for u in urls if u.endswith(".woff2")]
    expect_true(g, "style.css fonts are bundled", len(fonts) == 6 and not re.search(r"url\(\"?(?:https?:)?//", css), fonts)
    for u in fonts:
        check(g, f"GET {u}", client.get(f"/static/{u}"))


# ── More tools (the routes_*2 blueprints) ──

MP = "multipart/form-data"


def test_pdf2():
    g = "pdf"
    check(g, "to-images", client.post("/api/pdf/to-images", data={"file": fp(PDF, "d.pdf"), "format": "png", "dpi": "72"}, content_type=MP))
    check(g, "to-images (reject dpi)", client.post("/api/pdf/to-images", data={"file": fp(PDF, "d.pdf"), "dpi": "7"}, content_type=MP), expect="reject")
    check(g, "stamp", client.post("/api/pdf/stamp", data={"file": fp(PDF, "d.pdf"), "image": fp(PNG, "s.png")}, content_type=MP))
    check(g, "page-size", client.post("/api/pdf/page-size", data={"file": fp(PDF, "d.pdf"), "size": "a4"}, content_type=MP))
    check(g, "flatten", client.post("/api/pdf/flatten", data={"file": fp(PDF, "d.pdf")}, content_type=MP))
    # Tesseract and LibreOffice are optional system programs: a clear 4xx without them.
    check(g, "ocr", client.post("/api/pdf/ocr", data={"file": fp(PNG, "scan.png")}, content_type=MP), expect="ok_or_400")
    check(g, "from-office", client.post("/api/pdf/from-office", data={"file": fp(b"hello", "note.txt")}, content_type=MP), expect="ok_or_400")


def test_images2():
    g = "images"
    check(g, "adjust", client.post("/api/images/adjust", data={"file": fp(PNG, "i.png"), "brightness": "120"}, content_type=MP))
    check(g, "exif", client.post("/api/images/exif", data={"file": fp(PNG, "i.png")}, content_type=MP))
    check(g, "border", client.post("/api/images/border", data={"file": fp(PNG, "i.png"), "size": "4"}, content_type=MP))
    check(g, "favicon-set", client.post("/api/images/favicon-set", data={"file": fp(PNG, "i.png")}, content_type=MP))
    check(g, "upscale", client.post("/api/images/upscale", data={"file": fp(PNG, "i.png"), "factor": "2"}, content_type=MP))
    check(g, "collage", client.post("/api/images/collage", data={"files": [fp(PNG, "a.png"), fp(PNG, "b.png")], "cell": "32"}, content_type=MP))
    check(g, "ascii", client.post("/api/images/ascii", data={"file": fp(PNG, "i.png"), "width": "20"}, content_type=MP))
    # No HEIC encoder to make a fixture with: a PNG under that name is either converted or refused.
    check(g, "heic", client.post("/api/images/heic", data={"file": fp(PNG, "i.heic")}, content_type=MP), expect="ok_or_400")
    # "inf" is a float but not an int: this was an OverflowError and a 500.
    check(g, "heic (reject quality=inf)", client.post("/api/images/heic", data={"file": fp(PNG, "i.heic"), "quality": "inf"}, content_type=MP), expect="reject")
    check(g, "qr-generate (reject text=5)", client.post("/api/images/qr-generate", json={"text": 5}), expect="reject")


def test_convert2():
    g = "convert"
    check(g, "json-to-xml", client.post("/api/convert/json-to-xml", data={"text": '{"a": 1}'}))
    check(g, "html-to-md", client.post("/api/convert/html-to-md", data={"text": "<h1>Hi</h1><p>there</p>"}))
    check(g, "toml-to-json", client.post("/api/convert/toml-to-json", data={"text": 'a = 1\n[b]\nc = "d"\n'}))
    check(g, "json-to-toml", client.post("/api/convert/json-to-toml", data={"text": '{"a": 1, "b": {"c": "d"}}'}))
    check(g, "sql-format", client.post("/api/convert/sql-format", data={"text": "select a,b from t where a=1"}))
    x = client.post("/api/convert/csv-to-xlsx", data={"file": fp(b"a,b\n1,2\n", "d.csv")}, content_type=MP)
    check(g, "csv-to-xlsx", x)
    if x.status_code == 200:
        check(g, "xlsx-to-csv", client.post("/api/convert/xlsx-to-csv", data={"file": fp(x.data, "d.xlsx")}, content_type=MP))
    else:
        skip(g, "xlsx-to-csv", "csv-to-xlsx did not produce a file")
    z = client.post("/api/convert/zip", data={"files": [fp(b"hello", "a.txt"), fp(b"world", "b.txt")]}, content_type=MP)
    check(g, "archive-list", client.post("/api/convert/archive-list", data={"file": fp(z.data, "a.zip")}, content_type=MP))
    check(g, "extract-archive", client.post("/api/convert/extract-archive", data={"file": fp(z.data, "a.zip")}, content_type=MP))
    check(g, "checksum", client.post("/api/convert/checksum", data={"files": [fp(b"hello", "a.txt")]}, content_type=MP))
    check(g, "batch-rename", client.post("/api/convert/batch-rename", data={"files": [fp(b"1", "a.txt"), fp(b"2", "b.txt")], "pattern": "f-{n}.{ext}"}, content_type=MP))
    blob = os.urandom(300_000)
    sp = client.post("/api/convert/split-file", data={"file": fp(blob, "big.bin"), "chunk_mb": "0.1"}, content_type=MP)
    check(g, "split-file", sp)
    if sp.status_code == 200:
        with zipfile.ZipFile(io.BytesIO(sp.data)) as zf:
            parts = [(n, zf.read(n)) for n in sorted(zf.namelist()) if n != "JOIN.txt"]
        j = client.post("/api/convert/join-files", data={"files": [fp(d, n) for n, d in parts]}, content_type=MP)
        check(g, "join-files", j)
        expect_true(g, "split then join gives the file back", j.data == blob, f"{len(j.data)}B of {len(blob)}B")
    else:
        skip(g, "join-files", "split-file did not produce parts")
    # Flask stops a text field at 500 KB by default; a pasted document is often larger.
    big = "word " * 130_000
    check(g, "md-preview (650 KB of text)", client.post("/api/convert/md-preview", data={"text": big}, content_type=MP))
    check(g, "sql-format (650 KB of text)", client.post("/api/convert/sql-format", data={"text": "select 1; " * 65_000}, content_type=MP))
    # ... and a batch at 1000 parts.
    many = [fp(b"x", f"f{i}.txt") for i in range(1100)]
    check(g, "zip (1100 files)", client.post("/api/convert/zip", data={"files": many}, content_type=MP))


def test_av2():
    g = "av"
    names = ["remove-silence", "split-audio", "channels", "bitrate", "tags/read", "tags/write", "audio-to-video",
             "merge-video", "video-watermark", "frames", "video-speed", "stabilize", "gif-to-video", "info", "pip"]
    if not tools.ffmpeg_available():
        _av_without_files(g, names, "ffmpeg not available")
        return
    try:
        audio = _ffmpeg_make(["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame"], ".mp3")
        video = _ffmpeg_make(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15", "-f", "lavfi",
                              "-i", "sine=frequency=440:duration=0.5", "-t", "0.5", "-pix_fmt", "yuv420p",
                              "-c:v", "libx264", "-c:a", "aac"], ".mp4")
    except Exception as e:
        _av_without_files(g, names, f"fixture generation failed: {e}")
        return
    check(g, "remove-silence", client.post("/api/av/remove-silence", data={"file": fp(audio, "a.mp3")}, content_type=MP))
    check(g, "split-audio", client.post("/api/av/split-audio", data={"file": fp(audio, "a.mp3"), "mode": "count", "value": "2"}, content_type=MP))
    check(g, "channels", client.post("/api/av/channels", data={"file": fp(audio, "a.mp3"), "mode": "mono"}, content_type=MP))
    check(g, "bitrate", client.post("/api/av/bitrate", data={"file": fp(audio, "a.mp3"), "bitrate": "96"}, content_type=MP))
    check(g, "bitrate (reject inf)", client.post("/api/av/bitrate", data={"file": fp(audio, "a.mp3"), "bitrate": "inf"}, content_type=MP), expect="reject")
    check(g, "tags/read", client.post("/api/av/tags/read", data={"file": fp(audio, "a.mp3")}, content_type=MP))
    check(g, "tags/write", client.post("/api/av/tags/write", data={"file": fp(audio, "a.mp3"), "title": "T", "artist": "A"}, content_type=MP))
    check(g, "audio-to-video", client.post("/api/av/audio-to-video", data={"file": fp(audio, "a.mp3"), "style": "waveform", "resolution": "640x360"}, content_type=MP))
    check(g, "merge-video", client.post("/api/av/merge-video", data={"files": [fp(video, "a.mp4"), fp(video, "b.mp4")]}, content_type=MP))
    check(g, "video-watermark", client.post("/api/av/video-watermark", data={"video": fp(video, "v.mp4"), "image": fp(PNG, "w.png")}, content_type=MP))
    check(g, "frames", client.post("/api/av/frames", data={"file": fp(video, "v.mp4"), "mode": "single", "time": "0.1"}, content_type=MP))
    check(g, "video-speed", client.post("/api/av/video-speed", data={"file": fp(video, "v.mp4"), "speed": "2"}, content_type=MP))
    # Needs an ffmpeg built with vid.stab; a clear refusal without it.
    check(g, "stabilize", client.post("/api/av/stabilize", data={"file": fp(video, "v.mp4")}, content_type=MP), expect="ok_or_400")
    gif = client.post("/api/av/video-to-gif", data={"file": fp(video, "v.mp4"), "fps": "5", "width": "120"}, content_type=MP)
    if gif.status_code == 200:
        check(g, "gif-to-video", client.post("/api/av/gif-to-video", data={"file": fp(gif.data, "a.gif"), "format": "mp4"}, content_type=MP))
    else:
        skip(g, "gif-to-video", "video-to-gif did not produce a file")
    check(g, "info", client.post("/api/av/info", data={"file": fp(video, "v.mp4")}, content_type=MP))
    check(g, "pip", client.post("/api/av/pip", data={"main": fp(video, "v.mp4"), "overlay": fp(video, "o.mp4")}, content_type=MP))


# ── The server itself: guard, errors, settings, history ──

def test_server():
    g = "server"
    # Host / Origin guard. The test client's own Host is "localhost".
    check(g, "foreign Host refused", client.get("/api/history", headers={"Host": "evil.example:5001"}), expect="reject")
    check(g, "LAN address Host refused by default", client.get("/", headers={"Host": "192.168.1.5:5001"}), expect="reject")
    check(g, "IPv6 loopback Host with a port", client.get("/api/config", headers={"Host": "[::1]:5001"}))
    check(g, "IPv6 loopback Host without a port", client.get("/api/config", headers={"Host": "[::1]"}))
    check(g, "foreign Origin refused", client.post("/api/history", json={"title": "x"}, headers={"Origin": "http://evil.example"}), expect="reject")
    check(g, "Origin 'null' refused", client.post("/api/history", json={"title": "x"}, headers={"Origin": "null"}), expect="reject")
    check(g, "another local port's Origin refused",
          client.post("/api/config", json={"default_format": "mp3"}, headers={"Host": "127.0.0.1:5001", "Origin": "http://localhost:9999"}), expect="reject")
    check(g, "same-origin POST allowed",
          client.post("/api/config", json={"default_format": "mp3"}, headers={"Host": "127.0.0.1:5001", "Origin": "http://127.0.0.1:5001"}))
    # --host 0.0.0.0 (webapp._allow_bind_host): reachable by IP, still not by a rebound name.
    hosts, by_ip = set(webapp._extra_hosts), webapp._allow_ip_hosts
    try:
        webapp._allow_bind_host("0.0.0.0")
        check(g, "--host 0.0.0.0: LAN address allowed", client.get("/api/config", headers={"Host": "192.168.1.5:5001"}))
        check(g, "--host 0.0.0.0: a domain name still refused", client.get("/api/config", headers={"Host": "evil.example:5001"}), expect="reject")
        check(g, "--host 0.0.0.0: cross-origin POST still refused",
              client.post("/api/config", json={}, headers={"Host": "192.168.1.5:5001", "Origin": "http://10.0.0.9:5001"}), expect="reject")
    finally:
        webapp._extra_hosts.clear()
        webapp._extra_hosts.update(hosts)
        webapp._allow_ip_hosts = by_ip

    r = client.get("/settings")
    expect_true(g, "pages refuse to be framed by other sites", r.headers.get("X-Frame-Options") == "SAMEORIGIN", r.headers.get("X-Frame-Options"))
    r = client.get("/static/style.css")
    check(g, "static file", r)
    expect_true(g, "static file is cacheable", "max-age" in (r.headers.get("Cache-Control") or ""), r.headers.get("Cache-Control"))

    # API errors are JSON whatever raised them.
    for name, r in (("unknown /api/ path", client.get("/api/nope")),
                    ("wrong method", client.get("/api/download"))):
        ok = r.status_code in (404, 405) and isinstance(r.get_json(silent=True), dict) and "error" in r.get_json()
        expect_true(g, f"{name} answers in JSON", ok, f"{r.status_code} {r.content_type}")
    r = client.get("/nope")
    expect_true(g, "an unknown page keeps the HTML 404", r.status_code == 404 and "html" in r.content_type, r.content_type)
    limit = app.config["MAX_CONTENT_LENGTH"]
    try:
        app.config["MAX_CONTENT_LENGTH"] = 1000
        r = client.post("/api/pdf/merge", data={"files": [fp(b"x" * 5000, "a.pdf"), fp(b"x", "b.pdf")]}, content_type=MP)
    finally:
        app.config["MAX_CONTENT_LENGTH"] = limit
    expect_true(g, "an over-limit upload says so in JSON", r.status_code == 413 and "upload limit" in (r.get_json(silent=True) or {}).get("error", ""), f"{r.status_code} {r.data[:80]!r}")

    # The catch-all handler: answers 400, and logs, so a bug can't pass as bad input.
    real = tools.export_transcript_txt
    tools.export_transcript_txt = lambda *a, **k: {}["boom"]
    try:
        check(g, "catch-all 400 is logged", client.post("/api/transcribe/export", json={"segments": [{"start": 0, "end": 1, "text": "x"}]}), expect="malformed")
    finally:
        tools.export_transcript_txt = real

    # Settings.
    check(g, "config get", client.get("/api/config"))
    check(g, "config set", client.post("/api/config", json={"default_format": "mp3", "output_template": "{title}"}))
    expect_true(g, "config saved", webapp.load_config().get("output_template") == "{title}", webapp.load_config())
    check(g, "config (reject missing folder)", client.post("/api/config", json={"output_folder": str(STATE / "nope")}), expect="reject")
    check(g, "config (reject open_browser='yes')", client.post("/api/config", json={"open_browser": "yes"}), expect="reject")
    # A null saved here made every later download fail at the auto-save step.
    check(g, "config (reject output_folder=null)", client.post("/api/config", json={"output_folder": None}), expect="reject")
    check(g, "config (reject output_template=5)", client.post("/api/config", json={"output_template": 5}), expect="reject")
    check(g, "config (a list body changes nothing)", client.post("/api/config", json=["x"]))
    # A config.json that is valid JSON but not an object, as a hand edit can leave it.
    for junk in ("[]", "null", '"text"', "{not json"):
        webapp.CONFIG_FILE.write_text(junk)
        expect_true(g, f"config.json holding {junk} reads as empty", webapp.load_config() == {}, webapp.load_config())
    check(g, "open-folder with a broken config.json", client.post("/api/open-folder"), expect="reject")
    webapp.CONFIG_FILE.write_text('{"output_folder": null}')
    check(g, "open-folder with output_folder null on disk", client.post("/api/open-folder"), expect="reject")
    webapp.save_config({})

    # History.
    webapp.HISTORY_FILE.write_text('{"not": "a list"}')
    check(g, "history get with a broken history.json", client.get("/api/history"))
    check(g, "history add with a broken history.json", client.post("/api/history", json={"title": "first"}))
    check(g, "history (reject no title)", client.post("/api/history", json={}), expect="reject")
    webapp.save_history([{"title": f"seed{i}", "format": "mp3", "id": "i", "url": "u" * 300, "ts": 1} for i in range(50)])

    # Three playlist workers finishing together. Written in place, the file was
    # empty for a moment; a request reading it then started the history over.
    def add(n):
        c = app.test_client()
        for i in range(60):
            c.post("/api/history", json={"title": f"t{n}-{i}", "format": "mp3", "id": "i", "url": "u"})
    threads = [threading.Thread(target=add, args=(n,)) for n in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    items = webapp.load_history()
    new = {i["title"] for i in items if i["title"].startswith("t")}
    expect_true(g, "history survives concurrent adds", len(items) == 50 and len(new) == 50, f"{len(items)} items, {len(new)} of the newest 50")
    webapp.save_history([])
    leftovers = [p.name for p in webapp.CONFIG_DIR.iterdir() if p.name.endswith(".tmp")]
    expect_true(g, "no temp files left beside config.json", not leftovers, leftovers)

    # Routes that run pip, brew, a file picker or the desktop's "open": against stubs.
    real_update, real_ffmpeg = webapp.self_update, webapp.install_ffmpeg
    webapp.self_update = lambda engine_only=False: (True, "stub")
    webapp.install_ffmpeg = lambda: (True, "stub")
    try:
        check(g, "update (stubbed)", client.post("/api/update"))
        check(g, "update-ytdlp (stubbed)", client.post("/api/update-ytdlp"))
        check(g, "install-ffmpeg (stubbed)", client.post("/api/install-ffmpeg"))
    finally:
        webapp.self_update, webapp.install_ffmpeg = real_update, real_ffmpeg

    out = STATE / "out"
    out.mkdir(exist_ok=True)
    (out / "song.mp3").write_bytes(b"x")
    webapp.save_config({"output_folder": str(out)})
    opened = []

    class FakeDone:
        returncode, stdout, stderr = 1, "", ""

    real_popen, real_run = subprocess.Popen, subprocess.run
    subprocess.Popen = lambda cmd, *a, **k: opened.append(cmd)
    subprocess.run = lambda cmd, *a, **k: FakeDone()
    try:
        check(g, "open-folder (stubbed)", client.post("/api/open-folder"))
        check(g, "open-file (stubbed)", client.post("/api/open-file", json={"path": str(out / "song.mp3")}))
        check(g, "open-file (reject outside the folder)", client.post("/api/open-file", json={"path": str(STATE)}), expect="reject")
        check(g, "open-file (reject a sibling folder)", client.post("/api/open-file", json={"path": str(STATE / "out-private")}), expect="reject")
        check(g, "open-file (reject path=null)", client.post("/api/open-file", json={"path": None}), expect="reject")
        check(g, "browse-folder (stubbed, cancelled)", client.post("/api/browse-folder"), expect="ok_or_400")
    finally:
        subprocess.Popen, subprocess.run = real_popen, real_run
    expect_true(g, "only the two allowed paths were opened", len(opened) == 2, opened)
    webapp.save_config({})

    # Pure helpers shared with the CLI.
    # Linux filesystems count bytes (255); macOS and Windows count characters.
    name = webapp._safe_filename("あ" * 100, max_bytes=230) + " (2).webm"
    expect_true(g, "a 100-character Japanese title is cut to fit 255 bytes", len(name.encode()) <= 255 and name.startswith("あ" * 70), len(name.encode()))
    expect_true(g, "a short title is left alone", webapp._safe_filename("Song: Live?", max_bytes=230) == "Song_ Live_")
    expect_true(g, "a path in a title is not a path in a filename", "/" not in webapp._safe_filename("../../etc/passwd") and webapp._safe_filename("..") == "download")
    msg = webapp._friendly_download_error("ERROR: [youtube] abc123XYZ_-: Video unavailable. The uploader has not made this video available in your country")
    expect_true(g, "YouTube's country block reads as geo-restricted", "geo" in msg, msg)
    msg = webapp._friendly_download_error("ERROR: [generic] x: This video is not available from your location due to geo restriction")
    expect_true(g, "yt-dlp's geo restriction reads as geo-restricted", "geo" in msg, msg)
    msg = webapp._friendly_download_error("ERROR: [youtube] abc123XYZ_-: Sign in to confirm your age. This video may be inappropriate for some users.")
    expect_true(g, "an age gate is not a bot check", msg.startswith("Age-restricted"), msg)
    _fallbacks.drain()  # the three messages above are logged as download failures


# ── Downloads, with yt-dlp replaced by a stand-in (no network) ──

class FakeYDL:
    """What the server needs of yt_dlp.YoutubeDL: writes a small file where a
    real download would land and drives the progress hooks. A URL containing
    "slow" keeps "downloading" until a hook raises (that is how cancel works)."""
    title = "Smoke Test"

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        info = {"id": "abc", "title": FakeYDL.title, "uploader": "Someone", "duration": 3, "formats": []}
        if not download:
            return info
        path = Path(self.opts["outtmpl"] % {"ext": "mp4"})
        part = Path(str(path) + ".part")
        part.write_bytes(b"\0" * 64)
        hooks = self.opts.get("progress_hooks", [])
        for _ in range(500 if "slow" in url else 1):
            for h in hooks:
                h({"status": "downloading", "downloaded_bytes": 32, "total_bytes": 64, "speed": 2048, "eta": 1})
            if "slow" in url:
                time.sleep(0.02)
        part.rename(path)
        for h in hooks:
            h({"status": "finished"})
        return info


def _events(resp):
    return [json.loads(line[len("data: "):]) for line in resp.data.decode().split("\n\n") if line.startswith("data: ")]


def _download(url="https://example.com/v", **extra):
    """Start a download and follow its progress stream to the end. Returns (id, last event)."""
    webapp._download_timestamps.clear()
    r = client.post("/api/download", json={"url": url, "format": "mp4", **extra})
    dl_id = r.get_json()["id"]
    return dl_id, _events(client.get(f"/api/progress/{dl_id}"))[-1]


def test_downloads():
    g = "downloads"
    import yt_dlp
    real = yt_dlp.YoutubeDL
    yt_dlp.YoutubeDL = FakeYDL
    webapp.save_config({})
    try:
        check(g, "info", client.post("/api/info", json={"url": "https://example.com/v"}))
        check(g, "info (reject url=null)", client.post("/api/info", json={"url": None}), expect="reject")
        check(g, "download (reject url=5)", client.post("/api/download", json={"url": 5}), expect="reject")
        check(g, "download (reject a bad format id)", client.post("/api/download", json={"url": "https://example.com/v", "format_id": "137;rm"}), expect="reject")
        check(g, "download (reject clip_start='abc')", client.post("/api/download", json={"url": "https://example.com/v", "clip_start": "abc"}), expect="reject")
        check(g, "progress of an unknown id", client.get("/api/progress/nope"))
        check(g, "cancel (reject unknown id)", client.post("/api/cancel/nope"), expect="reject")
        check(g, "file (reject unknown id)", client.get("/api/file/nope"), expect="reject")

        a, last = _download()
        expect_true(g, "a download runs to done", last.get("status") == "done" and last.get("progress") == 100, last)
        r = client.get(f"/api/file/{a}")
        check(g, "file", r)
        expect_true(g, "the file is named after the title", "Smoke Test.mp4" in r.headers.get("Content-Disposition", ""), r.headers.get("Content-Disposition"))
        r.close()

        # Two downloads with one title: a ZIP with both names the same extracts only one.
        b, _ = _download()
        r = client.post("/api/batch-zip", json={"ids": [a, b, "gone"]})
        check(g, "batch-zip", r)
        names = zipfile.ZipFile(io.BytesIO(r.data)).namelist() if r.status_code == 200 else []
        expect_true(g, "batch-zip keeps both files of the same title", len(names) == 2 and len(set(names)) == 2, names)
        expect_true(g, "batch-zip states its size", r.headers.get("Content-Length") == str(len(r.data)), r.headers.get("Content-Length"))
        r.close()
        check(g, "batch-zip (reject none left)", client.post("/api/batch-zip", json={"ids": ["gone"]}), expect="reject")
        check(g, "batch-zip (reject no ids)", client.post("/api/batch-zip", json={}), expect="reject")
        check(g, "batch-zip (reject ids of the wrong type)", client.post("/api/batch-zip", json={"ids": [["x"], 5]}), expect="reject")
        stray = [p.name for p in webapp.DOWNLOAD_DIR.iterdir() if p.suffix == ".zip" or p.name.startswith("tmp")]
        expect_true(g, "batch-zip leaves no temp file behind", not stray, stray)

        # Auto-save to the output folder.
        out = STATE / "music"
        out.mkdir(exist_ok=True)
        webapp.save_config({"output_folder": str(out)})
        _, first = _download()
        _, second = _download()
        saved = sorted(p.name for p in out.iterdir())
        expect_true(g, "auto-save never overwrites a same-titled file", saved == ["Smoke Test (2).mp4", "Smoke Test.mp4"] and first.get("auto_saved") and second.get("auto_saved"), saved)

        FakeYDL.title = "あ" * 100  # 300 bytes: over the 255 a filename may have
        _, last = _download()
        FakeYDL.title = "Smoke Test"
        expect_true(g, "a long non-Latin title still auto-saves", last.get("status") == "done" and last.get("auto_saved"), {k: last.get(k) for k in ("status", "error", "auto_saved")})

        # A bad name template must not fail a download that already finished.
        webapp.save_config({"output_folder": str(out), "output_template": "{}"})
        _, last = _download()
        expect_true(g, "a broken name template falls back to the title", last.get("status") == "done", {k: last.get(k) for k in ("status", "error")})
        webapp.save_config({"output_folder": str(out)})

        if os.name == "posix" and os.geteuid() != 0:
            locked = STATE / "locked"
            locked.mkdir(exist_ok=True)
            os.chmod(locked, 0o555)
            webapp.save_config({"output_folder": str(locked)})
            try:
                c, last = _download()
            finally:
                os.chmod(locked, 0o755)
            ok = last.get("status") == "done" and not last.get("auto_saved") and client.get(f"/api/file/{c}").status_code == 200
            expect_true(g, "an unwritable output folder still leaves the file to save", ok, {k: last.get(k) for k in ("status", "error", "auto_saved")})
            _fallbacks.drain()  # the failed copy is logged as a warning
        else:
            skip(g, "an unwritable output folder still leaves the file to save", "needs POSIX permissions and a non-root user")
        webapp.save_config({})

        # Cancel: the worker stops, says so, and its partial file is removed.
        webapp._download_timestamps.clear()
        d = client.post("/api/download", json={"url": "https://example.com/slow", "format": "mp4"}).get_json()["id"]
        time.sleep(0.15)
        check(g, "cancel", client.post(f"/api/cancel/{d}"))
        last = _events(client.get(f"/api/progress/{d}"))[-1]
        left = [p.name for p in webapp.DOWNLOAD_DIR.iterdir() if p.name.startswith(d)]
        expect_true(g, "a cancelled download ends as cancelled", last.get("status") == "error" and last.get("error") == "Download cancelled.", last)
        expect_true(g, "a cancelled download leaves no partial file", not left, left)

        # The progress stream must send the final state even when the worker
        # finishes between one message and the next check.
        webapp.downloads["race"] = {"status": "metadata", "progress": 100}
        with app.test_request_context("/api/progress/race"):
            stream = iter(webapp.progress("race").response)
            next(stream)
            webapp.downloads["race"]["status"] = "done"
            rest = list(stream)
        webapp.downloads.pop("race", None)
        expect_true(g, "progress stream always ends on the final state", any('"done"' in str(m) for m in rest), rest)

        # Pruning.
        now = time.time()
        old = (now - 4000, now - 4000)
        dd = webapp.DOWNLOAD_DIR
        (dd / "longjob.mp4").write_bytes(b"x")
        webapp.downloads["longjob"] = {"status": "done", "filename": "longjob.mp4", "created": now - 4000, "finished": now - 5}
        (dd / "active.webp").write_bytes(b"x")
        os.utime(dd / "active.webp", old)
        webapp.downloads["active"] = {"status": "downloading", "filename": None, "created": now - 4000, "finished": None}
        (dd / "talk_audio.wav").write_bytes(b"x")
        os.utime(dd / "talk_audio.wav", old)
        webapp.transcriptions["talk"] = {"status": "transcribing", "created": now - 4000, "finished": None}
        (dd / "stale.mp4").write_bytes(b"x")
        os.utime(dd / "stale.mp4", old)
        webapp.downloads["stale"] = {"status": "done", "filename": "stale.mp4", "created": now - 8000, "finished": now - 4000}
        webapp.downloads["failed"] = {"status": "error", "filename": None, "created": now - 8000, "finished": now - 4000}
        webapp.cleanup_old_files()
        expect_true(g, "pruning keeps a download that ran over an hour and just finished", "longjob" in webapp.downloads and (dd / "longjob.mp4").exists())
        expect_true(g, "pruning keeps the files of a job still running", (dd / "active.webp").exists() and (dd / "talk_audio.wav").exists())
        expect_true(g, "pruning drops what finished over an hour ago", "stale" not in webapp.downloads and "failed" not in webapp.downloads and not (dd / "stale.mp4").exists())
        for k in ("longjob", "active"):
            webapp.downloads.pop(k, None)
        webapp.transcriptions.pop("talk", None)

        # A download directory left by a server that is gone is removed; a live one's is not.
        if os.name == "posix":
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            tmp = Path(tempfile.gettempdir())
            orphan = tmp / f"toolkit_{dead.pid}_0123456789ab"
            alive = tmp / f"toolkit_{os.getpid()}_0123456789ab"
            for d_ in (orphan, alive):
                d_.mkdir(exist_ok=True)
                (d_ / "video.mp4").write_bytes(b"x")
            webapp._remove_orphaned_download_dirs()
            ok = not orphan.exists() and alive.exists() and webapp.DOWNLOAD_DIR.exists()
            shutil.rmtree(alive, ignore_errors=True)
            shutil.rmtree(orphan, ignore_errors=True)
            expect_true(g, "a dead server's download directory is cleaned up, a live one's kept", ok)
    finally:
        yt_dlp.YoutubeDL = real
        webapp.save_config({})


def test_transcribe():
    g = "transcribe"
    check(g, "check", client.get("/api/transcribe/check"))
    # Never starts a real transcription (that would fetch a model): without the
    # optional engine the route says so, with it a missing file is refused.
    check(g, "transcribe (reject no file)", client.post("/api/transcribe", data={}, content_type=MP), expect="reject")
    check(g, "progress of an unknown id", client.get("/api/transcribe/progress/nope"))
    seg = [{"start": 0, "end": 1.5, "text": "hello", "speaker": "A"}]
    for fmt in ("txt", "srt", "vtt", "csv"):
        check(g, f"export {fmt}", client.post("/api/transcribe/export", json={"segments": seg, "format": fmt}))
    check(g, "export (reject format)", client.post("/api/transcribe/export", json={"segments": seg, "format": "docx"}), expect="reject")
    check(g, "export (reject no segments)", client.post("/api/transcribe/export", json={}), expect="reject")
    # The stream must end on the final state (same race as downloads).
    webapp.transcriptions["race"] = {"status": "transcribing", "progress": 90}
    with app.test_request_context("/api/transcribe/progress/race"):
        stream = iter(webapp.transcribe_progress("race").response)
        next(stream)
        webapp.transcriptions["race"]["status"] = "done"
        rest = list(stream)
    webapp.transcriptions.pop("race", None)
    expect_true(g, "progress stream always ends on the final state", any('"done"' in str(m) for m in rest), rest)


def test_route_coverage():
    """Every registered route was reached by some check above. A new route with
    no smoke check fails here until one is added."""
    g = "coverage"
    missed = sorted(r.rule for r in app.url_map.iter_rules() if r.rule not in _rules_hit)
    expect_true(g, f"all {len(list(app.url_map.iter_rules()))} routes were exercised", not missed, "never reached: " + ", ".join(missed))


def main():
    for fn in (test_pages, test_pdf, test_pdf2, test_images, test_images2, test_convert, test_convert2,
               test_av, test_av2, test_media, test_transcribe, test_server, test_downloads,
               test_route_coverage):
        try:
            fn()
        except Exception as e:
            results.append((fn.__name__, "(harness error)", "FAIL", repr(e)))

    width = max((len(f"{g}/{n}") for g, n, _, _ in results), default=10)
    cur = None
    for g, n, out, detail in results:
        if not QUIET and g != cur:
            print(f"\n  {g.upper()}")
            cur = g
        if QUIET and out == "PASS":
            continue
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[out]
        if not QUIET or out != "PASS":
            print(f"    {icon} {f'{g}/{n}':<{width}}  {detail}")

    npass = sum(1 for *_, o, _ in [(r[0], r[1], r[2], r[3]) for r in results] if o == "PASS")
    nfail = sum(1 for r in results if r[2] == "FAIL")
    nskip = sum(1 for r in results if r[2] == "SKIP")
    print(f"\n  {'='*48}")
    print(f"  {len(results)} checks:  {npass} PASS   {nfail} FAIL   {nskip} SKIP")
    if nfail:
        print(f"\n  FAILURES:")
        for g, n, out, detail in results:
            if out == "FAIL":
                print(f"    ✗ {g}/{n}: {detail}")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
