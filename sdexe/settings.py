"""`sdexe settings`: everything a person can change, in one place.

SETTINGS is the table of stored preferences (config.json, shared with the web
app). INTEGRATIONS are switches that change things outside sdexe (the zsh
alias, Claude Code). Both appear in the interactive screen; the stored ones can
also be read and written by scripts and agents:

    sdexe settings --json
    sdexe settings get dl_quality
    sdexe settings set dl_quality 720p
    sdexe settings reset [KEY]
"""

import json
import os
import select
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from sdexe import ui


@dataclass
class Setting:
    key: str
    section: str
    label: str
    kind: str                      # bool | choice | int | path
    default: object
    help: str = ""
    choices: tuple = ()            # ((value, label), ...)
    low: int = 0
    high: int = 0

    def show(self, value) -> str:
        if self.kind == "bool":
            return "on" if value else "off"
        if self.kind == "choice":
            return dict(self.choices).get(value, str(value))
        if self.kind == "path":
            return str(value).replace(str(Path.home()), "~", 1) if value else "the folder you're in"
        return str(value)

    def parse(self, raw):
        """A value from the command line or JSON, validated."""
        if self.kind == "bool":
            if isinstance(raw, bool):
                return raw
            low = str(raw).strip().lower()
            if low in ("1", "true", "yes", "on", "y"):
                return True
            if low in ("0", "false", "no", "off", "n"):
                return False
            raise ValueError(f"{self.key} takes on or off")
        if self.kind == "choice":
            values = [v for v, _ in self.choices]
            if str(raw) not in values:
                raise ValueError(f"{self.key} takes one of: {', '.join(values)}")
            return str(raw)
        if self.kind == "int":
            try:
                n = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{self.key} takes a number")
            if not self.low <= n <= self.high:
                raise ValueError(f"{self.key} must be between {self.low} and {self.high}")
            return n
        if self.kind == "path":
            if raw in ("", None, "-", "."):
                return ""
            p = Path(str(raw)).expanduser().resolve()
            if p.exists() and not p.is_dir():
                raise ValueError(f"{p} is a file, not a folder")
            return str(p)
        return raw


_QUALITIES = (
    ("best", "best available · 4K/8K when offered"),
    ("2160p60", "up to 4K"),
    ("1440p60", "up to 1440p"),
    ("1080p60", "up to 1080p60"),
    ("1080p30", "up to 1080p30"),
    ("720p60", "up to 720p"),
    ("480p", "up to 480p · small files"),
)

SETTINGS = [
    Setting("open_browser", "Startup", "Open the browser when sdexe starts", "bool", True,
            "Off: sdexe prints its address instead. sdexe --browser / --no-browser override one run."),
    Setting("port", "Startup", "Web app port", "int", 5001,
            "Where the web app listens. If it's taken, sdexe picks the next free one.", low=1024, high=65535),
    Setting("tray", "Startup", "Menu bar icon", "bool", True, "The sd icon with Open and Quit, while sdexe runs."),
    Setting("update_check", "Startup", "Check for updates on start", "bool", True,
            "A quick look at PyPI when sdexe starts. Nothing is installed without you."),

    Setting("dl_video_format", "Downloads", "Video format", "choice", "mp4",
            "What sdexe download saves when you don't add a tag.",
            (("mp4", "MP4 · plays everywhere"), ("mkv", "MKV · any codec, no conversion"),
             ("webm", "WebM · VP9/AV1"))),
    Setting("dl_quality", "Downloads", "Video quality", "choice", "1080p60",
            "The ceiling for video downloads. Tags like -720p or --best override it.", _QUALITIES),
    Setting("dl_audio_format", "Downloads", "Audio format", "choice", "wav",
            "What sdexe download -a saves.",
            (("wav", "WAV · lossless"), ("flac", "FLAC · lossless, half the size"), ("mp3", "MP3"),
             ("m4a", "M4A · AAC, no conversion"), ("opus", "Opus · no conversion"))),
    Setting("dl_mp3_bitrate", "Downloads", "MP3 bitrate", "choice", "320", "Used whenever you ask for MP3.",
            (("320", "320 kbps"), ("256", "256 kbps"), ("192", "192 kbps"), ("128", "128 kbps"))),
    Setting("dl_folder", "Downloads", "Save downloads to", "path", "",
            "Empty means the folder you run the command in. -o still overrides it."),
    Setting("dl_jobs", "Downloads", "Downloads at once", "int", 3, "For batches and playlists.", low=1, high=8),
    Setting("dl_cover_art", "Downloads", "Embed cover art", "bool", True,
            "The thumbnail as album art in MP3, M4A, FLAC and MP4."),
    Setting("dl_tags", "Downloads", "Embed title, artist and date", "bool", True,
            "Tags music apps and file browsers show."),

    Setting("accent", "Look", "Accent colour", "choice", ui.DEFAULT_ACCENT,
            "Colours the whole terminal side of sdexe.",
            tuple((name, name) for name in ui.ACCENTS)),
]
BY_KEY = {s.key: s for s in SETTINGS}


