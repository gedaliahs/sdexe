"""The terminal side of sdexe that isn't a tool: the startup screen, the
first-run setup (`sdexe setup`) and the walkthrough (`sdexe tutorial`).
"""

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sdexe import __version__, media, tools

ACCENT = "cyan"
SAMPLE_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo", 19 s, the first YouTube video


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _config():
    from sdexe.app import load_config
    return load_config()


def _save_config(**updates):
    from sdexe.app import load_config, save_config
    cfg = load_config()
    cfg.update(updates)
    save_config(cfg)


def opens_browser(cfg=None) -> bool:
    """The saved answer to "open the web app in your browser when you run sdexe?"."""
    cfg = _config() if cfg is None else cfg
    return cfg.get("open_browser", True) is not False


def needs_setup() -> bool:
    return not _config().get("setup_done")


# ── Prompts ──

def choose(console: Console, options: list, default: int = 0) -> int:
    """Arrow-key menu of (label, detail) rows. Returns the chosen index.
    Falls back to typing a number when the terminal can't do raw keys."""
    if not _interactive() or os.name == "nt":
        for i, (label, detail) in enumerate(options, 1):
            console.print(f"     [{ACCENT}]{i}[/{ACCENT}]  {label}  [dim]{detail}[/dim]")
        while True:
            raw = console.input(f"     choose [dim]\\[{default + 1}][/dim] ").strip()
            if not raw:
                return default
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1

    import termios
    import tty

    idx = default
    out = sys.stdout
    width = max(len(label) for label, _ in options) + 2

    def draw(first=False):
        if not first:
            out.write(f"\x1b[{len(options)}A")
        for i, (label, detail) in enumerate(options):
            out.write("\x1b[2K")
            if i == idx:
                console.print(f"   [{ACCENT}]❯[/{ACCENT}] [bold]{label.ljust(width)}[/bold][dim]{detail}[/dim]",
                              no_wrap=True, overflow="ellipsis")
            else:
                console.print(f"     {label.ljust(width)}[dim]{detail}[/dim]", no_wrap=True, overflow="ellipsis",
                              style="bright_black")
        out.flush()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out.write("\x1b[?25l")
    try:
        tty.setcbreak(fd)  # keys arrive one at a time; Ctrl+C still interrupts
        draw(first=True)
        while True:
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                seq = os.read(fd, 2)
                if seq == b"[A":
                    idx = (idx - 1) % len(options)
                elif seq == b"[B":
                    idx = (idx + 1) % len(options)
            elif ch in (b"k",):
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
    # Collapse the menu to the answer.
    out.write(f"\x1b[{len(options)}A\x1b[J")
    console.print(f"   [green]✓[/green] {options[idx][0]}")
    return idx


def yes_no(console: Console, default: bool = True) -> bool:
    return choose(console, [("Yes", ""), ("No", "")], 0 if default else 1) == 0


def _step(console, n, total, title, body=""):
    console.print(f"\n [dim]{n}/{total}[/dim]  [bold]{title}[/bold]")
    if body:
        console.print(Text.from_markup(body), style="default")
    console.print()


# ── System checks ──

def system_checks() -> list:
    """(ok, name, detail, fix) rows for the startup screen and setup."""
    rows = []
    ff = tools.ffmpeg_version()
    resolved = tools.ffmpeg_path()
    bundled = bool(resolved) and resolved != shutil.which("ffmpeg")
    rows.append((bool(ff), "ffmpeg", f"{ff}{' (bundled)' if bundled else ''}" if ff else "not found",
                 None if ff else "brew install ffmpeg"))
    import yt_dlp
    from sdexe.app import _ytdlp_is_stale
    stale = _ytdlp_is_stale()
    rows.append((not stale, "yt-dlp", yt_dlp.version.__version__ + (" (out of date)" if stale else ""),
                 "sdexe update" if stale else None))
    js = media.js_runtime_label()
    if js and media.ejs_installed():
        rows.append((True, "YouTube solver", js, None))
    elif js:
        rows.append((False, "YouTube solver", f"{js}, solver scripts missing", "sdexe update"))
    else:
        rows.append((False, "YouTube solver", "no JavaScript runtime", "brew install deno"))
    return rows


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


