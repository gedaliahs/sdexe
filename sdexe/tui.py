"""The clickable terminal app `sdexe` opens while the web app runs.

Built on Textual: buttons, fields, lists and progress bars that work with the
mouse or the keyboard. The look is black and gray with one accent colour, used
only for the main action, the current place and progress.

It drives the same code as the commands: cli.Downloader for downloads,
cli_search for search, `python -m sdexe ...` for the file tools, and the
settings table for settings.
"""

import json
import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from argparse import Namespace
from pathlib import Path

from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (Button, ContentSwitcher, DataTable, DirectoryTree, Footer, Input, Label,
                             OptionList, ProgressBar, Select, Static, Switch)
from textual.widgets.option_list import Option

from sdexe import __version__, settings, ui
from sdexe.cli import download_defaults, fmt_size, fmt_time

BG, SURFACE, RAISED, HOVER, LINE = "#0e0e0e", "#141414", "#1c1c1c", "#262626", "#2a2a2a"


def _theme() -> Theme:
    return Theme(
        name=f"sdexe-{ui.accent_name()}", primary=ui.accent(), secondary=ui.LIGHT, accent=ui.accent(),
        foreground=ui.TEXT, background=BG, surface=SURFACE, panel=RAISED,
        success="#6fcf8f", warning="#e8b04a", error="#ef6f6f", dark=True,
    )


CSS = f"""
* {{ scrollbar-size-vertical: 1; scrollbar-size-horizontal: 1; scrollbar-color: {LINE};
     scrollbar-color-hover: #3a3a3a; scrollbar-color-active: #4a4a4a; scrollbar-background: $background;
     scrollbar-background-hover: $background; scrollbar-background-active: $background;
     scrollbar-corner-color: $background; }}
Screen {{ background: $background; color: $foreground; }}

/* Top bar */
#top {{ height: 3; padding: 1 2 0 3; border-bottom: solid {LINE}; }}
#name {{ width: auto; text-style: bold; }}
#ver {{ width: 1fr; color: {ui.FAINT}; padding: 0 0 0 2; }}
#open-web {{ background: $background; color: {ui.MUTED}; padding: 0 1; min-width: 0; }}
#open-web:hover {{ color: $foreground; background: $background; text-style: underline; }}

/* Sidebar */
#body {{ height: 1fr; }}
#nav {{ width: 18; padding: 1 0; border-right: solid {LINE}; }}
.navitem {{ width: 100%; height: 1; margin: 0 0 1 0; padding: 0 3; background: $background; color: {ui.MUTED};
            border: none; content-align: left middle; text-align: left; text-style: none; }}
.navitem:hover {{ color: $foreground; background: {SURFACE}; }}
.navitem:focus {{ color: $foreground; background: {SURFACE}; text-style: none; }}
.navitem.-current {{ color: $foreground; text-style: bold; background: {SURFACE};
                     border-left: outer $primary; padding: 0 2; }}
#nav-spacer {{ height: 1fr; }}

#main {{ width: 1fr; padding: 1 4; }}

/* Type */
.title {{ text-style: bold; margin: 0 0 1 0; }}
.hint {{ color: {ui.MUTED}; }}
.faint {{ color: {ui.FAINT}; }}
.section {{ color: {ui.MUTED}; text-style: bold; margin: 2 0 1 0; }}
.label {{ color: {ui.MUTED}; margin: 1 0 0 0; }}

/* Controls: flat, gray, one line */
Button {{ height: 1; min-width: 8; border: none; padding: 0 2; background: {RAISED}; color: $foreground;
          text-style: none; }}
Button:hover {{ background: {HOVER}; }}
Button:focus {{ background: {HOVER}; text-style: bold; }}
Button.-primary {{ background: $primary; color: {BG}; text-style: bold; }}
Button.-primary:hover {{ background: $primary 85%; }}
Button:disabled {{ background: {SURFACE}; color: {ui.FAINT}; }}

Input {{ height: 3; border: round {LINE}; background: $background; padding: 0 1;
         scrollbar-size-horizontal: 0; }}
Input:focus {{ border: round #5a5a5a; background: $background; background-tint: $foreground 0%; }}
Input > .input--selection {{ background: #3a3a3a; color: $foreground; }}
Input > .input--placeholder {{ color: {ui.FAINT}; }}
Input > .input--cursor {{ background: $primary; color: {BG}; }}

Select {{ width: 26; }}
Select > SelectCurrent {{ border: round {LINE}; background: $background; }}
Select:focus > SelectCurrent {{ border: round #5a5a5a; background: $background; }}
Select > SelectOverlay {{ background: {SURFACE}; border: round {LINE}; }}

Switch {{ border: none; height: 1; width: 6; padding: 0; background: {RAISED}; }}
Switch:focus {{ border: none; background: {HOVER}; }}
Switch > .switch--slider {{ color: #3c3c3c; background: {RAISED}; }}
Switch.-on > .switch--slider {{ color: $primary; }}

DataTable {{ background: $background; }}
DataTable > .datatable--header {{ background: $background; color: {ui.MUTED}; text-style: bold; }}
DataTable > .datatable--cursor {{ background: {HOVER}; color: $foreground; text-style: bold; }}
DataTable > .datatable--hover {{ background: {SURFACE}; }}
DataTable > .datatable--header-hover {{ background: $background; }}

OptionList {{ background: $background; border: none; padding: 0; }}
OptionList:focus {{ border: none; }}
OptionList > .option-list--option {{ color: {ui.LIGHT}; }}
OptionList > .option-list--option-highlighted {{ background: {HOVER}; color: $foreground; text-style: bold; }}
OptionList > .option-list--option-hover {{ background: {SURFACE}; }}
OptionList > .option-list--option-disabled {{ color: {ui.FAINT}; text-style: bold; }}

Bar > .bar--bar {{ color: $primary; background: {HOVER}; }}
Bar > .bar--complete {{ color: #6fcf8f; background: {HOVER}; }}
Bar > .bar--indeterminate {{ color: $primary; background: {HOVER}; }}
PercentageStatus {{ color: {ui.MUTED}; }}

Footer {{ background: $background; }}
FooterKey {{ background: $background; }}
FooterKey > .footer-key--key {{ color: $foreground; background: $background; text-style: bold; }}
FooterKey > .footer-key--description {{ color: {ui.MUTED}; background: $background; }}

Toast {{ background: {RAISED}; border-left: outer $primary; }}
Toast.-error {{ border-left: outer $error; }}

/* A field with its button beside it */
.bar {{ height: 3; }}
.bar Input {{ width: 1fr; }}
.bar Button {{ height: 1; margin: 1 0 0 1; padding: 0 3; }}
.bar Select {{ margin: 0 0 0 1; }}

/* Rows of controls */
.row {{ height: auto; margin: 1 0 0 0; }}
.row > * {{ margin: 0 1 0 0; }}
.inline {{ height: 1; margin: 1 0 0 0; }}
.inline > * {{ margin: 0 2 0 0; }}
.inline Label {{ width: auto; }}
.grow {{ width: 1fr; }}

/* Home */
#home-box {{ width: 1fr; }}
#tools {{ height: 1; }}
#tools Button {{ margin: 0 1 0 0; }}
#home-hint {{ width: 1fr; }}
#home-recent {{ height: auto; }}
#recent-empty {{ color: {ui.FAINT}; }}

/* Downloads */
DownloadPane {{ overflow-y: auto; }}
#dl-rows {{ height: 1fr; min-height: 6; }}
.dlrow {{ height: 1; margin: 0 0 1 0; }}
.dlrow .icon {{ width: 2; }}
.dlrow .name {{ width: 1fr; min-width: 16; }}
.dlrow ProgressBar {{ width: 24; }}
.dlrow Bar {{ width: 22; }}
.dlrow .detail {{ width: 34; color: {ui.MUTED}; }}
.dlrow Button {{ background: $background; color: {ui.MUTED}; min-width: 6; padding: 0 1; }}
.dlrow Button:hover {{ color: $foreground; background: {SURFACE}; }}

/* Search */
#q {{ width: 1fr; }}
#results {{ height: 1fr; margin: 1 0 0 0; }}

/* Files */
#file-list {{ width: 26; height: 1fr; border-right: solid {LINE}; padding: 0 1 0 0; }}
#file-form {{ width: 1fr; height: 1fr; padding: 0 0 0 3; }}
#file-form Input {{ height: 1; border: none; background: {SURFACE}; padding: 0 1; }}
#file-form Input:focus {{ background: {RAISED}; }}
#file-form Select {{ width: 30; }}
#file-form Select > SelectCurrent {{ border: none; background: {SURFACE}; height: 1; padding: 0 1; }}
#file-head {{ height: 1; }}
#file-head Label {{ width: 1fr; text-style: bold; }}
#file-output {{ height: auto; margin: 1 0 0 0; color: {ui.LIGHT}; }}

/* Settings */
.setting {{ height: 1; margin: 0 0 1 0; }}
.setting Label {{ width: 40; }}
.setting Input {{ height: 1; border: none; width: 36; background: {SURFACE}; padding: 0 1; }}
.setting Input:focus {{ background: {RAISED}; }}
.setting Select {{ width: 36; }}
.setting Select > SelectCurrent {{ border: none; background: {SURFACE}; height: 1; padding: 0 1; }}

/* Under 110 columns (an 80-column terminal): the same screens, with the
   fixed widths taken in so nothing is pushed off the right edge. */
.-narrow #main {{ padding: 1 2; }}
.-narrow #tools Button {{ padding: 0; min-width: 0; }}
.-narrow .dlrow ProgressBar {{ display: none; }}
.-narrow .dlrow .name {{ margin: 0 1 0 0; }}
.-narrow .dlrow .detail {{ width: 26; }}
.-narrow #q-source {{ width: 18; }}
.-narrow SearchPane .inline > * {{ margin: 0 1 0 0; }}
.-narrow SearchPane .inline Button {{ padding: 0; min-width: 0; }}
.-narrow #file-list {{ width: 18; }}
.-narrow #file-form {{ padding: 0 0 0 2; }}
.-narrow #file-form .inline > * {{ margin: 0 1 0 0; }}
.-narrow #file-form .inline Button {{ padding: 0; min-width: 0; }}
.-narrow .setting Label {{ width: 1fr; }}
.-narrow .setting Input {{ width: 22; }}
.-narrow .setting Select {{ width: 22; }}

/* File picker */
FilePicker {{ align: center middle; background: $background 60%; }}
#picker {{ width: 80%; height: 80%; background: {SURFACE}; border: round {LINE}; padding: 1 2; }}
#picker DirectoryTree {{ height: 1fr; background: {SURFACE}; }}
"""


