#!/usr/bin/env python3
"""End-to-end smoke test for every `sdexe <group> <command>` in cli_tools.COMMANDS.

Builds tiny fixtures (PDFs, images, a tone, a test-pattern video, data files)
in a temp folder, runs each command through the real CLI entry point with
--json, and checks it exits 0 with an output that exists and is non-empty.
No network. Commands whose external tool is missing (tesseract, LibreOffice,
ffmpeg filters) are reported as SKIP, not FAIL.

Usage:
    python tests/cli_smoke_test.py            # exits non-zero on any FAIL
    python tests/cli_smoke_test.py --verbose  # print every command line
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sdexe import cli_tools, tools  # noqa: E402

VERBOSE = "--verbose" in sys.argv


def sdexe(*args, cwd):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    cmd = [sys.executable, "-m", "sdexe", *map(str, args)]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env, timeout=600)
    if VERBOSE:
        print("  $ sdexe", " ".join(map(str, args)))
    return r


def make_fixtures(d: Path) -> dict:
    from PIL import Image, ImageDraw
    from pypdf import PdfWriter

    f = {}
    img = Image.new("RGB", (320, 200), "#3366cc")
    ImageDraw.Draw(img).text((20, 80), "sdexe test 123", fill="white")
    for ext in ("png", "jpg"):
        img.save(d / f"photo.{ext}")
        f[ext] = d / f"photo.{ext}"
    img.rotate(90, expand=True).save(d / "photo2.png")
    f["png2"] = d / "photo2.png"

    for name, pages in (("doc", 3), ("doc2", 2)):
        w = PdfWriter()
        for _ in range(pages):
            w.add_blank_page(width=595, height=842)
        with open(d / f"{name}.pdf", "wb") as fh:
            w.write(fh)
        f[name] = d / f"{name}.pdf"
    # A PDF with real text and an embedded image, made from the image.
    (d / "scan.pdf").write_bytes(tools.images_to_pdf([img]))
    f["scan"] = d / "scan.pdf"
    with open(f["doc"], "rb") as fh:
        (d / "text.pdf").write_bytes(tools.watermark_pdf(fh, "hello from sdexe"))
    f["text"] = d / "text.pdf"

    ff = tools.ffmpeg_path()
    if ff:
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-f", "lavfi", "-i",
                        "anullsrc=r=44100:cl=stereo", "-filter_complex", "[0][1]amix=inputs=2:duration=shortest",
                        "-ac", "2", str(d / "tone.mp3")], capture_output=True)
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "sine=frequency=660:duration=2", str(d / "tone2.wav")],
                       capture_output=True)
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=3", "-shortest", "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", "-c:a", "aac", str(d / "clip.mp4")], capture_output=True)
        subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=2", "-pix_fmt",
                        "yuv420p", "-c:v", "libx264", str(d / "clip2.mp4")], capture_output=True)
        for k in ("tone.mp3", "tone2.wav", "clip.mp4", "clip2.mp4"):
            if (d / k).exists():
                f[k] = d / k
    (d / "subs.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n")
    f["srt"] = d / "subs.srt"

    (d / "data.csv").write_text("name,age\nada,36\nlinus,28\n")
    (d / "data.json").write_text('[{"name": "ada", "age": 36}]')
    (d / "data.yaml").write_text("name: ada\nage: 36\n")
    (d / "obj.json").write_text('{"name": "ada", "age": 36}')
    f["obj.json"] = d / "obj.json"
    (d / "data.xml").write_text("<root><name>ada</name></root>")
    (d / "data.toml").write_text('name = "ada"\n')
    (d / "data.tsv").write_text("name\tage\nada\t36\n")
    (d / "notes.md").write_text("# Title\n\nSome *text*.\n")
    (d / "page.html").write_text("<h1>Title</h1><p>Some <b>text</b>.</p>")
    for k in ("data.csv", "data.json", "data.yaml", "data.xml", "data.toml", "data.tsv", "notes.md", "page.html"):
        f[k] = d / k
    (d / "big.bin").write_bytes(os.urandom(300_000))
    f["bin"] = d / "big.bin"
    return f


def cases(f: dict) -> list:
    """(label, argv, needs) — needs names a fixture or tool that must exist."""
    P, P2, S = f["doc"], f["doc2"], f["scan"]
    I, J, I2 = f["png"], f["jpg"], f["png2"]
    A, A2 = f.get("tone.mp3"), f.get("tone2.wav")
    V, V2 = f.get("clip.mp4"), f.get("clip2.mp4")
    c = [
        ("pdf merge", ["pdf", "merge", P, P2]),
        ("pdf split", ["pdf", "split", P]),
        ("pdf split ranges", ["pdf", "split", P, "--ranges", "1-2,3"]),
        ("pdf pages", ["pdf", "pages", P, "--pages", "1,3"]),
        ("pdf delete", ["pdf", "delete", P, "--pages", "2"]),
        ("pdf reorder", ["pdf", "reorder", P, "--order", "3,1,2"]),
        ("pdf rotate", ["pdf", "rotate", P, "--angle", "180"]),
        ("pdf compress", ["pdf", "compress", S]),
        ("pdf text", ["pdf", "text", f["text"]]),
        ("pdf ocr", ["pdf", "ocr", S], "tesseract"),
        ("pdf info", ["pdf", "info", P]),
        ("pdf encrypt", ["pdf", "encrypt", P, "--password", "pw", "-o", "locked.pdf"]),
        ("pdf decrypt", ["pdf", "decrypt", "locked.pdf", "--password", "pw"]),
        ("pdf watermark", ["pdf", "watermark", P, "--text", "DRAFT"]),
        ("pdf number", ["pdf", "number", P]),
        ("pdf images", ["pdf", "images", S, "--dpi", "72"]),
        ("pdf extract-images", ["pdf", "extract-images", S]),
        ("pdf from-images", ["pdf", "from-images", I, J]),
        ("pdf from-office", ["pdf", "from-office", f["page.html"]], "soffice"),
        ("pdf flatten", ["pdf", "flatten", P, "--dpi", "40"]),
        ("pdf resize", ["pdf", "resize", P, "--size", "letter"]),
        ("pdf stamp", ["pdf", "stamp", P, I]),
        ("image resize", ["image", "resize", I, J, "--width", "100"]),
        ("image resize percent", ["image", "resize", I, "--percent", "50"]),
        ("image compress", ["image", "compress", J, "--quality", "low"]),
        ("image convert", ["image", "convert", I, "-f", "webp"]),
        ("image crop", ["image", "crop", I, "--width", "50", "--height", "40", "--x", "10"]),
        ("image rotate", ["image", "rotate", I]),
        ("image flip", ["image", "flip", I, "--direction", "vertical"]),
        ("image grayscale", ["image", "grayscale", J]),
        ("image blur", ["image", "blur", I]),
        ("image strip-exif", ["image", "strip-exif", J]),
        ("image watermark", ["image", "watermark", I, "--text", "hi"]),
        ("image adjust", ["image", "adjust", I, "--brightness", "120"]),
        ("image border", ["image", "border", I]),
        ("image upscale", ["image", "upscale", I]),
        ("image info", ["image", "info", J]),
        ("image ico", ["image", "ico", I]),
        ("image favicon", ["image", "favicon", I]),
        ("image collage", ["image", "collage", I, I2, J]),
        ("image ascii", ["image", "ascii", I, "--width", "40"]),
        ("image qr", ["image", "qr", "https://example.com"]),
        ("convert csv json", ["convert", f["data.csv"], "-f", "json"]),
        ("convert json csv", ["convert", f["data.json"], "-f", "csv"]),
        ("convert json yaml", ["convert", f["data.json"], "-f", "yaml"]),
        ("convert yaml json", ["convert", f["data.yaml"], "-f", "json"]),
        ("convert xml json", ["convert", f["data.xml"], "-f", "json"]),
        ("convert json xml", ["convert", f["data.json"], "-f", "xml"]),
        ("convert toml json", ["convert", f["data.toml"], "-f", "json"]),
        ("convert json toml", ["convert", f["obj.json"], "-f", "toml"]),
        ("convert tsv csv", ["convert", f["data.tsv"], "-f", "csv"]),
        ("convert md html", ["convert", f["notes.md"], "-f", "html"]),
        ("convert html md", ["convert", f["page.html"], "-f", "md"]),
        ("convert csv xlsx", ["convert", f["data.csv"], "-f", "xlsx", "-o", "sheet.xlsx"]),
        ("convert xlsx csv", ["convert", "sheet.xlsx", "-f", "csv"]),
        ("convert png jpg", ["convert", I, "-f", "jpg"]),
        ("file hash", ["file", "hash", f["bin"]]),
        ("file zip", ["file", "zip", I, J, "-o", "bundle.zip"]),
        ("file unzip", ["file", "unzip", "bundle.zip"]),
        ("file split", ["file", "split", f["bin"], "--size", "0.1"]),
    ]
    if A:
        c += [
            ("audio convert", ["audio", "convert", A, "-f", "wav"]),
            ("audio trim", ["audio", "trim", A, "--start", "1", "--end", "0:03"]),
            ("audio speed", ["audio", "speed", A, "--speed", "1.5"]),
            ("audio normalize", ["audio", "normalize", A]),
            ("audio fade", ["audio", "fade", A, "--in", "1", "--out", "1"]),
            ("audio pitch", ["audio", "pitch", A, "--semitones", "2"]),
            ("audio eq", ["audio", "eq", A, "--bass", "5"]),
            ("audio reverse", ["audio", "reverse", A]),
            ("audio silence", ["audio", "silence", A]),
            ("audio channels", ["audio", "channels", A, "--mode", "mono"]),
            ("audio bitrate", ["audio", "bitrate", A, "--kbps", "128"]),
            ("audio merge", ["audio", "merge", A, A2]),
            ("audio split", ["audio", "split", A, "--parts", "2"]),
            ("audio info", ["audio", "info", A]),
        ]
    if V:
        c += [
            ("video convert", ["video", "convert", V, "-f", "webm"]),
            ("video trim", ["video", "trim", V, "--start", "0", "--end", "2"]),
            ("video compress", ["video", "compress", V, "--quality", "low"]),
            ("video audio", ["video", "audio", V, "-f", "mp3"]),
            ("video gif", ["video", "gif", V, "--width", "160"]),
            ("video resize", ["video", "resize", V, "--width", "160"]),
            ("video rotate", ["video", "rotate", V]),
            ("video crop", ["video", "crop", V, "--width", "100", "--height", "100"]),
            ("video mute", ["video", "mute", V]),
            ("video speed", ["video", "speed", V, "--speed", "2"]),
            ("video reverse", ["video", "reverse", V]),
            ("video loop", ["video", "loop", V]),
            ("video stabilize", ["video", "stabilize", V], "vidstab"),
            ("video merge", ["video", "merge", V, V2]),
            ("video frames every", ["video", "frames", V, "--every", "1s"]),
            ("video frames at", ["video", "frames", V, "--at", "1"]),
            ("video add-audio", ["video", "add-audio", V2, A]),
            ("video subtitles", ["video", "subtitles", V, f["srt"]], "subtitles"),
            ("video watermark", ["video", "watermark", V, I]),
            ("video info", ["video", "info", V]),
        ]
    return c


def _available(need: str) -> bool:
    if need == "tesseract":
        from sdexe import tools_pdf2
        return bool(tools_pdf2.tesseract_path())
    if need == "soffice":
        from sdexe import tools_pdf2
        return bool(tools_pdf2.soffice_path())
    return bool(tools.ffmpeg_exe_with_filter(need))


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="sdexe-cli-test-"))
    rows = []
    try:
        fx = make_fixtures(work)
        run_cases = cases(fx)
        covered = {c[0].split()[0] + " " + c[0].split()[1] if c[0].split()[0] != "convert" else "convert"
                   for c in run_cases}
        for case in run_cases:
            label, argv = case[0], case[1]
            need = case[2] if len(case) > 2 else None
            if need and not _available(need):
                rows.append((label, "SKIP", f"{need} not installed"))
                continue
            r = sdexe(*argv, "--json", cwd=work)
            try:
                doc = json.loads(r.stdout)
            except json.JSONDecodeError:
                rows.append((label, "FAIL", f"exit {r.returncode}, no JSON: {(r.stderr or r.stdout)[:200]}"))
                continue
            res = doc["results"][0] if doc.get("results") else {}
            if r.returncode != 0 or not doc.get("ok"):
                rows.append((label, "FAIL", res.get("error") or r.stderr[:200]))
                continue
            outs = res.get("outputs") or []
            if outs and not all(Path(o["path"]).is_file() and Path(o["path"]).stat().st_size > 0 for o in outs):
                rows.append((label, "FAIL", "output missing or empty"))
            elif not outs and not res.get("text") and not res.get("data"):
                rows.append((label, "FAIL", "no output"))
            else:
                what = (f"{len(outs)} file(s)" if outs else "text" if res.get("text") else "data")
                rows.append((label, "PASS", what))

        # Every command in the table must have at least one case.
        for c in cli_tools.COMMANDS:
            if c.full not in covered and not (c.group in ("audio",) and "tone.mp3" not in fx) \
                    and not (c.group == "video" and "clip.mp4" not in fx):
                rows.append((c.full, "FAIL", "no test case"))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    width = max(len(r[0]) for r in rows) + 2
    for label, outcome, detail in rows:
        if VERBOSE or outcome != "PASS":
            print(f"  {outcome:4}  {label.ljust(width)}{detail}")
    counts = {k: sum(r[1] == k for r in rows) for k in ("PASS", "FAIL", "SKIP")}
    print(f"\n  {len(rows)} checks:  {counts['PASS']} PASS   {counts['FAIL']} FAIL   {counts['SKIP']} SKIP")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
