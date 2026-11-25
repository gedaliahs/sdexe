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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sdexe import cli_tools, tools  # noqa: E402

VERBOSE = "--verbose" in sys.argv


HOME = None  # a throwaway home, so settings tests never touch the real config


def sdexe(*args, cwd, module="sdexe"):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "HOME": str(HOME), "ZDOTDIR": str(HOME)}
    cmd = [sys.executable, "-m", module, *map(str, args)]
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


def settings_checks(work: Path) -> list:
    """`sdexe settings` get/set/reset, and that a changed default reaches downloads."""
    out = []

    def check(label, ok, detail=""):
        out.append((label, "PASS" if ok else "FAIL", detail))

    r = sdexe("settings", "--json", cwd=work)
    doc = json.loads(r.stdout or "{}")
    check("settings --json", r.returncode == 0 and doc.get("dl_quality") == "1080p60", r.stderr[:120])
    r = sdexe("settings", "set", "dl_quality", "720p60", cwd=work)
    check("settings set", r.returncode == 0)
    r = sdexe("settings", "get", "dl_quality", cwd=work)
    check("settings get", r.stdout.strip() == "720p60", r.stdout.strip())
    r = sdexe("settings", "set", "dl_quality", "999p", cwd=work)
    check("settings set rejects bad values", r.returncode == 2)
    r = sdexe("settings", "set", "dl_jobs", "99", cwd=work)
    check("settings set checks ranges", r.returncode == 2)
    probe = ("import sys; sys.path.insert(0, %r); from sdexe.cli import resolve_spec; "
             "print(resolve_spec([]).label)" % str(ROOT))
    env = {**os.environ, "HOME": str(HOME)}
    label = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env).stdout.strip()
    check("download uses the default quality", label.endswith("720p60"), label)
    r = sdexe("settings", "reset", cwd=work)
    r2 = sdexe("settings", "get", "dl_quality", cwd=work)
    check("settings reset", r.returncode == 0 and r2.stdout.strip() == "1080p60", r2.stdout.strip())
    return out

def _checker(out: list):
    def check(label, ok, detail=""):
        out.append((label, "PASS" if ok else "FAIL", "" if ok else str(detail)[:300]))
    return check