def _themed(renderable, width: int = 110) -> Text:
    """Render something drawn with sdexe's Rich theme (styles like "muted")
    into plain coloured Text; Textual doesn't know those style names."""
    from rich.console import Console
    c = Console(theme=ui.theme(), width=width, force_terminal=True, color_system="truecolor", highlight=False)
    with c.capture() as cap:
        c.print(renderable)
    return Text.from_ansi(cap.get().rstrip("\n"))


def _short(path: str) -> str:
    p = Path(path)
    try:
        return "./" + str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p).replace(str(Path.home()), "~", 1)


def _expand(text: str) -> Path:
    """Path(text).expanduser(). "~nobody/x" stays as typed instead of raising."""
    p = Path(text)
    try:
        return p.expanduser()
    except RuntimeError:
        return p


def _is_file(text: str) -> bool:
    try:
        return _expand(text).is_file()
    except (OSError, ValueError):  # Python 3.12 raises on a name over 255 characters
        return False


def _split_paths(text: str, windows: bool | None = None) -> list:
    """The file names in a box: quoted, backslash-escaped (how terminals paste
    a dragged file), or one bare path with spaces. ValueError on a stray quote."""
    text = text.strip()
    if not text:
        return []
    if _is_file(text):
        return [text]  # "My File (1).pdf", typed or pasted as it is
    if sys.platform.startswith("win") if windows is None else windows:
        # Backslashes separate folders there; they don't escape anything.
        return [t[1:-1] if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in shlex.split(text, posix=False)]
    return shlex.split(text)


def _quote_path(path: str, windows: bool | None = None) -> str:
    """A path as _split_paths reads it back."""
    if sys.platform.startswith("win") if windows is None else windows:
        return f'"{path}"' if " " in path else path
    return shlex.quote(path)


def reveal(path: str) -> bool:
    """Show a file in Finder / the file manager. False when that can't be done."""
    p = Path(path)
    if sys.platform == "darwin":
        cmd = ["open", "-R", str(p)]
    elif sys.platform.startswith("win"):
        cmd = ["explorer", "/select,", str(p)]
    else:
        cmd = ["xdg-open", str(p.parent)]
    if not p.exists():
        return False
    try:
        # Its messages must not land on top of the app.
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False  # no xdg-open on this machine
    threading.Thread(target=proc.wait, daemon=True).start()  # reap it
    return True


# ── Pieces ──

