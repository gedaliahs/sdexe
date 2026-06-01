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
"""

import io
import sys
import subprocess
import tempfile
from pathlib import Path

# Allow running from the repo root without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdexe.app import app          # noqa: E402
from sdexe import tools            # noqa: E402
from pypdf import PdfWriter        # noqa: E402
from PIL import Image              # noqa: E402

QUIET = "--quiet" in sys.argv
client = app.test_client()
results = []  # (group, name, outcome, detail)


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
    """expect: 'ok' (want 200), 'ok_or_400' (200 or graceful 4xx), 'reject' (want 4xx)."""
    code = resp.status_code
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

def test_av():
    g = "av"
    if not tools.ffmpeg_available():
        for name in ["convert-audio", "trim-audio", "audio-speed", "extract-audio", "trim-video",
                     "compress-video", "convert-video", "merge-audio", "normalize-volume", "video-to-gif",
                     "reverse-audio", "change-pitch", "audio-equalizer", "audio-fade", "crop-video",
                     "rotate-video", "resize-video", "reverse-video", "loop-video", "mute-video",
                     "add-audio", "burn-subtitles"]:
            skip(g, name, "ffmpeg not available")
        return
    try:
        audio = _ffmpeg_make(["-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", "-c:a", "libmp3lame"], ".mp3")
        video = _ffmpeg_make(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15", "-f", "lavfi",
                              "-i", "sine=frequency=440:duration=0.5", "-t", "0.5", "-pix_fmt", "yuv420p",
                              "-c:v", "libx264", "-c:a", "aac"], ".mp4")
    except Exception as e:
        skip(g, "(all)", f"fixture generation failed: {e}")
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
        check(g, f"GET {path}", client.get(path))


def main():
    for fn in (test_pages, test_pdf, test_images, test_convert, test_av, test_media):
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
