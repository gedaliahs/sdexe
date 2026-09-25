"""The terminal side of sdexe that isn't a tool: the startup screen, the guided
setup (`sdexe setup`) and the walkthrough (`sdexe tutorial`).
"""

import io
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from sdexe import __version__, media, settings, tools, ui

SAMPLE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo", 19 s, the first YouTube video


def opens_browser() -> bool:
    return bool(settings.get("open_browser"))


def needs_setup() -> bool:
    from sdexe.app import load_config
    return not load_config().get("setup_done")


def _mark_setup_done():
    from sdexe.app import load_config, save_config
    cfg = load_config()
    cfg["setup_done"] = __version__
    save_config(cfg)


# ── Prompts ──

def choose(c: Console, options: list, default: int = 0) -> int:
    """Arrow-key menu of (label, detail) rows; returns the index. Falls back to
    typing a number where raw keys aren't available."""
    if not ui.is_interactive() or os.name == "nt":
        for i, (label, detail) in enumerate(options, 1):
            c.print(f"     [brand]{i}[/brand]  {label}  [muted]{detail}[/muted]")
        while True:
            raw = c.input(f"     choose [muted]\\[{default + 1}][/muted] ").strip()
            if not raw:
                return default
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1

    import termios
    import tty

    idx = default
    out = sys.stdout
    width = max(len(label) for label, _ in options) + 3

    def draw(first=False):
        if not first:
            out.write(f"\x1b[{len(options)}A")
        for i, (label, detail) in enumerate(options):
            out.write("\x1b[2K")
            line = Text("   ")
            if i == idx:
                line.append("❯ ", style="brand")
                line.append(label.ljust(width), style="title")
                line.append(detail, style="muted")
            else:
                line.append("  " + label.ljust(width), style="faint")
                line.append(detail, style="faint")
            c.print(line, no_wrap=True, overflow="ellipsis")
        out.flush()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out.write("\x1b[?25l")
    try:
        tty.setcbreak(fd)
        draw(first=True)
        while True:
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                seq = os.read(fd, 2)
                if seq == b"[A":
                    idx = (idx - 1) % len(options)
                elif seq == b"[B":
                    idx = (idx + 1) % len(options)
            elif ch == b"k":
                idx = (idx - 1) % len(options)
            elif ch in (b"j", b"\t"):
                idx = (idx + 1) % len(options)
            elif ch.isdigit() and 1 <= int(ch) <= len(options):
                idx = int(ch) - 1
            elif ch in (b"\r", b"\n", b" "):
                break
            else:
                continue
            draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[?25h")
        out.flush()
    out.write(f"\x1b[{len(options)}A\x1b[J")
    c.print(Text.assemble(("   ", ""), ("✓ ", "ok"), (options[idx][0], "")))
    return idx


def yes_no(c: Console, default: bool = True) -> bool:
    return choose(c, [("Yes", ""), ("No", "")], 0 if default else 1) == 0


def _question(c: Console, n: int, total: int, title: str, body: str = ""):
    c.print()
    c.print(Text.assemble(("  ", ""), (f"{n}/{total} ", "faint"), (title, "title")))
    if body:
        c.print(Text.from_markup(body, style="muted"))
    c.print()


# ── System checks ──

def system_checks() -> list:
    """(ok, name, detail, fix) for ffmpeg, the downloader and the YouTube solver."""
    rows = []
    ff = tools.ffmpeg_version()
    resolved = tools.ffmpeg_path()
    bundled = bool(resolved) and resolved != shutil.which("ffmpeg")
    rows.append((bool(ff), "ffmpeg", f"{ff}{' (bundled)' if bundled else ''}" if ff else "not found",
                 None if ff else "brew install ffmpeg"))
    import yt_dlp
    from sdexe.app import _ytdlp_is_stale
    stale = _ytdlp_is_stale()
    rows.append((not stale, "yt-dlp", yt_dlp.version.__version__ + (" · out of date" if stale else ""),
                 "sdexe update" if stale else None))
    js = media.js_runtime_label()
    if js and media.ejs_installed():
        rows.append((True, "YouTube solver", js, None))
    elif js:
        rows.append((False, "YouTube solver", f"{js} · solver scripts missing", "sdexe update"))
    else:
        rows.append((False, "YouTube solver", "no JavaScript runtime", "brew install deno"))
    return rows


def _checks_table(checks) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(width=1)
    t.add_column(no_wrap=True)
    t.add_column(style="muted")
    for ok, name, detail, fix in checks:
        t.add_row(ui.status(ok if ok else None), name,
                  Text.assemble((detail, "muted"), (f"   → {fix}" if fix else "", "brand")))
    return t


# ── Startup screen ──

def _latest_version(result: dict):
    import json
    import urllib.request
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/sdexe/json", timeout=3) as r:
            result["latest"] = json.loads(r.read())["info"]["version"]
    except Exception:
        pass


def start_update_check() -> tuple:
    result = {}
    t = threading.Thread(target=_latest_version, args=(result,), daemon=True)
    t.start()
    return t, result


def _newer(latest: str, current: str) -> bool:
    def parts(v):
        return [int(x) if x.isdigit() else 0 for x in v.split(".")]
    try:
        return parts(latest) > parts(current)
    except Exception:
        return latest != current


def startup_screen(c: Console, url: str, opened: bool, port_note: str = "", update=None, tray=True):
    ui.header(c)
    c.print()
    c.print(Text.assemble(("  ● ", "ok"), ("running at ", "muted"), (url, "link")))
    c.print(Text("    opened in your browser" if opened else
                 "    not opened · ⌘-click the link, or turn on Open the browser in sdexe settings", style="faint"))
    if port_note:
        c.print(Text(f"    {port_note}", style="warn"))
    c.print()

    checks = system_checks()
    if all(ok for ok, *_ in checks):
        names = " · ".join(f"{name} {detail}" for _, name, detail, _ in checks)
        c.print(Text.assemble(("  ✓ ", "ok"), (names, "muted")))
    else:
        c.print(ui._indent(_checks_table(checks), 2))
    if update and update.get("latest") and _newer(update["latest"], __version__):
        c.print(Text.assemble(("  ↑ ", "warn"), (f"sdexe {update['latest']} is out", ""),
                              (f" · you have {__version__} · ", "muted"), ("sdexe update", "brand")))
    c.print()
    c.print(ui.section("From another tab"))
    c.print(ui.rows([
        ('sdexe download "<link>"', "save video or audio"),
        ("sdexe pdf merge a.pdf b.pdf", "and every image, audio, video, file tool"),
        ("sdexe settings", "defaults, colours, Claude Code, startup"),
        ("sdexe tutorial", "3-minute hands-on walkthrough"),
    ], key_width=28))
    c.print()
    stop = [("ctrl+c", "stop")]
    if tray:
        stop.append(("menu bar", "Open · Quit"))
    c.print(ui.keys(*stop))
    c.print()


# ── Setup ──

def setup_main(argv) -> int:
    c = ui.console()
    if argv and argv[0] in ("-h", "--help"):
        c.print("[title]sdexe setup[/title] [muted]· the guided questions: system check, browser, download "
                "quality, zsh links, Claude Code. Run it any time; for everything else there's[/muted] "
                "[brand]sdexe settings[/brand][muted].[/muted]")
        return 0
    if not ui.is_interactive():
        c.print("sdexe setup needs an interactive terminal. Scripts can use: sdexe settings set KEY VALUE")
        return 2
    try:
        run_setup(c)
    except (KeyboardInterrupt, EOFError):
        c.print("\n  [muted]Setup stopped. Everything answered so far is saved. Finish with[/muted] "
                "[brand]sdexe setup[/brand]\n")
        return 130
    return 0


def run_setup(c: Console, first_run: bool = False):
    ui.header(c, "setup")
    c.print()
    if first_run:
        c.print(Text("  Welcome. A few quick questions, and sdexe is ready.", style="title"))
        c.print(Text("  Everything runs on this computer: nothing is uploaded.", style="muted"))
    else:
        c.print(Text("  Each answer starts on what you have now: Enter keeps it.", style="muted"))

    # System
    c.print()
    c.print(ui.section("Your system"))
    checks = system_checks()
    c.print(ui._indent(_checks_table(checks), 4))
    for ok, name, detail, fix in checks:
        if ok:
            continue
        if name == "ffmpeg":
            c.print("\n  ffmpeg is needed for audio and video. Install it now?")
            if yes_no(c):
                from sdexe.app import install_ffmpeg
                with c.status("  installing ffmpeg, this can take a few minutes…", spinner="dots"):
                    done, msg = install_ffmpeg()
                c.print(Text.assemble(("   ", ""), ui.status(done), (f" {msg}", "")))
        elif fix == "sdexe update":
            c.print(f"\n  {name} needs an update. Do it now?")
            if yes_no(c):
                from sdexe.app import _pip_install
                with c.status("  updating yt-dlp and its YouTube solver…", spinner="dots"):
                    done, out = _pip_install("yt-dlp[default]")
                c.print(Text.assemble(("   ", ""), ui.status(done),
                                      (" updated · applies next time sdexe starts" if done else
                                       f" {out.splitlines()[-1] if out else 'update failed'}", "")))

    rc = settings.zshrc()
    has_claude = shutil.which("claude") is not None
    total = 2 + bool(rc) + has_claude
    n = 0

    # Browser
    n += 1
    _question(c, n, total, "When you run sdexe, open the web app in your browser?",
              "  The terminal commands work either way. One run can override it with --browser or --no-browser.")
    now = opens_browser()
    pick = choose(c, [("Yes, open it", "the tools page opens every time"),
                      ("No, just start it", "sdexe prints its address; open it when you want")], 0 if now else 1)
    settings.put("open_browser", pick == 0)

    # Download quality
    n += 1
    _question(c, n, total, "What quality should video downloads aim for?",
              "  A ceiling: sdexe takes the best a video offers up to this. Tags like -720p override it.")
    quals = settings.BY_KEY["dl_quality"].choices
    current = settings.get("dl_quality")
    keys = [v for v, _ in quals]
    pick = choose(c, [(label.split(" · ")[0][:1].upper() + label.split(" · ")[0][1:],
                       label.split(" · ")[1] if " · " in label else "")
                      for _, label in quals], keys.index(current) if current in keys else 3)
    settings.put("dl_quality", keys[pick])

    # zsh
    if rc:
        n += 1
        if settings.zsh_alias_on():
            _question(c, n, total, "Links without quotes is on.",
                      "  zsh would otherwise treat the ? in YouTube links as a wildcard.")
            if choose(c, [("Keep it", ""), ("Turn it off", "you'll need quotes around links")]) == 1:
                c.print(Text("   " + settings.set_zsh_alias(False), style="muted"))
        else:
            _question(c, n, total, "Paste links without quotes?",
                      "  zsh treats the ? in YouTube links as a wildcard, so an unquoted link fails with\n"
                      "  \"no matches found\". This adds [brand]alias sdexe='noglob sdexe'[/brand] to "
                      f"~/{rc.name}.")
            if yes_no(c):
                c.print(Text("   " + settings.set_zsh_alias(True), style="muted"))
            else:
                c.print(Text('   Put links in quotes: sdexe download "https://…"', style="muted"))

    # Claude Code
    if has_claude:
        n += 1
        with c.status("  checking Claude Code…", spinner="dots"):
            mcp = settings.claude_mcp_on()
        skill = settings.skill_on()
        _question(c, n, total, "Let Claude Code use sdexe?",
                  "  Claude can then download media and run every sdexe tool, in any project.")
        if mcp:
            if choose(c, [("Keep it connected", "as an MCP server"), ("Disconnect", "claude mcp remove sdexe")]) == 1:
                c.print(Text("   " + settings.set_claude_mcp(False), style="muted"))
        else:
            opts = [("Connect as an MCP server", "recommended · claude mcp add -s user sdexe"),
                    ("Keep the skill" if skill else "Install as a skill", "~/.claude/skills/sdexe"),
                    ("Not now", "")]
            pick = choose(c, opts, 1 if skill else 0)
            if pick == 0:
                with c.status("  connecting…", spinner="dots"):
                    msg = settings.set_claude_mcp(True)
                c.print(Text("   " + msg, style="muted"))
            elif pick == 1 and not skill:
                c.print(Text("   " + settings.set_skill(True), style="muted"))

    _mark_setup_done()
    c.print()
    quality = settings.BY_KEY["dl_quality"].show(settings.get("dl_quality"))
    c.print(ui.card(Group(
        Text("You're set.", style="ok.bold"),
        Text(""),
        ui.rows([
            ("sdexe", "start the web app" + ("" if settings.get("open_browser") else " · without the browser")),
            ('sdexe download "<link>"', f"save a video or song · {quality}"),
            ("sdexe settings", "everything else: formats, folder, colours, startup"),
            ("sdexe tutorial", "learn it all in 3 minutes"),
        ], key_width=24, indent=0),
    ), padding=(1, 3)))
    if first_run:
        return
    c.print("\n  Take the tutorial now?")
    if yes_no(c, default=False):
        run_tutorial(c)


# ── Tutorial ──

def _run(argv, cwd):
    """Run an sdexe command visibly, as the user would type it."""
    p = subprocess.Popen([sys.executable, "-m", "sdexe", *argv], cwd=cwd)
    while True:
        try:
            return p.wait()
        except KeyboardInterrupt:
            continue  # the child got the same Ctrl+C and is stopping


def _shell_quote(arg: str) -> str:
    return f'"{arg}"' if any(ch in arg for ch in " ?&*") else arg


def _make_samples(folder: Path):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1600, 1000))
    draw = ImageDraw.Draw(img)
    for y in range(1000):
        draw.line([(0, y), (1600, y)], fill=(40 + y // 8, 90 + y // 12, 200 - y // 10))
    draw.text((80, 460), "sdexe tutorial photo", fill="white")
    img.save(folder / "photo.jpg", quality=92)

    from pypdf import PdfWriter
    for name, pages, label in (("chapter-1.pdf", 2, "Chapter 1"), ("chapter-2.pdf", 3, "Chapter 2")):
        w = PdfWriter()
        for _ in range(pages):
            w.add_blank_page(width=595, height=842)
        buf = io.BytesIO()
        w.write(buf)
        buf.seek(0)
        (folder / name).write_bytes(tools.watermark_pdf(buf, label, font_size=48, opacity=0.8))
    (folder / "people.csv").write_text("name,city\nAda,London\nGrace,New York\nLinus,Helsinki\n")


def _home(p: Path) -> str:
    return str(p).replace(str(Path.home()), "~", 1)


def _tutorial_steps(folder: Path) -> list:
    """(title, body markup, [argv to run])."""
    link = SAMPLE_URL
    return [
        ("Welcome",
         "sdexe works three ways, all on this computer:\n\n"
         "  [title]The web app[/title]     run [brand]sdexe[/brand] and use the tools in your browser\n"
         "  [title]The terminal[/title]    every tool is a command, like [brand]sdexe pdf merge[/brand]\n"
         "  [title]AI agents[/title]       Claude and other apps can call sdexe directly\n\n"
         f"This tutorial runs real commands in [title]{_home(folder)}[/title], so you can open the results.\n"
         "[key]enter[/key] runs each example · [key]s[/key] skips it · [key]q[/key] quits",
         []),
        ("Download a video",
         "Give [brand]sdexe download[/brand] a link and you get an MP4 at the best quality up to your setting\n"
         "(1080p60 unless you changed it). YouTube, TikTok, Instagram, SoundCloud, Vimeo, X and 1000+ more.\n\n"
         "[muted]Put links in quotes: zsh otherwise trips on the ? in them (sdexe setup can fix that).\n"
         "This is the first video ever uploaded to YouTube, 19 seconds long.[/muted]",
         [["download", link]]),
        ("Audio, and choosing quality",
         "Tags change the format or quality for one download:\n\n"
         "  [brand2]-mp3  -wav  -flac  -m4a[/brand2]      audio in that format [muted]· mp3 is 320 kbps[/muted]\n"
         "  [brand2]-a[/brand2]                       audio only, lossless WAV\n"
         "  [brand2]-720p  -4k  -1080p30[/brand2]     cap the resolution or frame rate\n"
         "  [brand2]--best[/brand2]                   the highest quality there is\n"
         "  [brand2]--start 1:30 --end 2:00[/brand2]  only that part\n\n"
         "Your defaults live in [brand]sdexe settings[/brand]. Now just the audio, as MP3:",
         [["download", link, "-mp3"]]),
        ("Look before you download",
         "[brand]sdexe info[/brand] shows everything a link offers, every quality with its size, chapters and\n"
         "subtitles, and exactly what [brand]download[/brand] would pick. Nothing is downloaded.",
         [["info", link]]),
        ("Many at once",
         "Several links download together, three at a time, and one broken link doesn't stop the rest:\n\n"
         '  [brand]sdexe download[/brand] [brand2]"LINK1" "LINK2" "LINK3" -mp3[/brand2]\n'
         "  [brand]sdexe download[/brand] [brand2]-i links.txt[/brand2]                  [muted]one per line[/muted]\n"
         '  [brand]sdexe download[/brand] [brand2]"PLAYLIST" --playlist --limit 10[/brand2]  '
         "[muted]first 10 of a playlist[/muted]\n\n"
         "Nothing to run here. On to your own files.",
         []),
        ("PDFs",
         "Merge, split, compress, pull out text, rotate, watermark, add passwords, and more.\n"
         "The tutorial folder has two short PDFs. Merge them, then read the text back out:",
         [["pdf", "merge", "chapter-1.pdf", "chapter-2.pdf", "-o", "book.pdf"], ["pdf", "text", "book.pdf"]]),
        ("Images and data",
         "Images resize, compress, convert (iPhone HEIC too) and crop, many at once with [brand2]*.jpg[/brand2].\n"
         "[brand]sdexe convert[/brand] turns csv, json, yaml, xml, toml, markdown and Excel into each other.",
         [["image", "resize", "photo.jpg", "--width", "600"], ["convert", "people.csv", "-f", "json"]]),
        ("Audio and video files",
         "The same pattern works on media you already have:\n\n"
         "  [brand]sdexe audio trim[/brand] [brand2]song.mp3 --start 0:30 --end 1:00[/brand2]\n"
         "  [brand]sdexe video gif[/brand] [brand2]clip.mp4 --width 480[/brand2]\n"
         "  [brand]sdexe video audio[/brand] [brand2]talk.mp4 -f mp3[/brand2]    [muted]pull out the soundtrack[/muted]\n\n"
         "Turn the video from step 2 into a GIF:",
         [["video", "gif", "Me at the zoo.mp4", "--width", "320"]]),
        ("For scripts and AI agents",
         "Every command follows the same rules, so scripts and agents can rely on them:\n\n"
         "  • results are saved next to you, never over an existing file\n"
         "  • [brand2]--json[/brand2] gives one machine-readable result\n"
         "  • exit code 0 means everything worked\n\n"
         "[brand]sdexe mcp[/brand] hands every tool to Claude, Cursor and other AI apps; [brand]sdexe settings[/brand]\n"
         "can connect Claude Code for you. Here is --json:",
         [["image", "info", "photo.jpg", "--json"]]),
        ("The app, and your settings",
         "Run [brand]sdexe[/brand] on its own for a clickable app right here in the terminal (buttons for\n"
         "download, search, files and settings) plus the web app in your browser, with drag-and-drop.\n\n"
         "  [brand]sdexe[/brand]                  starts it, and opens the browser if you chose that\n"
         "  [brand]sdexe[/brand] [brand2]--browser[/brand2]        opens the browser this time\n"
         "  [brand]sdexe[/brand] [brand2]--no-browser[/brand2]     doesn't, this time\n"
         "  [brand]sdexe settings[/brand]         default quality and formats, download folder, colours,\n"
         "                         Claude Code, and what happens on start\n\n"
         "Every command has [brand2]--help[/brand2]. [brand]sdexe --help[/brand] lists them all.",
         []),
    ]


def _key(c: Console, prompt) -> str:
    try:
        return c.input(prompt).strip().lower()
    except EOFError:
        return "q"


def run_tutorial(c: Console, folder: Path | None = None):
    folder = folder or Path.home() / "sdexe-tutorial"
    steps = _tutorial_steps(folder)
    live = ui.is_interactive()
    if live:
        folder.mkdir(parents=True, exist_ok=True)
        _make_samples(folder)
        ui.header(c, "tutorial")

    for i, (title, body, runs) in enumerate(steps, 1):
        c.print()
        progress = Text()
        progress.append("━" * i, style="brand")
        progress.append("━" * (len(steps) - i), style="faint")
        progress.append(f"  {i}/{len(steps)}", style="faint")
        c.print(ui.card(Group(Text(title, style="brand.bold"), Text(""), Text.from_markup(body), Text(""), progress),
                        padding=(1, 3), expand=True))
        for argv in runs:
            line = "sdexe " + " ".join(_shell_quote(a) for a in argv)
            if not live:
                c.print(Text.assemble(("  $ ", "faint"), ui.cmd(line)))
                continue
            prompt = Text.assemble(("\n  $ ", "faint"), ui.cmd(line), ("   ", ""),
                                   ("enter", "key"), (" run  ", "muted"), ("s", "key"), (" skip  ", "muted"),
                                   ("q", "key"), (" quit ", "muted"))
            ans = _key(c, prompt)
            if ans == "q":
                return _tutorial_end(c, folder, finished=False)
            if ans == "s":
                continue
            c.print()
            if _run(argv, folder) not in (0, None):
                c.print(Text("  That didn't work here, which is fine for the tutorial. Carry on.", style="muted"))
        if live and i < len(steps):
            ans = _key(c, Text.assemble(("\n  ", ""), ("enter", "key"), (" next step  ", "muted"),
                                        ("q", "key"), (" quit ", "muted")))
            if ans == "q":
                return _tutorial_end(c, folder, finished=False)
    if live:
        _tutorial_end(c, folder, finished=True)


def _tutorial_end(c: Console, folder: Path, finished: bool):
    c.print()
    if finished:
        c.print(ui.card(Group(
            Text("That's everything.", style="ok.bold"), Text(""),
            ui.rows([
                ('sdexe download "<link>" [-mp3|-a|-720p|--best]', ""),
                ('sdexe info "<link>"', ""),
                ("sdexe pdf | image | audio | video | convert | file", "each lists its commands"),
                ("sdexe settings", "your defaults"),
                ("sdexe --help", "everything"),
            ], indent=0),
        ), padding=(1, 3)))
    if folder.exists() and any(folder.iterdir()):
        c.print(f"\n  The tutorial's files are in [title]{_home(folder)}[/title]. Delete them?")
        if yes_no(c, default=False):
            shutil.rmtree(folder, ignore_errors=True)
            c.print(Text("   deleted", style="muted"))
    c.print()


def tutorial_main(argv) -> int:
    c = ui.console()
    if argv and argv[0] in ("-h", "--help"):
        c.print("[title]sdexe tutorial[/title] [muted]· a hands-on walkthrough of downloads, the file tools, agents "
                "and the web app. Runs real commands in ~/sdexe-tutorial.[/muted]")
        return 0
    try:
        run_tutorial(c)
    except KeyboardInterrupt:
        c.print("\n  [muted]Tutorial stopped. Pick it up again with[/muted] [brand]sdexe tutorial[/brand]\n")
        return 130
    return 0