def _env(**extra) -> dict:
    return {**os.environ, "PYTHONPATH": str(ROOT), "HOME": str(HOME), "ZDOTDIR": str(HOME), **extra}


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def regression_checks(work: Path, fx: dict) -> list:
    """One case per bug fixed in the command line: usage errors, output naming,
    pipes and interrupts."""
    out = []
    check = _checker(out)
    d = work / "reg"
    d.mkdir()
    for name in ("photo.png", "photo2.png", "photo.jpg", "doc.pdf"):
        shutil.copy(work / name, d / name)

    # --json means JSON on stdout, on a usage error too.
    for label, argv in (("tool", ["image", "resize", "nope.png", "--width", "10"]),
                        ("download", ["download"]), ("info", ["info"]), ("search", ["search"]),
                        ("unknown command", ["image", "nope"])):
        r = sdexe(*argv, "--json", cwd=d)
        doc = _json(r.stdout)
        check(f"usage error with --json is JSON ({label})",
              r.returncode == 2 and isinstance(doc, dict) and doc.get("ok") is False and doc.get("error"),
              f"exit {r.returncode}: {r.stdout[:120]!r}")
    r = sdexe("image", "resize", "nope.png", "--width", "10", cwd=d)
    check("usage error without --json prints nothing on stdout", r.returncode == 2 and r.stdout == "", r.stdout)

    # -o naming the input used to replace it.
    before = (d / "photo.png").read_bytes()
    r = sdexe("image", "resize", "photo.png", "--width", "10", "-o", "photo.png", cwd=d)
    check("-o naming the input is refused", r.returncode == 2 and (d / "photo.png").read_bytes() == before, r.stderr)
    # Same file under another spelling (macOS and Windows ignore case) or a hard link.
    os.link(d / "photo.png", d / "hardlink.png")
    for other in ["hardlink.png"] + (["PHOTO.PNG"] if (d / "PHOTO.PNG").exists() else []):
        before = (d / "photo.png").read_bytes()
        r = sdexe("image", "resize", "photo.png", "--width", "10", "-o", other, cwd=d)
        check(f"-o {other} (the input itself) is refused", r.returncode == 2 and (d / "photo.png").read_bytes() == before)
    (d / "hardlink.png").unlink()
    before = (d / "doc.pdf").read_bytes()
    r = sdexe("pdf", "text", "doc.pdf", "-o", "doc.pdf", cwd=d)
    check("text output never replaces the input", r.returncode == 2 and (d / "doc.pdf").read_bytes() == before,
          r.stderr)

    # A pattern the shell did not expand (zsh `noglob sdexe` alias, cmd.exe).
    r = sdexe("image", "resize", "photo*.png", "--width", "10", "--json", cwd=d)
    doc = _json(r.stdout) or {}
    check("unexpanded *.png is expanded", r.returncode == 0 and len(doc.get("results", [])) == 2, r.stderr or r.stdout)
    r = sdexe("image", "resize", "nomatch*.png", "--width", "10", cwd=d)
    check("a pattern matching nothing is a usage error", r.returncode == 2 and "nomatch*.png" in r.stderr, r.stderr)
    r = sdexe("pdf", "info", ".", cwd=d)
    check("a folder as input says so", r.returncode == 2 and "folder" in r.stderr, r.stderr)

    r = sdexe("image", "qr", "--json", "--", "-h", cwd=d)
    doc = _json(r.stdout) or {}
    check('"-h" after -- is text, not a request for help', r.returncode == 0 and doc.get("ok") is True, r.stdout[:200])
    r = sdexe("pdf", "pages", "--help", cwd=d)
    check("--help works without the required options", r.returncode == 0 and "--pages" in r.stdout, r.stderr)

    r = sdexe("image", "convert", "photo.png", "-f", "jpg", "-o", "pic.jpeg", cwd=d)
    check("-o pic.jpeg keeps its name for a jpg", r.returncode == 0 and (d / "pic.jpeg").is_file(), r.stdout)
    # HEIC is read by every command that opens an image, on both entry points.
    try:
        import pillow_heif
        from PIL import Image
        pillow_heif.register_heif_opener()
        Image.new("RGB", (64, 48), "red").save(d / "logo.heic")
    except Exception as e:  # noqa: BLE001 - no HEIC encoder in this install
        out.append(("HEIC input", "SKIP", f"can't write a HEIC fixture: {e}"))
    else:
        for module in ("sdexe", "sdexe.cli_tools"):
            for argv in (["pdf", "stamp", "doc.pdf", "logo.heic"], ["image", "convert", "logo.heic", "-f", "png"]):
                r = sdexe(*argv, "--json", cwd=d, module=module)
                check(f"HEIC input: {' '.join(argv[:2])} via -m {module}", r.returncode == 0, r.stdout[-200:])
    r = sdexe("image", "convert", "photo.png", "-f", "jpg", "-o", "pic2.png", cwd=d)
    check("-o with the wrong extension gets the right one", r.returncode == 0 and (d / "pic2.jpg").is_file()
          and not (d / "pic2.png").exists(), r.stdout)

    # Values no option can use.
    for label, argv, code in (
            ("nan is not a number", ["image", "resize", "photo.png", "--percent", "nan"], 2),
            ("range on --box-size", ["image", "qr", "x", "--box-size", "100000"], 2),
            ("range on --dpi", ["pdf", "flatten", "doc.pdf", "--dpi", "0"], 2),
            ("crop outside the image", ["image", "crop", "photo.png", "--width", "5000", "--height", "10"], 1),
            ("crop of zero size", ["image", "crop", "photo.png", "--width", "0", "--height", "0"], 1),
            ("empty --order", ["pdf", "reorder", "doc.pdf", "--order", ","], 1),
            ("--sizes 0", ["image", "ico", "photo.png", "--sizes", "0"], 1),
            ("negative time", ["download", "https://example.invalid/a", "--start", "-5"], 2),
            ("--end 0", ["download", "https://example.invalid/a", "--end", "0"], 2),
            ("--end before --start", ["download", "https://example.invalid/a", "--start", "1:00", "--end", "30"], 2),
            ("unknown browser", ["download", "https://example.invalid/a", "--cookies-from-browser", "netscape"], 2),
            ("two formats", ["download", "https://example.invalid/a", "-mp3", "-wav"], 2),
            ("-o file for two links", ["download", "https://example.invalid/a", "https://example.invalid/b",
                                       "-o", "x.mp4"], 2),
            ("unknown tag", ["download", "https://example.invalid/a", "-999p"], 2)):
        r = sdexe(*argv, cwd=d)
        check(f"rejected: {label}", r.returncode == code and "Traceback" not in r.stderr,
              f"exit {r.returncode}: {r.stderr[-200:]}")

    # Link files: a byte-order mark, and a file that isn't text.
    (d / "bom.txt").write_bytes(b"\xef\xbb\xbfhttps://example.invalid/a\n")
    r = sdexe("download", "-i", "bom.txt", "--start", "abc", cwd=d)
    check("-i reads a file with a byte-order mark", r.returncode == 2 and "abc" in r.stderr, r.stderr)
    r = sdexe("download", "-i", "photo.png", cwd=d)
    check("-i on a binary file is a usage error", r.returncode == 2 and "Traceback" not in r.stderr, r.stderr[-200:])

    # A reader that goes away (`| head -1`) is not a crash.
    p = subprocess.Popen([sys.executable, "-m", "sdexe", "image", "info", "photo.png", "photo2.png", "photo.jpg"],
                         cwd=d, env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p.stdout.close()
    err = p.stderr.read()
    check("stdout closed early: no traceback", p.wait(60) == 0 and "Traceback" not in err and "BrokenPipe" not in err,
          f"exit {p.returncode}: {err[-200:]}")

    if os.name == "posix":
        import signal
        # Ctrl+C during a tool: exit 130, and --json still gets a document.
        slow = ("import sys, time\n"
                "from sdexe import cli_tools\n"
                "cli_tools._BY_NAME[('file', 'hash')].run = lambda p, a: time.sleep(60)\n"
                "print('ready', file=sys.stderr, flush=True)\n"
                "sys.exit(cli_tools.tools_main(['file', 'hash', 'photo.png', '--json']))\n")
        for name, sig in (("Ctrl+C", signal.SIGINT), ("kill", signal.SIGTERM)):
            p = subprocess.Popen([sys.executable, "-c", slow], cwd=d, env=_env(), stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
            p.stderr.readline()
            time.sleep(0.5)
            p.send_signal(sig)
            stdout, err = p.communicate(timeout=30)
            doc = _json(stdout)
            check(f"{name} during a tool: exit 130 and JSON", p.returncode == 130 and isinstance(doc, dict)
                  and doc.get("ok") is False and "Traceback" not in err, f"exit {p.returncode}: {err[-200:]}")
    return out


# `sdexe download` with the network replaced: each link "downloads" for
# FAKE_DELAY seconds inside a temp folder, like the real thing, then is saved.
FAKE_DOWNLOAD = r"""
import os, shutil, sys, tempfile, time
from pathlib import Path
from sdexe import cli

def attempt(self, item):
    tmp = Path(tempfile.mkdtemp(prefix="sdexe-dl-"))
    self.tmp_dirs.add(tmp)
    try:
        (tmp / "x.mp4.part").write_bytes(b"x" * 1000)
        end = time.time() + float(os.environ.get("FAKE_DELAY", "0.2"))
        while time.time() < end:
            if self.cancel.is_set():
                raise RuntimeError("Cancelled by user")
            time.sleep(0.05)
        item.title = item.url.rsplit("/", 1)[-1]
        item.info = {"id": item.title}
        (tmp / "x.mp4").write_bytes(b"data")
        item.path = self._save(item, {"title": item.title}, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        self.tmp_dirs.discard(tmp)

cli.Downloader._attempt = attempt
cli.tools.ffmpeg_path = lambda: sys.executable
sys.exit(cli.download_main(sys.argv[1:]))
"""


def download_checks(work: Path) -> list:
    """The download command's own plumbing, with no network: stdout going away,
    being stopped half way, JSON and exit codes."""
    out = []
    check = _checker(out)
    d = work / "dl"
    tmp = work / "dl-tmp"
    d.mkdir()
    tmp.mkdir()
    links = [f"https://example.invalid/v{i}" for i in range(6)]
    cmd = [sys.executable, "-c", FAKE_DOWNLOAD]

    r = subprocess.run([*cmd, *links[:2], "--json", "-o", "a"], cwd=d, env=_env(TMPDIR=str(tmp)),
                       capture_output=True, text=True, timeout=120)
    doc = _json(r.stdout) or {}
    check("download --json: one document, exit 0", r.returncode == 0 and doc.get("saved") == 2
          and all(Path(x["path"]).is_file() for x in doc.get("results", [])), r.stderr[-200:])
    r = subprocess.run([*cmd, *links[:2], "-o", "b"], cwd=d, env=_env(TMPDIR=str(tmp)), capture_output=True,
                       text=True, timeout=120)
    check("download: only saved paths on stdout", r.returncode == 0
          and sorted(r.stdout.split("\n")[:-1]) == sorted(str(p.resolve()) for p in (d / "b").iterdir()), r.stdout)
    r = subprocess.run([*cmd, links[0], links[0] + "?x", "-o", "b"], cwd=d, env=_env(TMPDIR=str(tmp)),
                       capture_output=True, text=True, timeout=120)
    check("download: never over an existing file", r.returncode == 0 and (d / "b" / "v0 (2).mp4").is_file(), r.stdout)

    # `sdexe download … | head -1`: each worker died on its print, and the
    # links still queued then waited forever.
    p = subprocess.Popen([*cmd, *links, "-j", "2", "-o", "c"], cwd=d, env=_env(TMPDIR=str(tmp)),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p.stdout.close()
    try:
        err = p.communicate(timeout=60)[1]
        check("download: stdout closed early still finishes", p.returncode == 0
              and len(list((d / "c").iterdir())) == 6 and "Traceback" not in err, f"exit {p.returncode}: {err[-200:]}")
    except subprocess.TimeoutExpired:
        p.kill()
        check("download: stdout closed early still finishes", False, "hung")

    if os.name == "posix":
        import signal
        for name, sig in (("Ctrl+C", signal.SIGINT), ("kill", signal.SIGTERM)):
            p = subprocess.Popen([*cmd, *links[:2], "--json", "-o", "e"], cwd=d, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, env=_env(TMPDIR=str(tmp), FAKE_DELAY="60"))
            deadline = time.time() + 30
            while not any(tmp.iterdir()) and time.time() < deadline:
                time.sleep(0.1)
            p.send_signal(sig)
            stdout, err = p.communicate(timeout=30)
            doc = _json(stdout) or {}
            check(f"{name} during a download: exit 130, JSON, no partial files", p.returncode == 130
                  and doc.get("ok") is False and doc.get("failed") == 2 and not any(tmp.iterdir())
                  and not ((d / "e").exists() and any((d / "e").iterdir())),
                  f"exit {p.returncode}, temp {[f.name for f in tmp.iterdir()]}: {err[-200:]}")
    return out


def offline_checks() -> list:
    """Tag parsing and yt-dlp format selection, in this process, on made-up data."""
    out = []
    check = _checker(out)
    os.environ["HOME"] = str(HOME)  # defaults come from settings
    from sdexe import cli, media

    def spec(*argv):
        try:
            args, tags = cli.parse_args(["https://example.invalid/a", *argv])
            return cli.resolve_spec(tags).label
        except cli.UsageError as e:
            return f"error: {e}"

    for argv, want in ((["-mp3"], "MP3 · 320 kbps"), (["--mp3", "mp3"], "MP3 · 320 kbps"), (["-mp3", "-128"], "MP3 · 128 kbps"),
                       (["-f", "mp3", "-q", "192"], "MP3 · 192 kbps"), (["-a"], "WAV · lossless"),
                       (["-720p"], "MP4 · up to 720p"), (["-q", "720p60"], "MP4 · up to 720p60"),
                       (["4k"], "MP4 · up to 2160p"), (["--best"], "MP4 · best available"),
                       (["-mkv", "-1080p30"], "MKV · up to 1080p30"), (["-aac"], "M4A"),
                       (["-mp3", "-wav"], "error: Pick one format"), (["-720p", "--best"], "error: Pick one quality"),
                       (["-a", "-mp4"], "error: mp4 is a video format"), (["-f", "1080p"], "error: Unknown format"),
                       (["-q", "mp3"], "error: Unknown quality"), (["-999p"], "error: Unknown option -999p"),
                       (["-5"], "error: Unknown option -5"), (["--limit", "x"], "error: Argument --limit")):
        got = spec(*argv)
        check(f"tags {' '.join(argv)}", got.startswith(want), got)
    args, tags = cli.parse_args(["--", "-mp3"])
    check("after --, -mp3 is a link, not a tag", args.urls == ["-mp3"] and not tags, f"{args.urls} {tags}")
    for text, want in (("90", 90), ("1:30", 90), ("1:02:03", 3723), ("1m30s", 90), ("2h", 7200), ("-5", None),
                       ("nan", None), ("inf", None), ("1:-30", None), ("1:2:3:4", None), ("", None)):
        try:
            got = cli.parse_time(text)
        except cli.UsageError:
            got = None
        check(f"time {text!r}", got == want, got)

    # What yt-dlp picks for the options sdexe builds, on synthetic formats.
    import copy
    import yt_dlp

    def v(fid, w, h, fps, tbr, ext="mp4"):
        return {"format_id": fid, "url": f"https://x/{fid}", "ext": ext, "width": w, "height": h, "fps": fps,
                "tbr": tbr, "vcodec": "vp9" if ext == "webm" else "avc1", "acodec": "none", "protocol": "https"}

    def a(fid, tbr, ext="m4a", **kw):
        return {"format_id": fid, "url": f"https://x/{fid}", "ext": ext, "tbr": tbr, "abr": tbr, "vcodec": "none",
                "acodec": "opus" if ext == "webm" else "mp4a", "protocol": "https", **kw}

    def pick(formats, fmt, **kw):
        opts = media.build_ydl_opts(fmt, prefer_fps=True, thumbnail=False, **kw)
        opts.update(quiet=True, no_warnings=True, postprocessors=[])
        info = {"id": "x", "title": "t", "extractor": "test", "extractor_key": "Test", "webpage_url": "https://x",
                "formats": copy.deepcopy(formats)}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                r = ydl.process_video_result(info, download=False)
        except Exception as e:  # noqa: BLE001
            return f"error: {e}"
        return "+".join(f["format_id"] for f in r.get("requested_formats") or [r]) + f" .{r['ext']}"

    land = [v("2160", 3840, 2160, 60, 20000, "webm"), v("1080p60", 1920, 1080, 60, 6000), v("1080p30", 1920, 1080, 30, 4500),
            v("1080w", 1920, 1080, 60, 6500, "webm"), v("720", 1280, 720, 30, 2000), v("360", 640, 360, 30, 500),
            a("aac", 129), a("vorb", 135, "webm")]
    tall = [v("1080x1920", 1080, 1920, 30, 5000), v("576x1024", 576, 1024, 30, 1200), v("360x640", 360, 640, 30, 500),
            a("aac", 129)]
    dubs = [v("1080", 1920, 1080, 30, 4500), a("original", 129.4, language="en", language_preference=10, quality=3),
            a("dubbed", 129.9, language="es", language_preference=-1, quality=3),
            a("described", 131.0, language="en", language_preference=-10, quality=3),
            a("drc", 130.5, language="en", language_preference=10, quality=2.5)]
    for label, got, want in (
            ("mp4 1080p60", pick(land, "mp4", height=1080, fps=60), "1080w+vorb .mp4"),
            ("mp4 1080p30 prefers 30 fps", pick(land, "mp4", height=1080, fps=30), "1080p30+vorb .mp4"),
            ("mp4 720p", pick(land, "mp4", height=720), "720+vorb .mp4"),
            ("mp4 480p steps down", pick(land, "mp4", height=480), "360+vorb .mp4"),
            ("mp4 144p takes the smallest", pick(land, "mp4", height=144), "360+vorb .mp4"),
            ("mp4 best", pick(land, "mp4"), "2160+vorb .mp4"),
            ("webm 1080p stays webm", pick(land, "webm", height=1080), "1080w+vorb .webm"),
            ("webm 720p: no webm that small, so mkv", pick(land, "webm", height=720), "720+vorb .mkv"),
            ("m4a takes the m4a stream", pick(land, "m4a"), "aac .m4a"),
            ("mp3 takes the best audio", pick(land, "mp3"), "vorb .webm"),
            ("vertical 1080x1920 is 1080p", pick(tall, "mp4", height=1080), "1080x1920+aac .mp4"),
            ("vertical 480p works", pick(tall, "mp4", height=480), "360x640+aac .mp4"),
            ("vertical webm request", pick(tall, "webm", height=1080), "1080x1920+aac .mkv"),
            ("original audio beats dubbed, described and DRC", pick(dubs, "mp4", height=1080), "1080+original .mp4"),
            ("audio only keeps the original track", pick(dubs, "m4a"), "original .m4a")):
        check(f"formats: {label}", got == want, got)
    return out


def integration_checks(work: Path) -> list:
    """Config values of the wrong type, and editing ~/.zshrc without harming it."""
    out = []
    check = _checker(out)
    cfg = HOME / ".config" / "sdexe" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    for body in ('[]', '{bad', '{"dl_jobs": 1e400, "dl_quality": 720, "open_browser": "maybe", "port": 80, '
                 '"dl_folder": 5, "accent": 5, "not_a_setting": 1}'):
        cfg.write_text(body)
        r = sdexe("settings", "--json", cwd=work)
        doc = _json(r.stdout) or {}
        check(f"settings survive config.json = {body[:24]}", r.returncode == 0 and doc.get("dl_jobs") == 3
              and doc.get("dl_quality") == "1080p60" and doc.get("open_browser") is True, r.stderr[-200:])
    cfg.unlink()

    # settings.put beside the web app saving the same file, in one process (the
    # terminal app runs both): without the shared lock 59 of 60 saves were lost.
    race = ("import threading\n"
            "from sdexe import app, settings\n"
            "def web(i):\n"
            "    with app._state_lock:\n"
            "        cfg = app.load_config(); cfg[f'web_{i}'] = 1; app.save_config(cfg)\n"
            "ts = [threading.Thread(target=lambda: [settings.put('dl_jobs', i % 7 + 2) for i in range(60)]),\n"
            "      threading.Thread(target=lambda: [web(i) for i in range(60)])]\n"
            "[t.start() for t in ts]; [t.join() for t in ts]\n"
            "cfg = app.load_config()\n"
            "print(sum(k.startswith('web_') for k in cfg), cfg.get('dl_jobs'))\n")
    r = subprocess.run([sys.executable, "-c", race], cwd=work, env=_env(), capture_output=True, text=True, timeout=120)
    check("settings saved from two threads lose nothing", r.stdout.split() == ["60", "5"], r.stdout + r.stderr[-200:])
    cfg.unlink(missing_ok=True)

    probe = ("import json, sys\n"
             "from sdexe import settings\n"
             "print(json.dumps([settings.zsh_alias_on(), settings.set_zsh_alias(sys.argv[1] == 'on'),"
             " settings.zsh_alias_on()]))\n")

    def zsh(action):
        r = subprocess.run([sys.executable, "-c", probe, action], cwd=work, env=_env(SHELL="/bin/zsh"),
                           capture_output=True, text=True, timeout=60)
        return _json(r.stdout) or [None, r.stderr[-200:], None]

    rc = HOME / ".zshrc"
    mine = b"export A=1\r\n# caf\xe9\nalias yt='noglob sdexe download -mp3'\n# was: alias sdexe='noglob sdexe'\nexport B=2"
    rc.write_bytes(mine)
    check("zsh: someone's own alias is not ours", zsh("off") == [False, zsh("off")[1], False] and rc.read_bytes() == mine)
    on = zsh("on")
    check("zsh: alias added once", on[0] is False and on[2] is True and zsh("on")[2] is True
          and rc.read_bytes().count(b"\nalias sdexe='noglob sdexe'\n") == 1 and rc.read_bytes().startswith(mine), on)
    off = zsh("off")
    check("zsh: alias removed, the rest untouched to the byte", off[2] is False and rc.read_bytes() == mine, off)
    rc.write_bytes(b'export A=1\n  alias sdexe="noglob sdexe"  # mine\nexport B=2\n')
    off = zsh("off")
    check("zsh: a hand-written alias is found and removed", off[0] is True and off[2] is False
          and rc.read_bytes() == b"export A=1\nexport B=2\n", off)
    if os.name == "posix" and os.geteuid() != 0:
        rc.chmod(0o444)
        on = zsh("on")
        check("zsh: a read-only file is reported, not a crash", on[2] is False and "Couldn't" in str(on[1]), on)
        rc.chmod(0o644)
    rc.unlink()
    return out


class _Mcp:
    """A minimal MCP client over stdio."""

    def __init__(self, cwd: Path, **env):
        import threading
        self.p = subprocess.Popen([sys.executable, "-m", "sdexe", "mcp"], cwd=cwd, env=_env(**env), text=True,
                                  encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        self.replies, self.stray, self.garbage = {}, [], []
        self.cv = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.p.stdout:
            msg = _json(line)
            with self.cv:
                if not isinstance(msg, dict):
                    self.garbage.append(line)
                elif msg.get("id") is None:
                    self.stray.append(msg)
                else:
                    self.replies[msg["id"]] = msg
                self.cv.notify_all()

    def raw(self, text: str):
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()

    def send(self, **msg):
        self.raw(json.dumps({"jsonrpc": "2.0", **msg}))

    def ask(self, id_, method, params=None, timeout=120):
        self.send(id=id_, method=method, **({"params": params} if params is not None else {}))
        return self.wait(id_, timeout)

    def wait(self, id_, timeout=120):
        with self.cv:
            self.cv.wait_for(lambda: id_ in self.replies, timeout)
            return self.replies.get(id_) or {}

    def close(self) -> int:
        try:
            self.p.stdin.close()
            return self.p.wait(30)
        except Exception:  # noqa: BLE001
            self.p.kill()
            return -1


def mcp_checks(work: Path, fx: dict) -> list:
    """`sdexe mcp` over stdio: the handshake, every tool's schema against the
    command it runs, real calls, bad input, and cancelling."""
    out = []
    check = _checker(out)
    from sdexe import agent

    # Each tool's schema must describe arguments its command accepts.
    bad = []
    for cmd in cli_tools.COMMANDS:
        props = agent._cmd_tool(cmd)["inputSchema"]["properties"]
        sample = {}
        for arg in cmd.args:
            schema = props.get(arg.dest)
            if not schema:
                bad.append(f"{cmd.full}: {arg.flag} missing")
                continue
            sample[arg.dest] = (True if arg.type is bool else schema["enum"][-1] if "enum" in schema
                                else schema.get("minimum", schema.get("default", 2.0)) if arg.type in (int, float)
                                else "-x")
        if cmd.inputs == "none":
            sample[cmd.text_arg] = "-text"
        else:
            sample["files"] = ["a.bin", "b.bin"] if cmd.inputs == "pair" else ["a.bin"]
        sample["output"] = "out"
        extra = set(props) - set(sample)
        try:
            argv = agent.tool_argv(cmd.tool_name, sample, work)
            cli_tools.build_parser(cmd).parse_args(argv[len(cmd.full.split()):])
        except Exception as e:  # noqa: BLE001
            bad.append(f"{cmd.full}: {e}")
        if extra:
            bad.append(f"{cmd.full}: schema has {extra} the command lacks")
    check("mcp: every tool schema matches its command", not bad, "; ".join(bad))
    argv = agent.tool_argv("download", {"urls": ["-i", "/etc/passwd"], "quality": 720.0, "limit": 3.0}, work)
    check("mcp: links go after --, whole numbers stay whole",
          argv == ["download", "--quality=720", "--limit=3", "--", "-i", "/etc/passwd"], argv)

    outdir, tmp = work / "mcp-out", work / "mcp-tmp"
    tmp.mkdir()
    c = _Mcp(work, SDEXE_OUTPUT_DIR=str(outdir), TMPDIR=str(tmp))
    try:
        r = c.ask(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "0"}})
        res = r.get("result", {})
        check("mcp: initialize", res.get("protocolVersion") == "2025-06-18" and "tools" in res.get("capabilities", {})
              and res.get("serverInfo", {}).get("name") == "sdexe", r)
        c.send(method="notifications/initialized")
        r = c.ask(2, "initialize", {"protocolVersion": "1999-01-01"})
        check("mcp: an unknown protocol version gets the newest one sdexe speaks",
              r.get("result", {}).get("protocolVersion") == agent.PROTOCOL_VERSIONS[0], r)
        check("mcp: ping", c.ask(3, "ping").get("result") == {})
        listed = c.ask(4, "tools/list").get("result", {}).get("tools", [])
        names = [t["name"] for t in listed]
        check("mcp: tools/list has every command", len(names) == len(set(names)) == len(cli_tools.COMMANDS) + 3
              and all(t["inputSchema"]["type"] == "object" and t.get("description") for t in listed), len(names))

        r = c.ask(5, "tools/call", {"name": "image_resize", "arguments": {"files": [str(fx["png"])], "width": 40.0}})
        res = r.get("result", {})
        saved = (res.get("structuredContent", {}).get("results") or [{}])[0].get("outputs") or [{}]
        check("mcp: a tool call saves a file and returns its path", res.get("isError") is False
              and Path(saved[0].get("path", "/nope")).is_file() and outdir.resolve() in Path(saved[0]["path"]).parents
              and _json(res["content"][0]["text"]) == res["structuredContent"], r)
        r = c.ask(6, "tools/call", {"name": "image_info", "arguments": {"files": ["missing.png"]}})
        check("mcp: a failed call is isError with the reason", r.get("result", {}).get("isError") is True
              and "missing.png" in r["result"]["content"][0]["text"], r)
        r = c.ask(7, "tools/call", {"name": "image_qr", "arguments": {"text": "--help"}})
        check('mcp: text that looks like an option ("--help") is text', r.get("result", {}).get("isError") is False, r)
        r = c.ask(8, "tools/call", {"name": "image_resize", "arguments": {"width": 10}})
        check("mcp: a missing required argument is reported", r.get("result", {}).get("isError") is True, r)
        r = c.ask(9, "tools/call", {"name": "download", "arguments": {"urls": ["-i", "/etc/passwd"]}})
        check("mcp: a link can't smuggle in an option", r.get("result", {}).get("isError") is True
              and "root:" not in json.dumps(r), r)
        check("mcp: unknown tool", c.ask(10, "tools/call", {"name": "nope"}).get("error", {}).get("code") == -32602)
        check("mcp: unknown method", c.ask(11, "nope/nope").get("error", {}).get("code") == -32601)

        # Lines that used to end the server, or went unanswered.
        c.raw("{not json")
        c.raw("5")
        c.raw('{"jsonrpc":"2.0","id":20,"method":"initialize","params":[1]}')
        c.raw('{"jsonrpc":"2.0","id":21,"method":5}')
        c.raw('{"jsonrpc":"2.0","id":22,"result":{}}')
        c.raw('{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":[1]}}')
        c.raw('{"jsonrpc":"2.0","id":23,"method":"tools/call","params":{"name":["a"],"arguments":[]}}')
        c.raw('[{"jsonrpc":"2.0","id":24,"method":"ping"},{"jsonrpc":"2.0","id":25,"method":"ping"}]')
        got = {i: c.wait(i, 30) for i in (20, 21, 23, 24, 25)}
        check("mcp: malformed messages get errors, and the server lives on",
              got[20].get("error", {}).get("code") == -32602 and got[21].get("error", {}).get("code") == -32600
              and got[23].get("result", {}).get("isError") is True and got[24].get("result") == {}
              and got[25].get("result") == {} and 22 not in c.replies and c.p.poll() is None
              and sorted(m["error"]["code"] for m in c.stray) == [-32700, -32600], f"{got} {c.stray}")

        # Many calls at once: every reply is one whole line with its own id.
        ids = list(range(100, 112))
        for i in ids:
            c.send(id=i, method="tools/call", params={"name": "image_resize", "arguments": {
                "files": [str(fx["png"])], "width": i}})
        replies = [c.wait(i, 120) for i in ids]
        paths = {(r.get("result", {}).get("structuredContent", {}).get("results") or [{}])[0].get("outputs", [{}])[0]
                 .get("path") for r in replies}
        check("mcp: 12 calls at once all answer, to 12 different files", len(paths) == 12 and None not in paths
              and not c.garbage, f"{len(paths)} paths, garbage {c.garbage[:1]}")

        # Cancelling stops the tool and the ffmpeg it started, and cleans up.
        ff = tools.ffmpeg_path()
        if ff and os.name == "posix":
            big = work / "big-clip.mp4"
            subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=120", "-pix_fmt",
                            "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(big)], capture_output=True)

            def ffmpegs():
                ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
                return [ln for ln in ps.splitlines() if "ffmpeg" in ln and str(tmp) in ln]

            def started():
                deadline = time.time() + 30
                while not ffmpegs() and time.time() < deadline:
                    time.sleep(0.1)
                return bool(ffmpegs())

            def stopped():
                deadline = time.time() + 15
                while (ffmpegs() or any(tmp.iterdir())) and time.time() < deadline:
                    time.sleep(0.2)
                return not ffmpegs() and not any(tmp.iterdir())

            c.send(id=200, method="tools/call", params={"name": "video_reverse", "arguments": {"files": [str(big)]}})
            if started() and 200 not in c.replies:
                c.send(method="notifications/cancelled", params={"requestId": 200})
                check("mcp: cancel stops ffmpeg and removes its temp files", stopped(),
                      f"ffmpeg {len(ffmpegs())}, temp {[f.name for f in tmp.iterdir()]}")
                time.sleep(0.5)
                check("mcp: a cancelled call gets no reply", 200 not in c.replies, c.replies.get(200))
                check("mcp: still serving after a cancel", c.ask(201, "ping").get("result") == {})
                c.send(id=202, method="tools/call", params={"name": "video_reverse",
                                                            "arguments": {"files": [str(big)]}})
                if started():
                    code = c.close()
                    check("mcp: closing stdin stops running tools", code == 0 and stopped(),
                          f"exit {code}, ffmpeg {len(ffmpegs())}, temp {[f.name for f in tmp.iterdir()]}")
            else:
                out.append(("mcp: cancel", "SKIP", "the tool finished before it could be cancelled"))
    finally:
        c.close()
    return out


def _available(need: str) -> bool:
    if need == "tesseract":
        from sdexe import tools_pdf2
        return bool(tools_pdf2.tesseract_path())
    if need == "soffice":
        from sdexe import tools_pdf2
        return bool(tools_pdf2.soffice_path())
    return bool(tools.ffmpeg_exe_with_filter(need))


def main() -> int:
    global HOME
    work = Path(tempfile.mkdtemp(prefix="sdexe-cli-test-"))
    HOME = work / "home"
    HOME.mkdir()
    rows = []
    try:
        fx = make_fixtures(work)
        run_cases = cases(fx)
        covered = {c[0].split()[0] + " " + c[0].split()[1] if c[0].split()[0] != "convert" else "convert"
                   for c in run_cases}
        # Every case twice: as `sdexe …`, and through the entry the MCP server
        # uses for its tool calls, which never loads the web app.
        for case in run_cases + [(f"{c[0]} (as MCP runs it)", *c[1:]) for c in run_cases]:
            label, argv = case[0], case[1]
            need = case[2] if len(case) > 2 else None
            if need and not _available(need):
                if "MCP" not in label:
                    rows.append((label, "SKIP", f"{need} not installed"))
                continue
            r = sdexe(*argv, "--json", cwd=work, module="sdexe.cli_tools" if "MCP" in label else "sdexe")
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

        rows += settings_checks(work)
        rows += regression_checks(work, fx)
        rows += download_checks(work)
        rows += offline_checks()
        rows += integration_checks(work)
        rows += mcp_checks(work, fx)

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