def startup_screen(console: Console, url: str, opened: bool, port_note: str = "", update=None, tray=True):
    head = Table.grid(padding=(0, 1))
    head.add_column()
    head.add_row(Text.assemble(("sdexe", f"bold {ACCENT}"), ("  ", ""), (f"v{__version__}", "dim"),
                               ("   local tools for media, PDF, images & files", "dim")))
    head.add_row("")
    head.add_row(Text.assemble(("● ", "green"), ("Running at  ", ""), (url, f"bold underline {ACCENT}")))
    head.add_row(Text("  opened in your browser" if opened else "  not opened in the browser; open the link when you want it",
                      style="dim"))
    if port_note:
        head.add_row(Text(f"  {port_note}", style="yellow"))

    checks = Table.grid(padding=(0, 2))
    checks.add_column()
    checks.add_column()
    for ok, name, detail, fix in system_checks():
        mark = Text("✓", style="green") if ok else Text("!", style="yellow")
        line = Text.assemble((f"{name}  ", "bold" if not ok else ""), (detail, "dim"))
        if fix:
            line.append(f"   → {fix}", style=ACCENT)
        checks.add_row(mark, line)
    if update and update.get("latest") and _newer(update["latest"], __version__):
        checks.add_row(Text("↑", style="yellow"),
                       Text.assemble(("Update available  ", "bold"), (f"{__version__} → {update['latest']}", "dim"),
                                     ("   → sdexe update", ACCENT)))

    cmds = Table.grid(padding=(0, 3))
    cmds.add_column(style=ACCENT, no_wrap=True)
    cmds.add_column(style="dim")
    for c, d in (('sdexe download "<link>"', "save video or audio, MP4 1080p60 by default"),
                 ("sdexe pdf merge a.pdf b.pdf", "and image, audio, video, convert, file tools"),
                 ("sdexe tutorial", "a 3-minute hands-on walkthrough"),
                 ("sdexe --help", "everything else")):
        cmds.add_row(c, d)

    body = Group(head, Text(""), checks, Text(""),
                 Text("From another terminal tab", style="bold"), cmds)
    console.print()
    console.print(Panel(body, border_style="bright_black", padding=(1, 3), expand=False))
    stop = "Ctrl+C to stop" + (" · or Quit from the menu bar icon" if tray else "")
    console.print(f"  [dim]{stop}[/dim]\n")


# ── Setup ──

def _zshrc() -> Path | None:
    if os.path.basename(os.environ.get("SHELL", "")) != "zsh":
        return None
    return Path(os.environ.get("ZDOTDIR", Path.home())) / ".zshrc"


def zsh_alias_installed(rc: Path) -> bool:
    try:
        return "noglob sdexe" in rc.read_text()
    except OSError:
        return False


def add_zsh_alias(rc: Path):
    with open(rc, "a") as f:
        f.write("\n# sdexe: let links with ? and & through without quotes\nalias sdexe='noglob sdexe'\n")


def _sdexe_exe() -> list:
    exe = shutil.which("sdexe")
    return [exe] if exe else [sys.executable, "-m", "sdexe"]