# ── Stored values ──

def _load() -> dict:
    from sdexe.app import load_config
    return load_config()


def get(key: str, cfg: dict | None = None):
    s = BY_KEY[key]
    cfg = _load() if cfg is None else cfg
    value = cfg.get(key, s.default)
    try:
        return s.parse(value) if value != s.default else value
    except ValueError:
        return s.default


def put(key: str, value):
    from sdexe.app import load_config, save_config
    s = BY_KEY[key]
    value = s.parse(value)
    cfg = load_config()
    if value == s.default:
        cfg.pop(key, None)
    else:
        cfg[key] = value
    save_config(cfg)
    if key == "accent":
        ui.set_accent(value)
    return value


def all_values() -> dict:
    cfg = _load()
    return {s.key: get(s.key, cfg) for s in SETTINGS}


# ── Integrations: switches that change things outside sdexe ──

ZSH_BLOCK = "\n# sdexe: let links with ? and & through without quotes\nalias sdexe='noglob sdexe'\n"


def zshrc() -> Path | None:
    if os.path.basename(os.environ.get("SHELL", "")) != "zsh":
        return None
    return Path(os.environ.get("ZDOTDIR") or Path.home()) / ".zshrc"


def zsh_alias_on() -> bool:
    rc = zshrc()
    try:
        return bool(rc) and "noglob sdexe" in rc.read_text()
    except OSError:
        return False


def set_zsh_alias(on: bool) -> str:
    rc = zshrc()
    if not rc:
        return "Only needed in zsh."
    if on:
        if not zsh_alias_on():
            with open(rc, "a") as f:
                f.write(ZSH_BLOCK)
        return f"Added to ~/{rc.name}. Takes effect in new terminal tabs."
    text = rc.read_text()
    if ZSH_BLOCK in text:  # exactly what we added, blank line included
        rc.write_text(text.replace(ZSH_BLOCK, "", 1))
        return f"Removed from ~/{rc.name}. Quote links again in new tabs."
    lines = [ln for ln in text.splitlines(keepends=True)
             if "noglob sdexe" not in ln and ln.strip() != ZSH_BLOCK.strip().splitlines()[0]]
    rc.write_text("".join(lines))
    return f"Removed from ~/{rc.name}. Quote links again in new tabs."


def _claude() -> str | None:
    return shutil.which("claude")


def sdexe_command() -> list:
    exe = shutil.which("sdexe")
    return [exe] if exe else [sys.executable, "-m", "sdexe"]