class LinesInput(Input):
    """A box for several links or files. A pasted list, one per line, becomes
    one line; a plain Input keeps only the first line and drops the rest."""

    def __init__(self, *args, files: bool = False, **kwargs):
        super().__init__(*args, select_on_focus=False, **kwargs)
        self.files = files

    def _on_paste(self, event: events.Paste) -> None:
        lines = [ln.strip() for ln in event.text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return  # one line: Input pastes it
        event.prevent_default()
        event.stop()
        if self.files:
            lines = [_quote_path(ln) if _is_file(ln) else ln for ln in lines]
        text = " ".join(lines)
        if self.selection.is_empty:
            self.insert_text_at_cursor(text)
        else:
            self.replace(text, *self.selection)


class FilePicker(ModalScreen):
    """Pick a file with the mouse. Returns its path, or None."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, start: Path):
        super().__init__()
        self.start = start

    def compose(self) -> ComposeResult:
        with Vertical(id="picker"):
            yield Label("Pick a file", classes="title")
            yield DirectoryTree(str(self.start))
            with Horizontal(classes="inline"):
                yield Button("Up a folder", id="picker-up")
                yield Button("Home", id="picker-home")
                yield Button("Cancel", id="picker-cancel")

    @on(DirectoryTree.FileSelected)
    def picked(self, event: DirectoryTree.FileSelected):
        self.dismiss(str(event.path))

    @on(Button.Pressed, "#picker-cancel")
    def cancel(self):
        self.dismiss(None)

    @on(Button.Pressed, "#picker-up")
    def up(self):
        tree = self.query_one(DirectoryTree)
        tree.path = Path(tree.path).parent

    @on(Button.Pressed, "#picker-home")
    def home(self):
        self.query_one(DirectoryTree).path = Path.home()


def _tui_error(msg: str) -> str:
    """A download error, with command-line advice reworded for this app."""
    return msg.replace("Add --playlist to download all of them.",
                       "Turn on Whole playlist on the Download page, then try again.")


class DownloadRow(Horizontal):
    def __init__(self, item):
        super().__init__(classes="dlrow")
        self.item = item
        self.last = None    # the status last drawn
        self.ready = False  # composed: its parts exist
        self._drawn = {}    # part -> what it shows now, to skip repainting the same thing

    def compose(self) -> ComposeResult:
        yield Label("·", classes="icon faint")
        yield Label(Text(self.item.name), classes="name")  # Text: titles aren't markup
        yield ProgressBar(total=100, show_eta=False, show_percentage=False)
        yield Label("waiting", classes="detail")
        yield Button("show", classes="show", disabled=True)

    def on_mount(self):
        if not self.children:
            return  # taken off Home again before it was drawn (more than five links at once)
        self._w_icon, self._w_name = self.query_one(".icon", Label), self.query_one(".name", Label)
        self._w_bar, self._w_detail = self.query_one(ProgressBar), self.query_one(".detail", Label)
        self._drawn = {"name": self.item.name}
        self.ready = True

    def _set(self, part: str, value, draw):
        if self._drawn.get(part) != value:
            self._drawn[part] = value
            draw()

    def sync(self, status: str):
        """Draw the item as it is now. status is passed in, read once by the
        caller: the download thread changes it at any moment."""
        i = self.item
        name = i.name
        self._set("name", name, lambda: self._w_name.update(Text(name)))
        if status == "running":
            self._set("icon", "↓", lambda: self._w_icon.update("↓"))
            stage = i.stage
            streams = list(i.streams.values())  # a copy: the download thread adds to it
            downloaded = sum(d for d, _ in streams)
            total = max(i.expected, sum(t or 0 for _, t in streams))
            if stage == "downloading" and total:
                pct = min(100.0, downloaded / total * 100)
                self._set("bar", round(pct, 1), lambda: self._w_bar.update(total=100, progress=pct))
                bits = [f"{pct:.0f}%", f"{fmt_size(downloaded)} of {fmt_size(total)}"]
                speed = i.speed
                if speed:
                    bits.append(f"{fmt_size(speed)}/s")
                text = "  ".join(bits)
            else:
                self._set("bar", None, lambda: self._w_bar.update(total=None))
                text = stage
            self._set("detail", text, lambda: self._w_detail.update(Text(text)))
        elif status == "done":
            self._w_icon.update(Text("✓", style="#6fcf8f"))
            self._w_bar.update(total=100, progress=100)
            try:
                size = fmt_size(i.path.stat().st_size)
            except (OSError, AttributeError):
                size = ""  # already moved away
            self._w_detail.update(" · ".join(b for b in (i.quality(), size) if b))
            self.query_one(".show", Button).disabled = False
        elif status == "failed":
            self._w_icon.update(Text("✗", style="#ef6f6f"))
            self._w_bar.display = False
            self._w_detail.update(Text(_tui_error(i.error), style="#ef6f6f"))
            self._w_detail.styles.width = "1fr"
            self.query_one(".show", Button).display = False

    @on(Button.Pressed, ".show")
    def show(self, event: Button.Pressed):
        event.stop()
        if self.item.path:
            self.app.show_file(str(self.item.path))


# ── Panes ──

FORMATS = [("MP4 video", "mp4"), ("MKV video", "mkv"), ("WebM video", "webm"),
           ("WAV audio", "wav"), ("FLAC audio", "flac"), ("MP3 audio", "mp3"),
           ("M4A audio", "m4a"), ("Opus audio", "opus")]
TOOL_GROUPS = [("PDF", "pdf"), ("Images", "image"), ("Audio", "audio"), ("Video", "video"),
               ("Convert", "convert"), ("Files", "file")]


def _quality_opts(fmt: str):
    if fmt == "mp3":
        return [(f"{b} kbps", b) for b in ("320", "256", "192", "128")]
    if fmt in ("wav", "flac", "m4a", "opus"):
        return [("Source quality", "source")]
    return [(label.split(" · ")[0][:1].upper() + label.split(" · ")[0][1:], v)
            for v, label in settings.BY_KEY["dl_quality"].choices]


def _default_label() -> str:
    from sdexe.cli import resolve_spec
    return resolve_spec([]).label


def _home_hint() -> str:
    return (f"A link downloads right away as {_default_label()}. Words search YouTube. "
            "Empty box? Go uses the link on your clipboard.")


class Home(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Paste a link, or type what you're looking for", classes="title")
        with Horizontal(classes="bar"):
            yield LinesInput(placeholder="https://…   or   artist - song", id="home-box")
            yield Button("Go", variant="primary", id="home-go")
        yield Label(_home_hint(), classes="hint", id="home-hint")
        yield Label("RECENT", classes="section")
        yield Label("Nothing downloaded yet.", id="recent-empty")
        yield Vertical(id="home-recent")
        yield Label("TOOLS", classes="section")
        with Horizontal(id="tools"):
            for label, group in TOOL_GROUPS:
                yield Button(label, id=f"tool-{group}")


class DownloadPane(Vertical):
    def compose(self) -> ComposeResult:
        d = download_defaults()
        yield Label("Download", classes="title")
        yield LinesInput(placeholder="Paste one or more links, separated by spaces", id="dl-links")
        with Horizontal(classes="row"):
            yield Select(FORMATS, value=d["video"], allow_blank=False, id="dl-format")
            yield Select(_quality_opts(d["video"]), value=d["quality"], allow_blank=False, id="dl-quality")
        with Horizontal(classes="inline"):
            yield Switch(value=False, id="dl-playlist")
            yield Label("Whole playlist", classes="hint")
        yield Label("Save to", classes="label")
        with Horizontal(classes="bar"):
            yield Input(value=d["folder"] or str(Path.cwd()), placeholder="Folder to save into", id="dl-folder")
            yield Button("Download", variant="primary", id="dl-go")
        yield Label("", classes="section", id="dl-heading")
        yield VerticalScroll(id="dl-rows")

    @on(Select.Changed, "#dl-format")
    def format_changed(self, event: Select.Changed):
        q = self.query_one("#dl-quality", Select)
        fmt = str(event.value)
        opts = _quality_opts(fmt)
        q.set_options(opts)
        d = download_defaults()
        default = d["bitrate"] if fmt == "mp3" else ("source" if fmt in ("wav", "flac", "m4a", "opus") else d["quality"])
        values = [v for _, v in opts]
        q.value = default if default in values else values[0]


class SearchPane(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Search", classes="title")
        with Horizontal(classes="bar"):
            yield Input(placeholder="What are you looking for?", id="q")
            yield Select([("YouTube", "youtube"), ("SoundCloud", "soundcloud")], value="youtube",
                         allow_blank=False, id="q-source")
            yield Button("Search", variant="primary", id="q-go")
        yield DataTable(id="results", cursor_type="row", zebra_stripes=False)
        with Horizontal(classes="inline"):
            yield Button("Download video", id="q-video", disabled=True)
            yield Button("Download audio", id="q-audio", disabled=True)
            yield Button("Open page", id="q-open", disabled=True)
            yield Label("", id="q-status", classes="hint")


class FilesPane(Horizontal):
    def compose(self) -> ComposeResult:
        from sdexe.cli_tools import COMMANDS
        options = []
        for label, group in TOOL_GROUPS:
            options.append(Option(label.upper(), id=f"group-{group}", disabled=True))
            for c in (c for c in COMMANDS if c.group == group):
                options.append(Option(f" {c.name or 'convert a file'}", id=c.full))
        yield OptionList(*options, id="file-list")
        with VerticalScroll(id="file-form"):
            yield Label("Pick a tool", classes="title")
            yield Label("Merge PDFs, resize images, trim audio, make GIFs, convert data.", classes="hint")


class SettingsPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Settings", classes="title")
        yield Label("Changes save as you make them.", classes="hint")
        values = settings.all_values()
        section = None
        for s in settings.SETTINGS:
            if s.section != section:
                section = s.section
                yield Label(section.upper(), classes="section")
            with Horizontal(classes="setting"):
                yield Label(s.label)
                v = values[s.key]
                if s.kind == "bool":
                    yield Switch(value=bool(v), id=f"set-{s.key}", tooltip=s.help)
                elif s.kind == "choice":
                    yield Select([(label, value) for value, label in s.choices], value=v, allow_blank=False,
                                 id=f"set-{s.key}", compact=True, tooltip=s.help)
                else:
                    yield Input(value=str(v), placeholder=s.show(""), id=f"set-{s.key}", compact=True,
                                type="integer" if s.kind == "int" else "text", tooltip=s.help)
        yield Label("INTEGRATIONS", classes="section")
        if settings.zshrc():
            with Horizontal(classes="setting"):
                yield Label("Paste links without quotes (zsh)")
                yield Switch(value=settings.zsh_alias_on(), id="int-zsh")
        with Horizontal(classes="setting"):
            yield Label("Claude Code can use sdexe")
            yield Switch(value=False, id="int-mcp", disabled=True)
        with Horizontal(classes="setting"):
            yield Label("Claude Code skill")
            yield Switch(value=settings.skill_on(), id="int-skill")
        yield Label("", id="settings-note", classes="hint")


HELP_COMMANDS = [
    ('sdexe download "<link>"', "save video or audio · -mp3, -a, -720p, --best"),
    ('sdexe search "<words>"', "find by name"),
    ('sdexe info "<link>"', "qualities and sizes, without downloading"),
    ("sdexe pdf | image | audio | video <command>", "the file tools"),
    ("sdexe convert <file> -f FMT", "csv, json, yaml, xml, md, xlsx…"),
    ("sdexe settings", "the settings, full screen"),
    ("sdexe mcp", "every tool for Claude, Cursor & co."),
    ("sdexe --classic", "start without this app"),
]
HELP_KEYS = [("d  s  f", "download · search · files"), (",", "settings"), ("o", "open the web app"),
             ("esc", "home, and out of the text box"), ("ctrl+q", "quit")]


def _help_rows(items: list, width: int, commands: bool = True) -> Text:
    """The two-column list when it fits; each description under its command
    when it doesn't (80 columns), instead of wrapping mid-row."""
    if width >= max(len(k) for k, _ in items) + 3 + max(len(v) for _, v in items):
        return _themed(ui.rows(items, indent=0, commands=commands), width=max(width, 20))
    out = Text()
    for n, (k, v) in enumerate(items):
        out.append_text(ui.cmd(k) if commands else Text(k))
        out.append(f"\n  {v}" + ("\n" if n < len(items) - 1 else ""), style="muted")
    return _themed(out, width=max(width, 20))


class HelpPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Help", classes="title")
        yield Label("Everything here also works as a typed command.", classes="hint")
        with Horizontal(classes="inline"):
            yield Button("Take the tutorial", id="help-tutorial")
            yield Button("Open the web app", id="help-web")
        yield Label("COMMANDS", classes="section")
        yield Static(_help_rows(HELP_COMMANDS, 110), id="help-commands")
        yield Label("KEYS", classes="section")
        yield Static(_help_rows(HELP_KEYS, 110, commands=False), id="help-keys")

    def on_resize(self, event: events.Resize):
        width = self.query_one("#help-commands", Static).size.width or event.size.width
        if width != getattr(self, "_drawn_width", 110):
            self._drawn_width = width
            self.query_one("#help-commands", Static).update(_help_rows(HELP_COMMANDS, width))
            self.query_one("#help-keys", Static).update(_help_rows(HELP_KEYS, width, commands=False))


# ── App ──

PANES = ("home", "download", "search", "files", "settings", "help")


class SdexeApp(App):
    TITLE = "sdexe"
    CSS = CSS
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (110, "-wide")]
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("q", "quit", "Quit", show=False),
        Binding("d", "go('download')", "Download"),
        Binding("s", "go('search')", "Search"),
        Binding("f", "go('files')", "Files"),
        Binding("comma", "go('settings')", "Settings"),
        Binding("o", "open_web", "Web app"),
        Binding("question_mark", "go('help')", "Help", show=False),
        Binding("escape", "home", "Home", show=False),
    ]

    def __init__(self, url: str | None = None, note: str = "", update: dict | None = None):
        super().__init__()
        self.url = url
        self.note = note
        self.update_info = update or {}
        self.downloaders = []
        self._submitted = {}   # (format, folder…, link) -> when it was last started
        self.rows = {}         # id(item) -> [its row on Download, its row on Home if still listed]
        self._heading = ""
        self.search_results = []
        self._result_rows = []
        self._search_seq = 0   # the newest search; older ones finishing later are dropped
        self._searching = None
        self.current_cmd = None
        self.last_outputs = []
        self._form_seq = 0     # the tool form on screen; results of an earlier one aren't drawn into it
        self._tool_busy = None
        self._tool_proc = None
        self._mcp_known = False  # Claude Code is installed: its switch can be used
        self._stopping = False
        self.ready = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Label("sdexe", id="name")
            yield Label(f"v{__version__}", id="ver")
            if self.url:
                yield Button(f"{self.url.replace('http://', '')}  ↗", id="open-web",
                             tooltip="Open the web app in your browser")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                for pane in PANES:
                    yield Button(pane.capitalize(), id=f"nav-{pane}", classes="navitem")
                yield Static(id="nav-spacer")
                yield Button("Quit", id="nav-quit", classes="navitem")
            with ContentSwitcher(id="main", initial="home"):
                yield Home(id="home")
                yield DownloadPane(id="download")
                yield SearchPane(id="search")
                yield FilesPane(id="files")
                yield SettingsPane(id="settings")
                yield HelpPane(id="help")
        yield Footer()

    def on_mount(self):
        for field in self.query(Input):
            field.select_on_focus = False
        from sdexe.cli import quiet_sdexe_logger
        quiet_sdexe_logger()  # error logs would print over the screen
        theme = _theme()
        self.register_theme(theme)
        self.theme = theme.name
        self._mark_nav("home")
        self._table_width = ()
        self._fill_results()
        self.set_interval(0.3, self._tick)
        self.set_timer(3.5, self._update_note)
        self._bg(self._load_mcp_state)
        self.query_one("#home-box", Input).focus()
        # Start listening for setting changes only after the first paint.
        self.call_after_refresh(lambda: setattr(self, "ready", True))

    def _update_note(self):
        latest = self.update_info.get("latest")
        from sdexe.cli_home import _newer
        bits = []
        if latest and _newer(latest, __version__):
            bits.append(f"{latest} is out · sdexe update")
        if self.note:
            bits.append(self.note)
        for label in self.query("#ver") if bits else ():
            label.update(Text(f"v{__version__}   " + " · ".join(bits), style=ui.FAINT))

    # background work
    def _bg(self, fn, *args):
        """Run fn off the app's thread. A daemon thread, not a Textual worker:
        those are joined when the app closes, so quitting during a search or a
        long conversion left the terminal hanging until it finished."""
        def run():
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 - a failed job must not take the app down
                if not self._stopping:
                    logging.getLogger("sdexe").exception("terminal app: %s failed", getattr(fn, "__name__", fn))
                    try:
                        self._ui(self._job_failed)
                    except Exception:  # noqa: BLE001
                        pass
        threading.Thread(target=run, daemon=True).start()

    def _job_failed(self):
        """A background job broke in a way nothing planned for. Free what it
        held, so Run, Search and the switches work again without a restart."""
        self._tool_busy = self._searching = None
        for w in self.query("#file-run, #int-zsh, #int-skill"):
            w.disabled = False
        if self._mcp_known:
            self.query_one("#int-mcp", Switch).disabled = False
        for label in self.query("#q-status, #file-status"):
            label.update("")
        self.notify("Something went wrong. Try that again.", severity="error")

    def _ui(self, fn, *args):
        """From a background thread: run fn on the app's thread. Does nothing
        once the app has closed."""
        if self._stopping:
            return
        try:
            self.call_from_thread(fn, *args)
        except Exception:  # noqa: BLE001
            if not self._stopping and self.is_running:
                raise

    def _load_mcp_state(self):
        state = settings.claude_mcp_on()

        def apply():
            sw = self.query_one("#int-mcp", Switch)
            if state is None:
                sw.tooltip = "Claude Code isn't installed"
                return
            with self.prevent(Switch.Changed):
                sw.value = bool(state)
            sw.disabled = False
            self._mcp_known = True
        self._ui(apply)

    def show_file(self, path: str):
        if not reveal(path):
            gone = not Path(path).exists()
            self.notify("That file has been moved or deleted." if gone else f"It's here: {path}",
                        severity="warning" if gone else "information", markup=False)

    def on_resize(self, event: events.Resize):
        if getattr(self, "_table_width", None):  # set once the table has its columns
            self._fill_results(width=event.size.width)

    def _fill_results(self, rows: list | None = None, width: int | None = None):
        """The results table, with the title column taking the room there is.
        Called again when the window is resized."""
        table = self.query_one("#results", DataTable)
        width = width or self.size.width
        narrow = width < 110
        channel_w = 12 if narrow else 22
        title_w = max(20 if narrow else 24, width - 18 - (4 if narrow else 8) - channel_w - 8 - 8 - 12)
        if rows is None:
            if (title_w, channel_w) == self._table_width:
                return
            rows, cursor = self._result_rows, table.cursor_row
        else:
            cursor = 0
        self._result_rows, self._table_width = rows, (title_w, channel_w)
        table.clear(columns=True)
        table.add_column("Title", width=title_w)
        table.add_column("Channel", width=channel_w)
        table.add_column("Length", width=8)
        table.add_column("Views", width=8)
        for n, row in enumerate(rows):
            table.add_row(*row, key=str(n))
        if rows and cursor:
            table.move_cursor(row=min(cursor, len(rows) - 1))

    # navigation
    def _mark_nav(self, pane: str):
        for p in PANES:
            self.query_one(f"#nav-{p}", Button).set_class(p == pane, "-current")

    def action_go(self, pane: str):
        self.query_one("#main", ContentSwitcher).current = pane
        self._mark_nav(pane)
        focus = {"home": "#home-box", "download": "#dl-links", "search": "#q", "files": "#file-list"}.get(pane)
        if focus:
            self.query_one(focus).focus()

    def action_home(self):
        """Esc: home, with the cursor out of the box so letter shortcuts work."""
        self.action_go("home")
        self.query_one("#nav-home", Button).focus()

    def action_open_web(self):
        if self.url:
            webbrowser.open(self.url)
            self.notify("Opened in your browser.")
        else:
            self.notify("The web app isn't running. Start sdexe without --classic.", severity="warning")

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid.startswith("nav-"):
            if bid == "nav-quit":
                self.action_quit()
            else:
                self.action_go(bid[4:])
        elif bid.startswith("tool-"):
            self.open_group(bid[5:])
        elif bid in ("open-web", "help-web"):
            self.action_open_web()
        elif bid == "help-tutorial":
            with self.suspend():
                subprocess.call([sys.executable, "-m", "sdexe", "tutorial"])
        elif bid == "home-go":
            self.home_go()
        elif bid == "dl-go":
            self.start_download()
        elif bid == "q-go":
            self.run_search()
        elif bid in ("q-video", "q-audio"):
            self.download_result(audio=bid == "q-audio")
        elif bid == "q-open":
            r = self._selected_result()
            if r and r["url"]:
                webbrowser.open(r["url"])
        elif bid == "file-run":
            self.run_tool()
        elif bid == "file-browse":
            self.push_screen(FilePicker(Path.cwd()), self._add_file)
        elif bid == "file-clear":
            self.query_one("#file-files", Input).value = ""
        elif bid == "file-show" and self.last_outputs:
            self.show_file(self.last_outputs[0])

    # home: one box for links and searches
    @on(Input.Submitted, "#home-box")
    def home_submitted(self):
        self.home_go()

    def home_go(self):
        from sdexe import cli
        box = self.query_one("#home-box", Input)
        text = box.value.strip()
        if not text:
            links = cli.clipboard_links()
            if not links:
                self.notify("Paste a link, or type what you're looking for.", severity="warning")
                return
            d = download_defaults()
            self.start_download(links, fmt=d["video"], quality=d["quality"], stay=True, from_clipboard=True)
            return
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        urls = [u for u in (cli.normalize_url(t) for t in tokens) if u]
        if urls and len(urls) == len(tokens):
            d = download_defaults()
            if self.start_download(urls, fmt=d["video"], quality=d["quality"], stay=True):
                box.value = ""  # kept when it couldn't start, so the link isn't lost
        else:
            box.value = ""
            self.query_one("#q", Input).value = text
            self.action_go("search")
            self.run_search()

    def open_group(self, group: str):
        self.action_go("files")
        tools = self.query_one("#file-list", OptionList)
        for i, opt in enumerate(tools._options):
            if opt.id and not opt.id.startswith("group-") and opt.id.split(" ")[0] == group:
                tools.highlighted = i
                break

    # downloads
    @on(Input.Submitted, "#dl-links")
    def links_submitted(self):
        self.start_download()

    def start_download(self, links: list | None = None, fmt: str | None = None, quality: str | None = None,
                       stay: bool = False, from_clipboard: bool = False) -> bool:
        """Queue links. True when at least one was started."""
        from sdexe import cli
        links_input = self.query_one("#dl-links", Input)
        typed = links is None
        if typed:
            try:
                links = shlex.split(links_input.value.strip())
            except ValueError:
                links = links_input.value.split()
        urls = list(dict.fromkeys(u for u in (cli.normalize_url(t) for t in links if t) if u))
        if not urls and typed and not links_input.value.strip():
            urls, from_clipboard = cli.clipboard_links(), True
        if not urls:
            if typed and links_input.value.strip():
                self.notify("That isn't a link (https://…). To find something by name, use Search.",
                            severity="warning")
            else:
                self.notify("Paste a link first (https://…). Your clipboard has none either.", severity="warning")
            return False
        fmt = fmt or str(self.query_one("#dl-format", Select).value)
        quality = quality or str(self.query_one("#dl-quality", Select).value)
        tags = [("format", fmt)]
        if quality not in ("source", ""):
            tag = cli.classify_tag(quality)
            if tag:
                tags.append(tag)
        defaults = download_defaults()
        spec = cli.resolve_spec(tags, defaults=defaults)
        folder = _expand(self.query_one("#dl-folder", Input).value.strip() or ".")
        try:
            folder.mkdir(parents=True, exist_ok=True)
            folder = folder.resolve()
        except OSError as e:
            self.notify(f"Can't use that folder: {e.strerror or e}", severity="error", markup=False)
            return False
        playlist = self.query_one("#dl-playlist", Switch).value
        # What makes two downloads of one link the same download.
        key = (spec.fmt, spec.height, spec.fps, spec.bitrate, spec.best, str(folder), playlist)
        now = time.monotonic()
        busy, failed = set(), set()
        for dl in self.downloaders:
            if getattr(dl, "tui_key", None) == key:
                with dl.lock:
                    busy |= {i.url for i in dl.items if i.status in ("queued", "running")}
                    failed |= {i.url for i in dl.items if i.status == "failed"}
        # The same link again while it's still downloading (Enter twice, a
        # double click, the clipboard holding what was just pasted): once is enough.
        # The 2 seconds cover a playlist link, which is replaced by its videos.
        fresh = [u for u in urls if u not in busy
                 and (u in failed or now - self._submitted.get((key, u), -10) > 2)]
        if not fresh:
            self.notify("Already downloading that.", severity="warning")
            if typed:
                links_input.value = ""
            return False
        for u in fresh:
            self._submitted[(key, u)] = now
        args = Namespace(quiet=True, json=False, playlist=playlist, limit=None, jobs=defaults["jobs"],
                         verbose=False, cookies_from_browser=None)
        dl = cli.Downloader(fresh, spec, args, folder, defaults=defaults, silent=True)
        dl.tui_key = key
        dl.start()
        self.downloaders.append(dl)
        if typed:
            links_input.value = ""
        if not stay:
            self.action_go("download")
            # A short window scrolls this page; bring the list of downloads into view.
            self.call_after_refresh(self.query_one("#download").scroll_end, animate=False)
        where = " from your clipboard" if from_clipboard else ""
        self.notify(f"Downloading {len(fresh)} {'link' if len(fresh) == 1 else 'links'}{where} as {spec.label}.")
        return True

    def _tick(self):
        try:
            dl_box = self.query_one("#dl-rows", VerticalScroll)
            home_box = self.query_one("#home-recent", Vertical)
        except NoMatches:
            return  # the timer fired while the app was closing; the screen is gone
        count = done = 0
        for dl in self.downloaders:
            with dl.lock:
                items = list(dl.items)
            workers = getattr(dl, "_workers", None)
            if workers and not dl.q.unfinished_tasks:
                # Everything it was given is finished. Its threads would wait
                # for more forever, a few more with every download started.
                dl._workers = []
                for _ in workers:
                    dl.q.put(None)
            for item in items:
                status = item.status  # read once: a download thread changes it under us
                rows = self.rows.get(id(item))
                if status == "expanded":
                    # A playlist or search link. Its videos have rows of their own.
                    if rows:
                        for row in rows:
                            row.remove()
                        rows.clear()
                    continue
                count += 1
                done += status == "done"
                if rows is None:
                    rows = [DownloadRow(item), DownloadRow(item)]
                    self.rows[id(item)] = rows
                    dl_box.mount(rows[0])
                    home_box.mount(rows[1], before=0) if home_box.children else home_box.mount(rows[1])
                    for extra in list(home_box.children)[5:]:  # Home lists the newest five
                        extra.remove()
                        listed = self.rows.get(id(extra.item), [])
                        if extra in listed:
                            listed.remove(extra)
                    continue  # drawn on the next tick, once mounted
                finished = status in ("done", "failed")
                for n, row in enumerate(rows):
                    if not row.ready or (finished and row.last == status):
                        continue
                    row.sync(status)
                    first_finish = n == 0 and finished and row.last != status  # rows[0]: the Download page's
                    row.last = status
                    if first_finish:
                        if status == "done":
                            self.notify(f"Saved {item.path.name if item.path else item.name}", markup=False)
                        else:
                            self.notify(_tui_error(item.error), title=item.name[:50], severity="error", markup=False)
        if count:
            heading = f"THIS SESSION · {done} of {count} saved"
            if heading != self._heading:
                self._heading = heading
                self.query_one("#recent-empty", Label).display = False
                self.query_one("#dl-heading", Label).update(heading)

    # search
    @on(Input.Submitted, "#q")
    def query_submitted(self):
        self.run_search()

    def run_search(self):
        q = self.query_one("#q", Input).value.strip()
        if not q:
            self.notify("Type what you're looking for.", severity="warning")
            return
        source = str(self.query_one("#q-source", Select).value)
        if self._searching == (q, source):
            return  # Enter twice: that search is already on its way
        self._searching = (q, source)
        self._search_seq += 1
        self.query_one("#q-status", Label).update("searching…")
        self._bg(self._search, q, source, self._search_seq)

    def _search(self, q: str, source: str, seq: int):
        from sdexe.cli_search import search, _views
        rows, error = [], None
        try:
            results = search(q, 20, source)
            for r in results:
                rows.append((Text(str(r["title"])), Text(str(r["channel"] or ""), style=ui.MUTED),
                             Text(fmt_time(r["duration"]) if r["duration"] else "", style=ui.MUTED),
                             Text(_views(r["views"]), style=ui.MUTED)))
        except Exception as e:  # noqa: BLE001
            from sdexe.app import _friendly_download_error
            results, rows, error = [], [], _friendly_download_error(str(e), cli=True)

        def show():
            if seq != self._search_seq:
                return  # a newer search was started; this one finishing late must not replace it
            self._searching = None
            self.search_results = results
            self._fill_results(rows)
            for b in ("#q-video", "#q-audio", "#q-open"):
                self.query_one(b, Button).disabled = not results
            self.query_one("#q-video", Button).variant = "primary" if results else "default"
            self.query_one("#q-status", Label).update("failed" if error else f"{len(results)} results")
            if error:
                # A toast: the status line is one short row and cut the message off.
                self.notify(error, severity="error", markup=False)
            if results and self.query_one("#main", ContentSwitcher).current == "search":
                self.query_one("#results", DataTable).focus()
        self._ui(show)

    def _selected_result(self):
        table = self.query_one("#results", DataTable)
        if not self.search_results or table.cursor_row is None:
            return None
        return self.search_results[min(table.cursor_row, len(self.search_results) - 1)]

    @on(DataTable.RowSelected, "#results")
    def result_chosen(self):
        self.query_one("#q-video", Button).focus()

    def download_result(self, audio: bool):
        r = self._selected_result()
        if not r or not r["url"]:
            return
        d = download_defaults()
        self.start_download([r["url"]], fmt=d["audio"] if audio else d["video"],
                            quality=(d["bitrate"] if d["audio"] == "mp3" else "source") if audio else d["quality"])

    # files
    @on(OptionList.OptionSelected, "#file-list")
    async def tool_chosen(self, event: OptionList.OptionSelected):
        from sdexe.cli_tools import _BY_NAME
        group, _, name = event.option.id.partition(" ")
        cmd = _BY_NAME[(group, name)]
        self.current_cmd = cmd
        self.last_outputs = []
        self._form_seq += 1
        form = self.query_one("#file-form", VerticalScroll)
        await form.remove_children()
        busy = self._tool_busy  # read after the await: the running tool may just have finished
        widgets = [Horizontal(Label(Text(cmd.summary[:1].upper() + cmd.summary[1:])),
                              Button("Run", variant="primary", id="file-run", disabled=bool(busy)), id="file-head"),
                   Label(f"sdexe {cmd.full}", classes="faint")]
        if cmd.inputs == "none":
            widgets += [Label(cmd.text_arg.capitalize(), classes="label"),
                        Input(placeholder="Type here", id="file-text", select_on_focus=False)]
        else:
            what = {"many": "Files, in order", "pair": cmd.inputs_help.capitalize(), "each": "Files"}[cmd.inputs]
            widgets += [Label(Text(f"{what} · drag them in, or browse"), classes="label"),
                        Horizontal(LinesInput(placeholder="Drop files here", id="file-files", classes="grow", files=True),
                                   Button("Browse", id="file-browse"), Button("Clear", id="file-clear"),
                                   classes="inline")]
        for arg in cmd.args:
            label = arg.flag.lstrip("-").replace("-", " ").capitalize()
            hint = arg.help or ""
            if arg.required:
                hint = (hint + " · required").lstrip(" ·")
            widgets.append(Label(Text.assemble((label, ui.LIGHT), (f"   {hint}" if hint else "", ui.FAINT)),
                                 classes="label"))
            if arg.type is bool:
                widgets.append(Switch(value=False, id=f"arg-{arg.dest}"))
            elif arg.choices:
                # Select.BLANK is False in Textual 8; passing it as a value crashed the app.
                options = [(str(c), str(c)) for c in arg.choices]
                if arg.default is not None:
                    widgets.append(Select(options, value=str(arg.default), allow_blank=False,
                                          id=f"arg-{arg.dest}", compact=True))
                else:
                    widgets.append(Select(options, allow_blank=True, prompt="choose", id=f"arg-{arg.dest}",
                                          compact=True))
            else:
                widgets.append(Input(value="" if arg.default in (None, "") else str(arg.default),
                                     placeholder="required" if arg.required else "optional", id=f"arg-{arg.dest}",
                                     select_on_focus=False))
        text_out = cmd.name in ("text", "ocr", "ascii")
        widgets += [Label("Save to" + (" · leave empty to show the text here" if text_out else ""), classes="label"),
                    Input(value="" if text_out else str(Path.cwd()), id="file-out", select_on_focus=False),
                    Horizontal(Label(Text(f"working on {busy}…" if busy else ""), id="file-status", classes="hint"),
                               Button("Show in Finder" if sys.platform == "darwin" else "Show file",
                                      id="file-show", disabled=True), classes="inline"),
                    Static("", id="file-output")]
        await form.mount(*widgets)
        if cmd.inputs != "none":
            self.query_one("#file-files", Input).focus()

    def _add_file(self, path: str | None):
        if not path:
            return
        box = self.query_one("#file-files", Input)
        box.value = (box.value + " " + _quote_path(path)).strip()

    def run_tool(self):
        cmd = self.current_cmd
        if not cmd or self._tool_busy:
            return
        argv = cmd.full.split()
        try:
            if cmd.inputs != "none":
                files = _split_paths(self.query_one("#file-files", Input).value)
                if not files:
                    self.notify("Add a file first: drag it in, or click Browse.", severity="warning")
                    return
                for f in files:
                    f = str(_expand(f))
                    # "-notes.pdf" would be read as an option.
                    argv.append(os.path.join(os.curdir, f) if f.startswith("-") else f)
        except ValueError:
            self.notify("Those file names have an unmatched quote.", severity="error")
            return
        for arg in cmd.args:
            w = self.query_one(f"#arg-{arg.dest}")
            if isinstance(w, Switch):
                if w.value:
                    argv.append(arg.flag)
            else:
                v = w.value
                if v in (None, "", Select.BLANK, Select.NULL):
                    if arg.required:
                        self.notify(f"{arg.flag.lstrip('-').capitalize()} is required.", severity="warning")
                        return
                    continue
                argv.append(f"{arg.flag}={v}")  # "--text=-DRAFT-", not "--text -DRAFT-"
        out = self.query_one("#file-out", Input).value.strip()
        if out:
            argv += ["-o", str(_expand(out))]
        if cmd.inputs == "none":
            text = self.query_one("#file-text", Input).value
            if not text.strip():
                self.notify(f"Type the {cmd.text_arg} first.", severity="warning")
                return
            argv += ["--", text]
        self.query_one("#file-status", Label).update("working…")
        self.query_one("#file-run", Button).disabled = True
        self._tool_busy = cmd.full
        self._bg(self._run_tool, argv, self._form_seq)

    def _tool_json(self, argv: list) -> dict:
        """Run `sdexe <argv> --json` and return its result document. Always a
        dict with a list under "results", whatever the command printed."""
        cut = argv.index("--") if "--" in argv else len(argv)
        cmd = [sys.executable, "-m", "sdexe", *argv[:cut], "--json", *argv[cut:]]
        out = err = ""
        try:
            # stdin: ffmpeg reads keys from an inherited terminal, and would
            # take the ones typed into this app. UTF-8: file names in the JSON.
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, encoding="utf-8", errors="replace",
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            self._tool_proc = proc
            out, err = proc.communicate()
        except OSError as e:
            err = str(e)
        finally:
            self._tool_proc = None
        try:
            doc = json.loads(out)
        except ValueError:
            doc = None
        if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
            lines = (err or out).strip().splitlines()
            doc = {"ok": False, "results": [{"ok": False, "error": lines[-1] if lines else "failed"}]}
        return doc

    def _run_tool(self, argv: list, form: int):
        doc = self._tool_json(argv)
        out, outputs = Text(), []
        try:
            for res in doc["results"]:
                if not res.get("ok"):
                    out.append("✗ ", style="#ef6f6f")
                    out.append(f"{res.get('error') or 'failed'}\n", style="#ef6f6f")
                    continue
                for o in res.get("outputs") or []:
                    outputs.append(o["path"])
                    out.append("✓ ", style="#6fcf8f")
                    out.append(_short(o["path"]), style=ui.TEXT)
                    out.append(f"  {fmt_size(o.get('size_bytes') or 0)}\n", style=ui.MUTED)
                if res.get("text"):
                    out.append(str(res["text"])[:20000])
                if res.get("data"):
                    for k, v in res["data"].items():
                        out.append(f"{k}  ", style=ui.MUTED)
                        out.append(f"{v}\n")
            ok = bool(doc.get("ok")) and all(res.get("ok") for res in doc["results"])
        except (AttributeError, KeyError, TypeError):  # not the document the tools print
            out, outputs, ok = Text("✗ failed\n", style="#ef6f6f"), [], False

        def show():
            self._tool_busy = None
            for run in self.query("#file-run"):
                run.disabled = False
            if ok and outputs:
                n = len(outputs)
                self.notify(f"Saved {n} file{'s' if n != 1 else ''}.")
            if form != self._form_seq:
                # Another tool's form is open now; this result isn't its.
                for status in self.query("#file-status"):
                    status.update("")
                if not ok:
                    self.notify(out.plain.strip()[:300] or "Something failed.", severity="error", markup=False)
                return
            self.last_outputs = outputs
            self.query_one("#file-output", Static).update(out)
            self.query_one("#file-status", Label).update("Done." if ok else "Something failed.")
            self.query_one("#file-show", Button).disabled = not outputs
        self._ui(show)

    # settings
    @on(Switch.Changed)
    def switch_changed(self, event: Switch.Changed):
        if not self.ready:
            return  # widgets report their initial values on mount; that isn't a change
        sid = event.switch.id or ""
        if sid.startswith("set-"):
            self._save(sid[4:], event.value)
        elif sid.startswith("int-") and event.switch.has_focus:
            event.switch.disabled = True  # one change at a time; back on when it's done
            self._bg(self._integration, sid[4:], event.value)

    @on(Select.Changed)
    def select_changed(self, event: Select.Changed):
        if not self.ready:
            return
        sid = event.select.id or ""
        if sid.startswith("set-") and event.value not in (Select.BLANK, Select.NULL):
            self._save(sid[4:], event.value)

    @on(Input.Submitted)
    def input_submitted(self, event: Input.Submitted):
        sid = event.input.id or ""
        if sid.startswith("set-"):
            self._save(sid[4:], event.value)

    @on(Input.Blurred)
    def input_blurred(self, event: Input.Blurred):
        sid = event.input.id or ""
        if sid.startswith("set-"):
            self._save(sid[4:], event.value, quiet_if_same=True)

    def _save(self, key: str, value, quiet_if_same: bool = False):
        s = settings.BY_KEY[key]
        old = settings.get(key)
        try:
            if quiet_if_same and s.parse(value) == old:
                return
            new = settings.put(key, value)
        except (ValueError, RuntimeError, OSError) as e:  # RuntimeError: a folder like "~nobody/x"
            self.notify(str(e), severity="error", markup=False)
            return
        self.query_one("#settings-note", Label).update(Text(f"Saved · {s.label}: {s.show(new)}"))
        if key == "accent":
            theme = _theme()
            self.register_theme(theme)
            self.theme = theme.name
        if key.startswith("dl_"):
            self.query_one("#home-hint", Label).update(_home_hint())
        if key == "dl_folder":
            # Home and Search save into the Download page's folder box. Keep it
            # on the setting unless a different folder was typed there.
            box = self.query_one("#dl-folder", Input)
            if box.value.strip() in ("", old or str(Path.cwd())):
                box.value = new or str(Path.cwd())

    def _integration(self, which: str, on_: bool):
        fn = {"zsh": settings.set_zsh_alias, "mcp": settings.set_claude_mcp, "skill": settings.set_skill}[which]
        state = {"zsh": settings.zsh_alias_on, "mcp": settings.claude_mcp_on, "skill": settings.skill_on}[which]
        try:
            msg = fn(on_)
            sev = "information"
        except Exception as e:  # noqa: BLE001
            msg, sev = str(e), "error"
        try:
            now = bool(state())  # what really happened: a failed change must not leave the switch on
        except Exception:  # noqa: BLE001
            now = on_

        def show():
            sw = self.query_one(f"#int-{which}", Switch)
            with self.prevent(Switch.Changed):
                sw.value = now
            sw.disabled = False
            if self.focused is None:
                sw.focus()
            self.notify(msg, severity=sev, markup=False)
        self._ui(show)

    def stop_work(self, wait: float = 1.5):
        """The app is closing: stop what it started. Cancel downloads and
        remove their partial files, and stop a file tool that is still running."""
        self._stopping = True
        for dl in self.downloaders:
            dl.cancel.set()
        proc = self._tool_proc
        if proc and proc.poll() is None:
            try:
                # Ctrl+C rather than a kill where it exists: the tool stops its
                # own ffmpeg and removes its temporary files on the way out.
                proc.send_signal(signal.SIGINT) if os.name == "posix" else proc.terminate()
            except OSError:
                pass
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and (
                any(getattr(dl, "q", None) is not None and dl.q.unfinished_tasks for dl in self.downloaders)
                or (proc and proc.poll() is None)):
            time.sleep(0.05)
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        for dl in self.downloaders:
            for tmp in list(dl.tmp_dirs):
                shutil.rmtree(tmp, ignore_errors=True)

    def action_quit(self):
        self._stopping = True
        for dl in self.downloaders:
            dl.cancel.set()
        self.exit()


def run(url: str | None = None, note: str = "", update: dict | None = None):
    app = SdexeApp(url=url, note=note, update=update)
    try:
        app.run()
    finally:
        app.stop_work()