def claude_has_sdexe() -> bool:
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        return subprocess.run([claude, "mcp", "get", "sdexe"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def add_to_claude() -> tuple:
    claude = shutil.which("claude")
    r = subprocess.run([claude, "mcp", "add", "-s", "user", "sdexe", "--", *_sdexe_exe(), "mcp"],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def setup_main(argv) -> int:
    console = Console(highlight=False)
    if argv and argv[0] in ("-h", "--help"):
        console.print("[bold]sdexe setup[/bold] [dim]· check your system and choose how sdexe starts. "
                      "Safe to run again any time.[/dim]")
        return 0
    if not _interactive():
        console.print("sdexe setup needs an interactive terminal.")
        return 2
    try:
        run_setup(console)
    except (KeyboardInterrupt, EOFError):
        console.print("\n  [dim]Setup stopped. Run[/dim] [cyan]sdexe setup[/cyan] [dim]to finish it later.[/dim]\n")
        return 130
    return 0


def run_setup(console: Console, first_run: bool = False):
    cfg = _config()
    console.print()
    console.print(Panel(
        Group(Text.assemble(("Welcome to sdexe", "bold"), ("  ", ""), (f"v{__version__}", "dim")),
              Text("Download video and audio, and work with PDFs, images and media files.\n"
                   "Everything runs on this computer: nothing is uploaded.", style="dim")),
        border_style=ACCENT, padding=(1, 3), expand=False))
    if first_run:
        console.print("  [dim]First run: a few quick questions. Change them later with[/dim] "
                      f"[{ACCENT}]sdexe setup[/{ACCENT}][dim].[/dim]")

    # System
    console.print("\n  [bold]Checking your system[/bold]\n")
    checks = system_checks()
    for ok, name, detail, fix in checks:
        mark = "[green]✓[/green]" if ok else "[yellow]![/yellow]"
        console.print(f"   {mark} {name}  [dim]{detail}[/dim]")
    for ok, name, detail, fix in checks:
        if ok:
            continue
        if name == "ffmpeg":
            console.print("\n  ffmpeg is needed for audio and video. Install it now?")
            if yes_no(console):
                from sdexe.app import install_ffmpeg
                with console.status("  Installing ffmpeg (can take a few minutes)...", spinner="dots"):
                    done, msg = install_ffmpeg()
                console.print(f"   {'[green]✓[/green]' if done else '[red]✗[/red]'} {msg}")
        elif fix == "sdexe update":
            console.print(f"\n  {name}: {detail}. Update the downloader engine now?")
            if yes_no(console):
                from sdexe.app import _pip_install
                with console.status("  Updating yt-dlp and its YouTube solver...", spinner="dots"):
                    done, out = _pip_install("yt-dlp[default]")
                console.print("   [green]✓[/green] Updated. Takes effect next time sdexe starts." if done
                              else f"   [red]✗[/red] {out.splitlines()[-1] if out else 'Update failed'}")
        elif fix:
            console.print(f"\n   [yellow]![/yellow] {name}: {detail}. Fix with [{ACCENT}]{fix}[/{ACCENT}] when convenient.")

    questions = ["browser"]
    rc = _zshrc()
    if rc and not zsh_alias_installed(rc):
        questions.append("zsh")
    if shutil.which("claude"):
        questions.append("claude")
    total = len(questions)

    # 1. Browser
    _step(console, 1, total, "When you run sdexe, open the web app in your browser?",
          "   [dim]The terminal commands (sdexe download, sdexe pdf ...) work either way.\n"
          "   One run can always override it: sdexe --browser or sdexe --no-browser.[/dim]")
    open_it = choose(console, [
        ("Yes, open the browser", "the tools page opens every time"),
        ("No, don't open it", "sdexe starts and shows its address; open it when you want"),
    ], 0 if opens_browser(cfg) else 1) == 0
    _save_config(open_browser=open_it)
    n = 1

    # 2. zsh globbing
    if "zsh" in questions:
        n += 1
        _step(console, n, total, "Paste links without quotes?",
              "   [dim]zsh treats the ? in YouTube links as a wildcard, so\n"
              "   sdexe download https://youtube.com/watch?v=... fails with \"no matches found\".\n"
              f"   This adds one line to {rc.name}:[/dim] [{ACCENT}]alias sdexe='noglob sdexe'[/{ACCENT}]")
        if yes_no(console):
            add_zsh_alias(rc)
            console.print(f"   [dim]Open a new terminal tab (or run[/dim] [{ACCENT}]source ~/{rc.name}[/{ACCENT}][dim]) "
                          "for it to apply.[/dim]")
        else:
            console.print("   [dim]Fine. Put links in quotes: sdexe download \"https://...\"[/dim]")

    # 3. Claude Code
    if "claude" in questions:
        n += 1
        already = claude_has_sdexe()
        _step(console, n, total, "Let Claude Code use sdexe?",
              "   [dim]Adds sdexe as an MCP server, so Claude can download media and run every\n"
              "   tool directly, in any project.[/dim]" + ("\n   [green]Already added.[/green]" if already else ""))
        if not already:
            pick = choose(console, [
                ("Add sdexe to Claude Code", "claude mcp add -s user sdexe -- sdexe mcp"),
                ("Install as a skill instead", "~/.claude/skills/sdexe/SKILL.md, Claude runs the CLI"),
                ("Not now", "run sdexe setup again any time"),
            ])
            if pick == 0:
                with console.status("  Adding to Claude Code...", spinner="dots"):
                    done, msg = add_to_claude()
                console.print("   [green]✓[/green] Added. Start a new Claude Code session to use it." if done
                              else f"   [red]✗[/red] {msg}")
            elif pick == 1:
                from sdexe.agent import skill_markdown
                dest = Path.home() / ".claude" / "skills" / "sdexe" / "SKILL.md"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(skill_markdown(), encoding="utf-8")
                console.print(f"   [green]✓[/green] Saved {str(dest).replace(str(Path.home()), '~')}")

    _save_config(setup_done=__version__)
    console.print()
    console.print(Panel(
        Group(Text("You're set up.", style="bold green"), Text(""),
              Text.assemble(("  sdexe                ", ACCENT), ("start the web app" + ("" if open_it else " (without opening the browser)"), "dim")),
              Text.assemble(('  sdexe download "…"   ', ACCENT), ("save a video or song", "dim")),
              Text.assemble(("  sdexe tutorial       ", ACCENT), ("learn everything in 3 minutes", "dim")),
              Text.assemble(("  sdexe setup          ", ACCENT), ("change these answers", "dim"))),
        border_style="green", padding=(1, 3), expand=False))
    if first_run:
        console.print(f"\n  [dim]New here? Run[/dim] [{ACCENT}]sdexe tutorial[/{ACCENT}] [dim]any time for a walkthrough.[/dim]")
        return
    console.print("\n  Take the tutorial now?")
    if yes_no(console, default=False):
        run_tutorial(console)


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
    return f'"{arg}"' if any(c in arg for c in " ?&*") else arg


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
        buf = __import__("io").BytesIO()
        w.write(buf)
        buf.seek(0)
        (folder / name).write_bytes(tools.watermark_pdf(buf, label, font_size=48, opacity=0.8))
    (folder / "people.csv").write_text("name,city\nAda,London\nGrace,New York\nLinus,Helsinki\n")


def _tutorial_steps(folder: Path) -> list:
    """(title, body, [commands to run]). Commands are argv lists."""
    link = SAMPLE_URL
    return [
        ("Welcome",
         "sdexe works three ways, all on this computer:\n\n"
         "  [bold]The web app[/bold]      run [cyan]sdexe[/cyan], use the tools in your browser\n"
         "  [bold]The terminal[/bold]     every tool is a command, like [cyan]sdexe pdf merge[/cyan]\n"
         "  [bold]AI agents[/bold]        Claude and other apps can call sdexe directly\n\n"
         f"This tutorial runs real commands in [bold]{_home(folder)}[/bold], so you can look at the results.\n"
         "Press [bold]Enter[/bold] to run each example, [bold]s[/bold] to skip it, [bold]q[/bold] to quit.",
         []),
        ("Download a video",
         "Give [cyan]sdexe download[/cyan] a link. You get an MP4, the best quality up to 1080p at 60fps.\n"
         "It works with YouTube, TikTok, Instagram, SoundCloud, Vimeo, X and 1000+ other sites.\n\n"
         "[dim]Tip: put links in quotes. zsh otherwise chokes on the ? in them (sdexe setup can fix that).[/dim]\n"
         "This one is the first video ever uploaded to YouTube: 19 seconds, about 1 MB.",
         [["download", link]]),
        ("Audio, and choosing quality",
         "Add a tag to pick the format or quality:\n\n"
         "  [cyan]-mp3[/cyan]  [cyan]-wav[/cyan]  [cyan]-flac[/cyan]  [cyan]-m4a[/cyan]      audio in that format [dim](mp3 is 320 kbps)[/dim]\n"
         "  [cyan]-a[/cyan]                    audio only, lossless WAV\n"
         "  [cyan]-720p[/cyan]  [cyan]-4k[/cyan]  [cyan]-1080p30[/cyan]    cap the resolution or frame rate\n"
         "  [cyan]--best[/cyan]                the highest quality available, no cap\n"
         "  [cyan]--start 1:30 --end 2:00[/cyan]   only that part\n\n"
         "Let's grab just the audio as an MP3:",
         [["download", link, "-mp3"]]),
        ("Look before you download",
         "[cyan]sdexe info[/cyan] shows what a link offers (every quality and its size, chapters,\n"
         "subtitles) and exactly what [cyan]download[/cyan] would pick. Nothing is downloaded.",
         [["info", link]]),
        ("Many at once",
         "Pass several links to download them together, three at a time:\n\n"
         '  [cyan]sdexe download "LINK1" "LINK2" "LINK3" -mp3[/cyan]\n'
         "  [cyan]sdexe download -i links.txt[/cyan]                 [dim]one link per line[/dim]\n"
         '  [cyan]sdexe download "PLAYLIST" --playlist --limit 10[/cyan]  [dim]first 10 of a playlist[/dim]\n\n'
         "One broken link doesn't stop the rest. Nothing to run here, on to files.",
         []),
        ("PDFs",
         "The PDF tools merge, split, compress, pull out text, rotate, watermark, add passwords and more.\n"
         "The tutorial folder has two short PDFs. Merge them, then read the text back out:",
         [["pdf", "merge", "chapter-1.pdf", "chapter-2.pdf", "-o", "book.pdf"], ["pdf", "text", "book.pdf"]]),
        ("Images and data",
         "Images resize, compress, convert (iPhone HEIC too), crop and more. Pass many at once, like [cyan]*.jpg[/cyan].\n"
         "[cyan]sdexe convert[/cyan] turns csv, json, yaml, xml, toml, markdown and Excel into each other.",
         [["image", "resize", "photo.jpg", "--width", "600"], ["convert", "people.csv", "-f", "json"]]),
        ("Audio and video files",
         "The same pattern works on media files you already have:\n\n"
         "  [cyan]sdexe audio trim song.mp3 --start 0:30 --end 1:00[/cyan]\n"
         "  [cyan]sdexe video gif clip.mp4 --width 480[/cyan]\n"
         "  [cyan]sdexe video audio talk.mp4 -f mp3[/cyan]          [dim]pull out the soundtrack[/dim]\n\n"
         "Let's turn the video from step 2 into a GIF:",
         [["video", "gif", "Me at the zoo.mp4", "--width", "320"]]),
        ("For scripts and AI agents",
         "Every command follows the same rules, so scripts and agents can rely on them:\n\n"
         "  • Results are saved next to you, never over an existing file.\n"
         "  • Add [cyan]--json[/cyan] for one machine-readable result.\n"
         "  • Exit code 0 means everything worked.\n\n"
         "[cyan]sdexe mcp[/cyan] makes every tool available to Claude, Cursor and other AI apps\n"
         "([cyan]sdexe setup[/cyan] can connect Claude Code for you). Here is --json:",
         [["image", "info", "photo.jpg", "--json"]]),
        ("The web app",
         "Run [cyan]sdexe[/cyan] on its own to start the web app, with drag-and-drop for all of this.\n\n"
         "  [cyan]sdexe[/cyan]                opens it in your browser, or not, as you chose in setup\n"
         "  [cyan]sdexe --no-browser[/cyan]   start it without opening the browser this time\n"
         "  [cyan]sdexe --browser[/cyan]      start it and open the browser this time\n"
         "  [cyan]sdexe setup[/cyan]          change that choice (also on the web Settings page)\n\n"
         "Every command has [cyan]--help[/cyan]. [cyan]sdexe --help[/cyan] lists them all.",
         []),
    ]


def _home(p: Path) -> str:
    return str(p).replace(str(Path.home()), "~", 1)


def _key(console: Console, prompt: str) -> str:
    try:
        return console.input(prompt).strip().lower()
    except EOFError:
        return "q"


def run_tutorial(console: Console, folder: Path | None = None):
    folder = folder or Path.home() / "sdexe-tutorial"
    steps = _tutorial_steps(folder)
    live = _interactive()

    if live:
        folder.mkdir(parents=True, exist_ok=True)
        _make_samples(folder)

    for i, (title, body, runs) in enumerate(steps, 1):
        console.print()
        console.print(Panel(Text.from_markup(body), title=f"[bold]{title}[/bold]",
                            subtitle=f"[dim]{i} of {len(steps)}[/dim]", title_align="left",
                            subtitle_align="right", border_style=ACCENT, padding=(1, 2)))
        for argv in runs:
            line = "sdexe " + " ".join(_shell_quote(a) for a in argv)
            if not live:
                console.print(f"  $ {line}")
                continue
            ans = _key(console, f"\n  [dim]$[/dim] [bold]{line}[/bold]   [dim]Enter to run · s skip · q quit[/dim] ")
            if ans == "q":
                return _tutorial_end(console, folder, finished=False)
            if ans == "s":
                continue
            console.print()
            code = _run(argv, folder)
            if code not in (0, None):
                console.print("  [dim]That didn't work here, which is fine for the tutorial. "
                              "Carry on.[/dim]")
        if live and i < len(steps):
            ans = _key(console, "\n  [dim]Enter for the next step · q quit[/dim] ")
            if ans == "q":
                return _tutorial_end(console, folder, finished=False)
    if live:
        _tutorial_end(console, folder, finished=True)


def _tutorial_end(console: Console, folder: Path, finished: bool):
    console.print()
    if finished:
        console.print(Panel(
            Group(Text("That's everything.", style="bold green"), Text(""),
                  Text("Keep this handy:", style="bold"),
                  Text.assemble(('  sdexe download "<link>" [-mp3|-a|-720p|--best]\n', ACCENT),
                                ("  sdexe info \"<link>\"\n", ACCENT),
                                ("  sdexe pdf | image | audio | video | convert | file   ", ACCENT),
                                ("(each lists its commands)\n", "dim"),
                                ("  sdexe --help", ACCENT))),
            border_style="green", padding=(1, 3), expand=False))
    if folder.exists() and any(folder.iterdir()):
        console.print(f"\n  The tutorial's files are in [bold]{_home(folder)}[/bold]. Delete them?")
        if yes_no(console, default=False):
            shutil.rmtree(folder, ignore_errors=True)
            console.print("   [dim]Deleted.[/dim]")
    console.print()


def tutorial_main(argv) -> int:
    console = Console(highlight=False)
    if argv and argv[0] in ("-h", "--help"):
        console.print("[bold]sdexe tutorial[/bold] [dim]· a hands-on walkthrough of downloads, the file tools, "
                      "agents and the web app. Runs real commands in ~/sdexe-tutorial.[/dim]")
        return 0
    try:
        run_tutorial(console)
    except KeyboardInterrupt:
        console.print("\n  [dim]Tutorial stopped. Pick it up again with[/dim] [cyan]sdexe tutorial[/cyan]\n")
        return 130
    return 0