def claude_mcp_on() -> bool | None:
    """True/False, or None when Claude Code isn't installed."""
    claude = _claude()
    if not claude:
        return None
    try:
        return subprocess.run([claude, "mcp", "get", "sdexe"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def set_claude_mcp(on: bool) -> str:
    claude = _claude()
    if not claude:
        return "Claude Code isn't installed (claude not found on PATH)."
    if on:
        r = subprocess.run([claude, "mcp", "add", "-s", "user", "sdexe", "--", *sdexe_command(), "mcp"],
                           capture_output=True, text=True, timeout=60)
        return "Connected. New Claude Code sessions can use sdexe." if r.returncode == 0 \
            else (r.stderr or r.stdout).strip().splitlines()[-1]
    r = subprocess.run([claude, "mcp", "remove", "-s", "user", "sdexe"], capture_output=True, text=True, timeout=60)
    return "Disconnected." if r.returncode == 0 else (r.stderr or r.stdout).strip().splitlines()[-1]


def skill_path() -> Path:
    return Path.home() / ".claude" / "skills" / "sdexe" / "SKILL.md"


def skill_on() -> bool:
    return skill_path().is_file()


def set_skill(on: bool) -> str:
    p = skill_path()
    if on:
        from sdexe.agent import skill_markdown
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(skill_markdown(), encoding="utf-8")
        return "Installed. Claude Code picks it up in new sessions."
    shutil.rmtree(p.parent, ignore_errors=True)
    return "Removed."


# ── Command line ──

HELP = """\
  [title]sdexe settings[/title] [muted]· change how sdexe behaves[/muted]

  [brand]sdexe settings[/brand]                     the settings screen (arrow keys)
  [brand]sdexe settings[/brand] [brand2]--json[/brand2]              every setting and its value
  [brand]sdexe settings get[/brand] [brand2]KEY[/brand2]
  [brand]sdexe settings set[/brand] [brand2]KEY VALUE[/brand2]       e.g. set dl_quality 720p60
  [brand]sdexe settings reset[/brand] [brand2]\\[KEY][/brand2]         back to the default (all, without KEY)
"""


def settings_main(argv) -> int:
    c = ui.console()
    err = ui.console(stderr=True)
    if argv and argv[0] in ("-h", "--help"):
        c.print()
        c.print(HELP, soft_wrap=True)
        c.print("  [title]Keys[/title]")
        for s in SETTINGS:
            vals = "|".join(v for v, _ in s.choices) if s.kind == "choice" else s.kind
            c.print(f"    [brand]{s.key.ljust(16)}[/brand] [muted]{vals}[/muted]")
        return 0
    if argv and argv[0] == "--json":
        print(json.dumps(all_values(), indent=2))
        return 0
    if argv and argv[0] in ("get", "set", "reset"):
        action, rest = argv[0], argv[1:]
        try:
            if action == "get":
                if len(rest) != 1 or rest[0] not in BY_KEY:
                    raise ValueError("usage: sdexe settings get KEY  (keys: sdexe settings --help)")
                value = get(rest[0])
                print(json.dumps(value) if not isinstance(value, str) else value)
            elif action == "set":
                if len(rest) != 2 or rest[0] not in BY_KEY:
                    raise ValueError("usage: sdexe settings set KEY VALUE  (keys: sdexe settings --help)")
                value = put(rest[0], rest[1])
                err.print(f"  [ok]✓[/ok] {BY_KEY[rest[0]].label}: [brand]{BY_KEY[rest[0]].show(value)}[/brand]")
            else:
                keys = rest or [s.key for s in SETTINGS]
                for k in keys:
                    if k not in BY_KEY:
                        raise ValueError(f"unknown setting {k}")
                    put(k, BY_KEY[k].default)
                err.print(f"  [ok]✓[/ok] Reset {'everything' if not rest else ', '.join(rest)} to defaults.")
        except ValueError as e:
            err.print(f"sdexe settings: {e}")
            return 2
        return 0
    if argv:
        err.print(f"sdexe settings: unknown argument {argv[0]}. Run [brand]sdexe settings --help[/brand].")
        return 2
    if not ui.is_interactive():
        for s in SETTINGS:
            print(f"{s.key} = {json.dumps(get(s.key))}")
        return 0
    return Hub().run()


# ── The settings screen ──

class _Row:
    def __init__(self, kind, label, section, setting=None, action=None, help=""):
        self.kind = kind            # setting | integration | system | setup | done
        self.label = label
        self.section = section
        self.setting = setting
        self.action = action
        self.help = help


class Hub:
    """Full-screen, arrow-key settings. Every change saves at once."""

    def __init__(self):
        self.c = ui.console()
        self.values = all_values()
        self.idx = 0
        self.flash = ("", "muted")
        self.states = {}
        self.rows = [_Row("setting", s.label, s.section, setting=s, help=s.help) for s in SETTINGS]
        integ = []
        if zshrc():
            integ.append(_Row("integration", "Paste links without quotes (zsh)", "Integrations", action="zsh",
                              help="Adds alias sdexe='noglob sdexe' so the ? in YouTube links doesn't break."))
        integ += [
            _Row("integration", "Claude Code can use sdexe (MCP)", "Integrations", action="mcp",
                 help="Every sdexe tool becomes available to Claude Code, in any project."),
            _Row("integration", "Claude Code skill", "Integrations", action="skill",
                 help="A SKILL.md that teaches Claude the sdexe commands. An alternative to MCP."),
        ]
        self.rows += integ
        self.rows += [
            _Row("system", "Check ffmpeg, yt-dlp and the YouTube solver", "System",
                 help="Enter runs the checks and offers fixes."),
            _Row("setup", "Run the guided setup again", "System", help="The first-run questions, one by one."),
        ]
        self._refresh_states()

    def _refresh_states(self):
        self.states = {"zsh": zsh_alias_on(), "mcp": claude_mcp_on(), "skill": skill_on()}

    # drawing
    def _value(self, row: _Row, selected: bool) -> Text:
        if row.kind == "setting":
            s = row.setting
            v = self.values[s.key]
            txt = s.show(v)
            if s.key == "accent":
                t = Text()
                if selected:
                    t.append("‹ ", style="faint")
                a, b = ui.ACCENTS[v]
                t.append_text(ui.gradient(f"■■■ {txt}", a, b))
                if selected:
                    t.append(" ›", style="faint")
                return t
            style = ("ok" if v else "faint") if s.kind == "bool" else "brand"
            if s.kind in ("choice",) and selected:
                return Text.assemble(("‹ ", "faint"), (txt, style), (" ›", "faint"))
            return Text(txt, style=style)
        if row.kind == "integration":
            state = self.states.get(row.action)
            if state is None:
                return Text("Claude Code not installed", style="faint")
            words = {"zsh": ("on", "off"), "mcp": ("connected", "not connected"), "skill": ("installed", "not installed")}
            on, off = words[row.action]
            return Text(on, style="ok") if state else Text(off, style="faint")
        return Text("")

    def render(self):
        c = self.c
        height = c.size.height
        lines = [Text(""), ui.wordmark("settings · changes save as you make them", None), Text("")]
        body = []
        last_section = None
        sel_line = 0
        label_w = max(len(r.label) for r in self.rows) + 2
        for i, row in enumerate(self.rows):
            if row.section != last_section:
                if last_section is not None:
                    body.append(Text(""))
                body.append(ui.section(row.section))
                last_section = row.section
            selected = i == self.idx
            t = Text("   ")
            t.append("❯ " if selected else "  ", style="brand")
            t.append(row.label.ljust(label_w), style="title" if selected else "default")
            t.append_text(self._value(row, selected))
            if selected:
                sel_line = len(body)
            body.append(t)
        footer = [Text(""), Text("   " + (self.rows[self.idx].help or ""), style="muted")]
        msg, style = self.flash
        footer.append(Text("   " + msg, style=style) if msg else Text(""))
        footer.append(ui.keys(("↑↓", "move"), ("←→", "change"), ("enter", "edit / toggle"), ("q", "done")))

        room = max(height - len(lines) - len(footer) - 1, 5)
        if len(body) > room:
            start = min(max(sel_line - room // 2, 0), len(body) - room)
            body = body[start:start + room]
        out = lines + body + footer
        with c.capture() as cap:
            for ln in out:
                c.print(ln, no_wrap=True, overflow="ellipsis")
        sys.stdout.write("\x1b[H\x1b[2J" + cap.get())
        sys.stdout.flush()

    # input
    def _read_key(self, fd) -> str:
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            if select.select([fd], [], [], 0.05)[0]:
                seq = os.read(fd, 2)
                return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}.get(seq, "")
            return "esc"
        return {b"\r": "enter", b"\n": "enter", b" ": "enter", b"q": "q", b"k": "up", b"j": "down",
                b"h": "left", b"l": "right", b"\x03": "ctrl-c"}.get(ch, ch.decode("utf-8", "ignore"))

    def _prompt(self, label: str, current: str) -> str | None:
        """Read a line at the bottom of the screen, in normal (cooked) mode."""
        import termios
        fd = sys.stdin.fileno()
        termios.tcsetattr(fd, termios.TCSADRAIN, self._cooked)
        sys.stdout.write("\x1b[?25h")
        try:
            import readline  # noqa: F401  arrow keys and editing inside input()
        except ImportError:
            pass
        try:
            self.c.print(f"\n   [title]{label}[/title] [muted](enter keeps {current or 'it'}, "
                         f"- clears)[/muted]")
            raw = input("   › ")
        except (EOFError, KeyboardInterrupt):
            raw = None
        finally:
            sys.stdout.write("\x1b[?25l")
            import tty
            tty.setcbreak(fd)
        return raw

    def _change(self, row: _Row, step: int):
        s = row.setting
        v = self.values[s.key]
        if s.kind == "bool":
            new = not v
        elif s.kind == "choice":
            values = [x for x, _ in s.choices]
            new = values[(values.index(v) + step) % len(values)] if v in values else values[0]
        elif s.kind == "int" and step:
            new = min(max(v + step, s.low), s.high)
        else:
            raw = self._prompt(s.label, s.show(v))
            if raw is None or raw == "":
                return
            try:
                new = s.parse("" if raw.strip() == "-" else raw.strip())
            except ValueError as e:
                self.flash = (f"✗ {e}", "err")
                return
        put(s.key, new)
        self.values[s.key] = new
        if s.key == "accent":
            self.c.push_theme(ui.theme())
        self.flash = (f"✓ {s.label}: {s.show(new)}", "ok")

    def _toggle(self, row: _Row):
        state = self.states.get(row.action)
        if row.action == "mcp" and state is None:
            self.flash = ("Install Claude Code first: https://claude.com/claude-code", "warn")
            return
        self.flash = ("working…", "muted")
        self.render()
        fn = {"zsh": set_zsh_alias, "mcp": set_claude_mcp, "skill": set_skill}[row.action]
        try:
            msg = fn(not state)
        except Exception as e:  # noqa: BLE001
            self.flash = (f"✗ {e}", "err")
            return
        self._refresh_states()
        ok = self.states.get(row.action) == (not state)
        self.flash = (f"{'✓' if ok else '✗'} {msg}", "ok" if ok else "err")

    def _system(self):
        from sdexe.cli_home import system_checks
        self.flash = ("checking…", "muted")
        self.render()
        issues = [(name, detail, fix) for ok, name, detail, fix in system_checks() if not ok]
        if not issues:
            self.flash = ("✓ ffmpeg, yt-dlp and the YouTube solver are all good.", "ok")
            return
        name, detail, fix = issues[0]
        self.flash = (f"! {name}: {detail}. Fix: {fix}" + (f"  (+{len(issues) - 1} more)" if len(issues) > 1 else ""),
                      "warn")

    def run(self) -> int:
        import termios
        import tty
        fd = sys.stdin.fileno()
        self._cooked = termios.tcgetattr(fd)
        run_setup_after = False
        sys.stdout.write("\x1b[?1049h\x1b[?25l")  # alternate screen, hide cursor
        try:
            tty.setcbreak(fd)
            while True:
                self.render()
                key = self._read_key(fd)
                row = self.rows[self.idx]
                if key in ("q", "esc", "ctrl-c"):
                    break
                if key == "up":
                    self.idx = (self.idx - 1) % len(self.rows)
                elif key == "down":
                    self.idx = (self.idx + 1) % len(self.rows)
                elif key in ("left", "right", "enter"):
                    step = -1 if key == "left" else 1
                    self.flash = ("", "muted")
                    if row.kind == "setting":
                        if row.setting.kind == "path" and key != "enter":
                            continue
                        if key == "enter" and row.setting.kind == "int":
                            step = 0  # enter types a number; arrows nudge it
                        self._change(row, step)
                    elif row.kind == "integration" and key == "enter":
                        self._toggle(row)
                    elif row.kind == "system" and key == "enter":
                        self._system()
                    elif row.kind == "setup" and key == "enter":
                        run_setup_after = True
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, self._cooked)
            sys.stdout.write("\x1b[?25h\x1b[?1049l")
            sys.stdout.flush()
        if run_setup_after:
            from sdexe.cli_home import run_setup
            run_setup(ui.console())
            return 0
        self.c.print(f"  [ok]✓[/ok] [muted]Settings saved. Change them any time with[/muted] [brand]sdexe settings[/brand]")
        return 0
