"""The clickable terminal app `sdexe` opens while the web app runs.

Built on Textual: buttons, fields, lists and progress bars that work with the
mouse or the keyboard. The look is black and gray with one accent colour, used
only for the main action, the current place and progress.

It drives the same code as the commands: cli.Downloader for downloads,
cli_search for search, `python -m sdexe ...` for the file tools, and the
settings table for settings.
"""

import json
import shlex
import subprocess
import sys
import webbrowser
from argparse import Namespace
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
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
#home-recent {{ height: auto; }}
#recent-empty {{ color: {ui.FAINT}; }}

/* Downloads */
#dl-rows {{ height: 1fr; }}
.dlrow {{ height: 1; margin: 0 0 1 0; }}
.dlrow .icon {{ width: 2; }}
.dlrow .name {{ width: 1fr; min-width: 16; }}
.dlrow ProgressBar {{ width: 24; }}
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

/* File picker */
FilePicker {{ align: center middle; background: $background 60%; }}
#picker {{ width: 80%; height: 80%; background: {SURFACE}; border: round {LINE}; padding: 1 2; }}
#picker DirectoryTree {{ height: 1fr; background: {SURFACE}; }}
"""


def _themed(renderable) -> Text:
    """Render something drawn with sdexe's Rich theme (styles like "muted")
    into plain coloured Text; Textual doesn't know those style names."""
    from rich.console import Console
    c = Console(theme=ui.theme(), width=110, force_terminal=True, color_system="truecolor", highlight=False)
    with c.capture() as cap:
        c.print(renderable)
    return Text.from_ansi(cap.get().rstrip("\n"))


def _short(path: str) -> str:
    p = Path(path)
    try:
        return "./" + str(p.relative_to(Path.cwd()))
    except ValueError:
        return str(p).replace(str(Path.home()), "~", 1)


def reveal(path: str):
    """Show a file in Finder / the file manager."""
    p = Path(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])


# ── Pieces ──

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


class DownloadRow(Horizontal):
    def __init__(self, item):
        super().__init__(classes="dlrow")
        self.item = item
        self.last = None

    def compose(self) -> ComposeResult:
        yield Label("·", classes="icon faint")
        yield Label(self.item.name, classes="name")
        yield ProgressBar(total=100, show_eta=False, show_percentage=False)
        yield Label("waiting", classes="detail")
        yield Button("show", classes="show", disabled=True)

    def sync(self):
        i = self.item
        icon, name, bar, detail, show = (self.query_one(".icon", Label), self.query_one(".name", Label),
                                         self.query_one(ProgressBar), self.query_one(".detail", Label),
                                         self.query_one(".show", Button))
        name.update(i.name)
        if i.status == "running":
            icon.update("↓")
            if i.stage == "downloading" and i.total:
                pct = min(100.0, i.downloaded / i.total * 100)
                bar.update(total=100, progress=pct)
                bits = [f"{pct:.0f}%", f"{fmt_size(i.downloaded)} of {fmt_size(i.total)}"]
                if i.speed:
                    bits.append(f"{fmt_size(i.speed)}/s")
                detail.update("  ".join(bits))
            else:
                bar.update(total=None)
                detail.update(i.stage)
        elif i.status == "done":
            icon.update(Text("✓", style="#6fcf8f"))
            bar.update(total=100, progress=100)
            bits = [b for b in (i.quality(), fmt_size(i.path.stat().st_size) if i.path and i.path.exists() else "") if b]
            detail.update(" · ".join(bits))
            show.disabled = False
        elif i.status == "failed":
            icon.update(Text("✗", style="#ef6f6f"))
            bar.display = False
            detail.update(Text(i.error, style="#ef6f6f"))
            detail.styles.width = "1fr"
            show.display = False

    @on(Button.Pressed, ".show")
    def show(self, event: Button.Pressed):
        event.stop()
        if self.item.path:
            reveal(str(self.item.path))


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


class Home(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Paste a link, or type what you're looking for", classes="title")
        with Horizontal(classes="bar"):
            yield Input(placeholder="https://…   or   artist - song", id="home-box")
            yield Button("Go", variant="primary", id="home-go")
        yield Label(f"A link downloads right away as {_default_label()}. Words search YouTube.",
                    classes="hint", id="home-hint")
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
        yield Input(placeholder="Paste one or more links, separated by spaces", id="dl-links")
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


class HelpPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Help", classes="title")
        yield Label("Everything here also works as a typed command.", classes="hint")
        with Horizontal(classes="inline"):
            yield Button("Take the tutorial", id="help-tutorial")
            yield Button("Open the web app", id="help-web")
        yield Label("COMMANDS", classes="section")
        yield Static(_themed(ui.rows([
            ('sdexe download "<link>"', "save video or audio · -mp3, -a, -720p, --best"),
            ('sdexe search "<words>"', "find by name"),
            ('sdexe info "<link>"', "qualities and sizes, without downloading"),
            ("sdexe pdf | image | audio | video <command>", "the file tools"),
            ("sdexe convert <file> -f FMT", "csv, json, yaml, xml, md, xlsx…"),
            ("sdexe settings", "the settings, full screen"),
            ("sdexe mcp", "every tool for Claude, Cursor & co."),
            ("sdexe --classic", "start without this app"),
        ], indent=0)))
        yield Label("KEYS", classes="section")
        yield Static(_themed(ui.rows([("d  s  f", "download · search · files"), (",", "settings"),
                                      ("o", "open the web app"), ("esc", "home, and out of the text box"), ("ctrl+q", "quit")],
                                     indent=0, commands=False)))


# ── App ──

PANES = ("home", "download", "search", "files", "settings", "help")


class SdexeApp(App):
    TITLE = "sdexe"
    CSS = CSS
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
        self.rows = {}
        self.search_results = []
        self.current_cmd = None
        self.last_outputs = []

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
        table = self.query_one("#results", DataTable)
        title_w = max(24, self.size.width - 18 - 8 - 22 - 8 - 8 - 12)
        table.add_column("Title", width=title_w)
        table.add_column("Channel", width=22)
        table.add_column("Length", width=8)
        table.add_column("Views", width=8)
        self.set_interval(0.3, self._tick)
        self.set_timer(3.5, self._update_note)
        self._load_mcp_state()
        self.query_one("#home-box", Input).focus()

    def _update_note(self):
        latest = self.update_info.get("latest")
        from sdexe.cli_home import _newer
        bits = []
        if latest and _newer(latest, __version__):
            bits.append(f"{latest} is out · sdexe update")
        if self.note:
            bits.append(self.note)
        if bits:
            self.query_one("#ver", Label).update(Text(f"v{__version__}   " + " · ".join(bits), style=ui.FAINT))

    @work(thread=True)
    def _load_mcp_state(self):
        state = settings.claude_mcp_on()

        def apply():
            sw = self.query_one("#int-mcp", Switch)
            if state is None:
                sw.tooltip = "Claude Code isn't installed"
                return
            sw.value = bool(state)
            sw.disabled = False
        self.call_from_thread(apply)

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
            if r:
                webbrowser.open(r["url"])
        elif bid == "file-run":
            self.run_tool()
        elif bid == "file-browse":
            self.push_screen(FilePicker(Path.cwd()), self._add_file)
        elif bid == "file-clear":
            self.query_one("#file-files", Input).value = ""
        elif bid == "file-show" and self.last_outputs:
            reveal(self.last_outputs[0])

    # home: one box for links and searches
    @on(Input.Submitted, "#home-box")
    def home_submitted(self):
        self.home_go()

    def home_go(self):
        from sdexe import cli
        box = self.query_one("#home-box", Input)
        text = box.value.strip()
        if not text:
            self.notify("Paste a link, or type what you're looking for.", severity="warning")
            return
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        urls = [u for u in (cli.normalize_url(t) for t in tokens) if u]
        box.value = ""
        if urls and len(urls) == len(tokens):
            d = download_defaults()
            self.start_download(urls, fmt=d["video"], quality=d["quality"], stay=True)
        else:
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
                       stay: bool = False):
        from sdexe import cli
        links_input = self.query_one("#dl-links", Input)
        if links is None:
            try:
                links = shlex.split(links_input.value.strip())
            except ValueError:
                links = links_input.value.split()
        urls = [u for u in (cli.normalize_url(t) for t in links if t) if u]
        if not urls:
            self.notify("Paste a link first (https://…).", severity="warning")
            return
        fmt = fmt or str(self.query_one("#dl-format", Select).value)
        quality = quality or str(self.query_one("#dl-quality", Select).value)
        tags = [("format", fmt)]
        if quality not in ("source", ""):
            tag = cli.classify_tag(quality)
            if tag:
                tags.append(tag)
        defaults = download_defaults()
        spec = cli.resolve_spec(tags, defaults=defaults)
        folder = Path(self.query_one("#dl-folder", Input).value.strip() or ".").expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.notify(f"Can't use that folder: {e.strerror}", severity="error")
            return
        args = Namespace(quiet=True, json=False, playlist=self.query_one("#dl-playlist", Switch).value,
                         limit=None, jobs=defaults["jobs"], verbose=False, cookies_from_browser=None)
        dl = cli.Downloader(urls, spec, args, folder.resolve(), defaults=defaults, silent=True)
        dl.start()
        self.downloaders.append(dl)
        links_input.value = ""
        if not stay:
            self.action_go("download")
        self.notify(f"Downloading {len(urls)} {'link' if len(urls) == 1 else 'links'} as {spec.label}.")

    def _tick(self):
        dl_box = self.query_one("#dl-rows", VerticalScroll)
        home_box = self.query_one("#home-recent", Vertical)
        count = 0
        for dl in self.downloaders:
            with dl.lock:
                items = [i for i in dl.items if i.status != "expanded"]
            for item in items:
                count += 1
                rows = self.rows.get(id(item))
                if rows is None:
                    rows = [DownloadRow(item), DownloadRow(item)]
                    self.rows[id(item)] = rows
                    dl_box.mount(rows[0])
                    home_box.mount(rows[1], before=0) if home_box.children else home_box.mount(rows[1])
                    for extra in list(home_box.children)[5:]:
                        extra.remove()
                    continue  # sync once mounted
                for row in rows:
                    if not row.is_mounted or (item.status in ("done", "failed") and row.last == item.status):
                        continue
                    row.sync()
                    first_finish = row is rows[0] and item.status != row.last and item.status in ("done", "failed")
                    row.last = item.status
                    if first_finish:
                        if item.status == "done":
                            self.notify(f"Saved {item.path.name}")
                        else:
                            self.notify(item.error, title=item.name[:50], severity="error")
        if count:
            self.query_one("#recent-empty", Label).display = False
            done = sum(1 for dl in self.downloaders for i in dl.items if i.status == "done")
            self.query_one("#dl-heading", Label).update(f"THIS SESSION · {done} of {count} saved")

    # search
    @on(Input.Submitted, "#q")
    def query_submitted(self):
        self.run_search()

    def run_search(self):
        q = self.query_one("#q", Input).value.strip()
        if not q:
            self.notify("Type what you're looking for.", severity="warning")
            return
        self.query_one("#q-status", Label).update("searching…")
        self._search(q, str(self.query_one("#q-source", Select).value))

    @work(thread=True, exclusive=True, group="search")
    def _search(self, q: str, source: str):
        from sdexe.cli_search import search, _views
        try:
            results = search(q, 20, source)
            error = None
        except Exception as e:  # noqa: BLE001
            from sdexe.app import _friendly_download_error
            results, error = [], _friendly_download_error(str(e), cli=True)

        def show():
            self.search_results = results
            table = self.query_one("#results", DataTable)
            table.clear()
            for i, r in enumerate(results):
                table.add_row(r["title"], Text(r["channel"], style=ui.MUTED),
                              Text(fmt_time(r["duration"]) if r["duration"] else "", style=ui.MUTED),
                              Text(_views(r["views"]), style=ui.MUTED), key=str(i))
            for b in ("#q-video", "#q-audio", "#q-open"):
                self.query_one(b, Button).disabled = not results
            self.query_one("#q-video", Button).variant = "primary" if results else "default"
            self.query_one("#q-status", Label).update(error or f"{len(results)} results")
            if results:
                table.focus()
        self.call_from_thread(show)

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
        if not r:
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
        form = self.query_one("#file-form", VerticalScroll)
        await form.remove_children()
        widgets = [Horizontal(Label(cmd.summary[:1].upper() + cmd.summary[1:]),
                              Button("Run", variant="primary", id="file-run"), id="file-head"),
                   Label(f"sdexe {cmd.full}", classes="faint")]
        if cmd.inputs == "none":
            widgets += [Label(cmd.text_arg.capitalize(), classes="label"),
                        Input(placeholder="Type here", id="file-text")]
        else:
            what = {"many": "Files, in order", "pair": cmd.inputs_help.capitalize(), "each": "Files"}[cmd.inputs]
            widgets += [Label(f"{what} · drag them in, or browse", classes="label"),
                        Horizontal(Input(placeholder="Drop files here", id="file-files", classes="grow"),
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
                widgets.append(Select([(str(c), str(c)) for c in arg.choices],
                                      value=str(arg.default) if arg.default is not None else Select.BLANK,
                                      allow_blank=arg.default is None, id=f"arg-{arg.dest}", compact=True))
            else:
                widgets.append(Input(value="" if arg.default in (None, "") else str(arg.default),
                                     placeholder="required" if arg.required else "optional", id=f"arg-{arg.dest}"))
        text_out = cmd.name in ("text", "ocr", "ascii")
        widgets += [Label("Save to" + (" · leave empty to show the text here" if text_out else ""), classes="label"),
                    Input(value="" if text_out else str(Path.cwd()), id="file-out"),
                    Horizontal(Label("", id="file-status", classes="hint"),
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
        box.value = (box.value + " " + shlex.quote(path)).strip()

    def run_tool(self):
        cmd = self.current_cmd
        if not cmd:
            return
        argv = cmd.full.split()
        try:
            if cmd.inputs != "none":
                files = shlex.split(self.query_one("#file-files", Input).value)
                if not files:
                    self.notify("Add a file first: drag it in, or click Browse.", severity="warning")
                    return
                argv += [str(Path(f).expanduser()) for f in files]
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
                argv += [arg.flag, str(v)]
        out = self.query_one("#file-out", Input).value.strip()
        if out:
            argv += ["-o", str(Path(out).expanduser())]
        if cmd.inputs == "none":
            argv += ["--", self.query_one("#file-text", Input).value]
        self.query_one("#file-status", Label).update("working…")
        self.query_one("#file-run", Button).disabled = True
        self._run_tool(argv)

    @work(thread=True, exclusive=True, group="tool")
    def _run_tool(self, argv: list):
        cut = argv.index("--") if "--" in argv else len(argv)
        cmd = [sys.executable, "-m", "sdexe", *argv[:cut], "--json", *argv[cut:]]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path.cwd()))
        try:
            doc = json.loads(r.stdout)
        except json.JSONDecodeError:
            msg = (r.stderr or r.stdout).strip().splitlines()
            doc = {"ok": False, "results": [{"ok": False, "error": msg[-1] if msg else "failed"}]}

        def show():
            out = Text()
            self.last_outputs = []
            for res in doc.get("results", []):
                if not res.get("ok"):
                    out.append("✗ ", style="#ef6f6f")
                    out.append(res.get("error", "failed") + "\n", style="#ef6f6f")
                    continue
                for o in res.get("outputs") or []:
                    self.last_outputs.append(o["path"])
                    out.append("✓ ", style="#6fcf8f")
                    out.append(_short(o["path"]), style=ui.TEXT)
                    out.append(f"  {fmt_size(o['size_bytes'])}\n", style=ui.MUTED)
                if res.get("text"):
                    out.append(res["text"][:20000])
                if res.get("data"):
                    for k, v in res["data"].items():
                        out.append(f"{k}  ", style=ui.MUTED)
                        out.append(f"{v}\n")
            self.query_one("#file-output", Static).update(out)
            self.query_one("#file-run", Button).disabled = False
            ok = doc.get("ok")
            self.query_one("#file-status", Label).update("Done." if ok else "Something failed.")
            self.query_one("#file-show", Button).disabled = not self.last_outputs
            if ok and self.last_outputs:
                n = len(self.last_outputs)
                self.notify(f"Saved {n} file{'s' if n != 1 else ''}.")
        self.call_from_thread(show)

    # settings
    @on(Switch.Changed)
    def switch_changed(self, event: Switch.Changed):
        sid = event.switch.id or ""
        if sid.startswith("set-"):
            self._save(sid[4:], event.value)
        elif sid.startswith("int-") and event.switch.has_focus:
            self._integration(sid[4:], event.value)

    @on(Select.Changed)
    def select_changed(self, event: Select.Changed):
        sid = event.select.id or ""
        if sid.startswith("set-") and event.value is not Select.BLANK:
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
        try:
            if quiet_if_same and s.parse(value) == settings.get(key):
                return
            new = settings.put(key, value)
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.query_one("#settings-note", Label).update(f"Saved · {s.label}: {s.show(new)}")
        if key == "accent":
            theme = _theme()
            self.register_theme(theme)
            self.theme = theme.name
        if key.startswith("dl_"):
            self.query_one("#home-hint", Label).update(
                f"A link downloads right away as {_default_label()}. Words search YouTube.")

    @work(thread=True, exclusive=True, group="integration")
    def _integration(self, which: str, on_: bool):
        fn = {"zsh": settings.set_zsh_alias, "mcp": settings.set_claude_mcp, "skill": settings.set_skill}[which]
        try:
            msg = fn(on_)
            sev = "information"
        except Exception as e:  # noqa: BLE001
            msg, sev = str(e), "error"
        self.call_from_thread(self.notify, msg, severity=sev)

    def action_quit(self):
        for dl in self.downloaders:
            dl.cancel.set()
        self.exit()


def run(url: str | None = None, note: str = "", update: dict | None = None):
    SdexeApp(url=url, note=note, update=update).run()
