"""The clickable terminal app `sdexe` opens while the web app runs.

Built on Textual: buttons, fields, lists and progress bars that work with the
mouse or the keyboard. It drives the same code as the commands:
cli.Downloader for downloads, cli_search for search, `python -m sdexe ...` for
the file tools, and the settings table for settings.
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
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (Button, ContentSwitcher, DataTable, DirectoryTree, Footer, Input, Label,
                             OptionList, ProgressBar, Select, Static, Switch)
from textual.widgets.option_list import Option

from sdexe import __version__, settings, ui
from sdexe.cli import download_defaults, fmt_size, fmt_time

# ── Look ──

def _theme() -> Theme:
    a, b = ui.colors()
    return Theme(
        name=f"sdexe-{ui.accent_name()}", primary=a, secondary=b, accent=b,
        foreground="#e6e7ec", background="#121318", surface="#1a1b22", panel="#23252e",
        success="#4ade80", warning="#fbbf24", error="#f87171", dark=True,
    )


CSS = """
Screen { background: $background; }

#top { height: 4; padding: 0 2; background: $surface; }
#brand { width: auto; padding: 1 0 0 0; }
#status { width: 1fr; padding: 1 0 0 4; }
#open-web { margin: 1 0 0 1; min-width: 20; }

#body { height: 1fr; }
#nav { width: 20; padding: 1 1; background: $surface; border-right: tall $panel; }
#nav Button { width: 100%; margin: 0; border: none; height: 3; background: $surface; text-style: none;
               content-align: left middle; padding: 0 2; }
#nav Button:hover { background: $panel; }
#nav Button.-current { background: $panel; color: $primary; text-style: bold; }
#main { width: 1fr; padding: 1 3; }

.title { text-style: bold; color: $foreground; margin: 0 0 0 0; }
.subtitle { color: $text-muted; margin: 0 0 1 0; }
.section { color: $primary; text-style: bold; margin: 1 0 0 0; }
.hint { color: $text-muted; }
.field-label { color: $text-muted; margin: 1 0 0 0; }

/* Home */
#tiles { grid-size: 3; grid-rows: 8; grid-gutter: 1 2; height: auto; margin: 1 0; }
.tile { height: 8; width: 100%; background: $surface; border: round $panel; content-align: left top;
        padding: 1 2; text-align: left; }
.tile:hover { border: round $primary; background: $panel; }
.tile:focus { border: round $secondary; }
#home-checks { margin: 1 0 0 0; color: $text-muted; }

/* Forms */
.row { height: auto; margin: 1 0 0 0; }
.row > * { margin: 0 1 0 0; }
Input { width: 1fr; }
Select { width: 30; }
.go { min-width: 16; }
#dl-rows { height: 1fr; margin: 1 0 0 0; }
.dlrow { height: 1; margin: 0 0 1 0; }
.dlrow .icon { width: 2; }
.dlrow .name { width: 1fr; min-width: 16; }
.dlrow ProgressBar { width: 28; }
.dlrow .detail { width: 36; color: $text-muted; }
.dlrow Button { min-width: 8; height: 1; border: none; margin: 0 0 0 1; }
.ok { color: $success; }
.bad { color: $error; }

/* Search */
#results { height: 1fr; margin: 1 0 0 0; }

/* Files */
#file-list { width: 34; height: 1fr; border: round $panel; }
#file-form { width: 1fr; height: 1fr; padding: 0 0 0 2; }
#file-output { height: auto; max-height: 16; margin: 1 0 0 0; border: round $panel; padding: 0 1; }

/* Settings and tool forms: one line per field */
.setting { height: 1; margin: 0 0 1 0; }
.setting Label { width: 40; color: $foreground; }
Switch.-compact, .setting Switch, #file-form Switch { border: none; height: 1; padding: 0; width: 6;
                                                      background: $surface; }
.setting Input { width: 44; }
.setting Select { width: 44; }
#file-form Input, #file-form Select { margin: 0 0 0 0; }
#file-form .field-label { margin: 1 0 0 0; }
#file-head { height: 1; margin: 0 0 1 0; }
#file-head Label { width: 1fr; }
#file-head Button { min-width: 10; }
#file-form .setting Button { width: auto; min-width: 10; margin: 0 0 0 1; }
#file-done { height: 1; margin: 1 0 0 0; }
#file-done Label { width: 1fr; }
#settings-note { margin: 1 0 0 0; }

/* File picker */
FilePicker { align: center middle; }
#picker { width: 80%; height: 80%; background: $surface; border: round $primary; padding: 1 2; }
#picker DirectoryTree { height: 1fr; }
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
            yield Label("Click folders to open them, click a file to add it · Esc to cancel", classes="subtitle")
            yield DirectoryTree(str(self.start))
            with Horizontal(classes="row"):
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

    def compose(self) -> ComposeResult:
        yield Label("·", classes="icon")
        yield Label(self.item.name, classes="name")
        yield ProgressBar(total=100, show_eta=False, show_percentage=True)
        yield Label("waiting", classes="detail")
        yield Button("Show", classes="show", disabled=True)

    def sync(self):
        i = self.item
        icon, name, bar, detail, show = (self.query_one(".icon", Label), self.query_one(".name", Label),
                                         self.query_one(ProgressBar), self.query_one(".detail", Label),
                                         self.query_one(".show", Button))
        name.update(i.name)
        if i.status == "running":
            icon.update(Text("↓", style="bold"))
            if i.stage == "downloading" and i.total:
                bar.update(total=100, progress=min(100.0, i.downloaded / i.total * 100))
                bits = [f"{fmt_size(i.downloaded)} / {fmt_size(i.total)}"]
                if i.speed:
                    bits.append(f"{fmt_size(i.speed)}/s")
                detail.update("  ".join(bits))
            else:
                bar.update(total=None)
                detail.update(i.stage)
        elif i.status == "done":
            icon.update(Text("✓", style="bold #4ade80"))
            bar.update(total=100, progress=100)
            bits = [b for b in (i.quality(), fmt_size(i.path.stat().st_size) if i.path and i.path.exists() else "") if b]
            detail.update(Text("saved · " + " · ".join(bits), style="#4ade80"))
            show.disabled = False
        elif i.status == "failed":
            icon.update(Text("✗", style="bold #f87171"))
            bar.update(total=100, progress=0)
            detail.update(Text(i.error, style="#f87171"))
            show.display = False

    @on(Button.Pressed, ".show")
    def show(self):
        if self.item.path:
            reveal(str(self.item.path))


# ── Panes ──

VIDEO_OPTS = [("MP4 · video", "mp4"), ("MKV · video", "mkv"), ("WebM · video", "webm"),
              ("WAV · audio, lossless", "wav"), ("FLAC · audio, lossless", "flac"), ("MP3 · audio", "mp3"),
              ("M4A · audio", "m4a"), ("Opus · audio", "opus")]


def _quality_opts(fmt: str):
    if fmt == "mp3":
        return [(f"{b} kbps", b) for b in ("320", "256", "192", "128")]
    if fmt in ("wav", "flac", "m4a", "opus"):
        return [("as the source", "source")]
    return [(label.split(" · ")[0].capitalize() if not label[0].isupper() else label, v)
            for v, label in settings.BY_KEY["dl_quality"].choices]


class Home(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("What do you want to do?", classes="title")
        yield Label("Click a tile, or use the buttons on the left. Everything runs on this computer.",
                    classes="subtitle")
        with Grid(id="tiles"):
            yield Button("[b]↓  Download[/b]\n[dim]paste a link from YouTube,\nTikTok, SoundCloud and 1000+ more[/dim]",
                         id="go-download", classes="tile")
            yield Button("[b]⌕  Search[/b]\n[dim]find a video or song by\nname, then download it[/dim]",
                         id="go-search", classes="tile")
            yield Button("[b]▤  Files[/b]\n[dim]PDF, images, audio, video,\ndata conversion[/dim]",
                         id="go-files", classes="tile")
            yield Button("[b]◎  Web app[/b]\n[dim]the same tools in your\nbrowser, drag and drop[/dim]",
                         id="go-web", classes="tile")
            yield Button("[b]≡  Settings[/b]\n[dim]defaults, folder, colours,\nClaude Code[/dim]",
                         id="go-settings", classes="tile")
            yield Button("[b]?  Help[/b]\n[dim]commands, and a hands-on\ntutorial[/dim]",
                         id="go-help", classes="tile")
        yield Static(id="home-checks")


class DownloadPane(Vertical):
    def compose(self) -> ComposeResult:
        d = download_defaults()
        yield Label("Download", classes="title")
        yield Label("Paste one or more links (space between them), pick a format, press Download.",
                    classes="subtitle")
        yield Input(placeholder="https://…   or   ytsearch:song name   (top YouTube result)", id="dl-links")
        with Horizontal(classes="row"):
            yield Select(VIDEO_OPTS, value=d["video"], allow_blank=False, id="dl-format")
            yield Select(_quality_opts(d["video"]), value=d["quality"], allow_blank=False, id="dl-quality")
            yield Switch(value=False, id="dl-playlist")
            yield Label("whole playlist", classes="hint")
        with Horizontal(classes="row"):
            yield Input(value=d["folder"] or str(Path.cwd()), placeholder="folder to save into", id="dl-folder")
            yield Button("Download", variant="primary", id="dl-go", classes="go")
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
        yield Label("Find something by name. Pick a result, then download it as video or audio.",
                    classes="subtitle")
        with Horizontal(classes="row"):
            yield Input(placeholder="what are you looking for?", id="q")
            yield Select([("YouTube", "youtube"), ("SoundCloud", "soundcloud")], value="youtube",
                         allow_blank=False, id="q-source")
            yield Button("Search", variant="primary", id="q-go", classes="go")
        yield DataTable(id="results", cursor_type="row", zebra_stripes=True)
        with Horizontal(classes="row"):
            yield Button("Download video", id="q-video", variant="primary", disabled=True)
            yield Button("Download audio", id="q-audio", disabled=True)
            yield Button("Open the page", id="q-open", disabled=True)
            yield Label("", id="q-status", classes="hint")


class FilesPane(Horizontal):
    def compose(self) -> ComposeResult:
        from sdexe.cli_tools import COMMANDS, GROUPS
        options = []
        for group in GROUPS:
            options.append(Option(Text(group.upper(), style="bold"), disabled=True))
            for c in (c for c in COMMANDS if c.group == group):
                options.append(Option(f"  {c.name or 'convert a file'}", id=c.full))
        yield OptionList(*options, id="file-list")
        with VerticalScroll(id="file-form"):
            yield Label("Pick a tool on the left", classes="title")
            yield Label("Merge PDFs, resize images, trim audio, make GIFs, convert data and more.",
                        classes="subtitle")


class SettingsPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Settings", classes="title")
        yield Label("Changes save as you make them. Scripts can use sdexe settings set KEY VALUE.",
                    classes="subtitle")
        values = settings.all_values()
        section = None
        for s in settings.SETTINGS:
            if s.section != section:
                section = s.section
                yield Label(section, classes="section")
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
        yield Label("Integrations", classes="section")
        if settings.zshrc():
            with Horizontal(classes="setting"):
                yield Label("Paste links without quotes (zsh)")
                yield Switch(value=settings.zsh_alias_on(), id="int-zsh")
        with Horizontal(classes="setting"):
            yield Label("Claude Code can use sdexe (MCP)")
            yield Switch(value=False, id="int-mcp", disabled=True)
        with Horizontal(classes="setting"):
            yield Label("Claude Code skill")
            yield Switch(value=settings.skill_on(), id="int-skill")
        yield Label("", id="settings-note", classes="hint")


class HelpPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Label("Help", classes="title")
        yield Label("Everything here also works as a typed command, which is handy for scripts and AI agents.",
                    classes="subtitle")
        with Horizontal(classes="row"):
            yield Button("Start the tutorial", variant="primary", id="help-tutorial")
            yield Button("Open the web app", id="help-web")
        yield Label("Commands", classes="section")
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
        yield Label("Keys", classes="section")
        yield Static(_themed(ui.rows([("d / s / f", "download · search · files"), (", ", "settings"),
                                      ("o", "open the web app"), ("q", "quit sdexe")], indent=0, commands=False)))


# ── App ──

PANES = ("home", "download", "search", "files", "settings", "help")


class SdexeApp(App):
    TITLE = "sdexe"
    CSS = CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "go('download')", "Download"),
        Binding("s", "go('search')", "Search"),
        Binding("f", "go('files')", "Files"),
        Binding("comma", "go('settings')", "Settings"),
        Binding("o", "open_web", "Open web app"),
        Binding("question_mark", "go('help')", "Help"),
        Binding("escape", "go('home')", "Home", show=False),
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

    # layout
    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static(ui.wordmark(None, None, indent=0), id="brand")
            yield Static(id="status")
            if self.url:
                yield Button("Open in browser", id="open-web", variant="primary")
        with Horizontal(id="body"):
            with Vertical(id="nav"):
                for pane, label in zip(PANES, ("⌂  Home", "↓  Download", "⌕  Search", "▤  Files",
                                                "≡  Settings", "?  Help")):
                    yield Button(label, id=f"nav-{pane}")
                yield Static("")
                yield Button("⏻  Quit", id="nav-quit")
            with ContentSwitcher(id="main", initial="home"):
                yield Home(id="home")
                yield DownloadPane(id="download")
                yield SearchPane(id="search")
                yield FilesPane(id="files")
                yield SettingsPane(id="settings")
                yield HelpPane(id="help")
        yield Footer()

    def on_mount(self):
        from sdexe.cli import quiet_sdexe_logger
        quiet_sdexe_logger()  # error logs would print over the screen
        theme = _theme()
        self.register_theme(theme)
        self.theme = theme.name
        self._mark_nav("home")
        self._status()
        table = self.query_one("#results", DataTable)
        title_w = max(24, self.size.width - 20 - 6 - 22 - 8 - 8 - 12)
        table.add_column("Title", width=title_w)
        table.add_column("Channel", width=22)
        table.add_column("Length", width=8)
        table.add_column("Views", width=8)
        self.set_interval(0.3, self._tick)
        self.set_timer(3.5, self._status)  # the update check finishes after we open
        self._load_checks()
        self._load_mcp_state()

    def _status(self):
        t = Text()
        if self.url:
            t.append("● ", style="#4ade80")
            t.append("web app running at ", style="#8a8f98")
            t.append(self.url, style=f"bold {ui.colors()[0]}")
        else:
            t.append("terminal only", style="#8a8f98")
        t.append(f"\nv{__version__}", style="#5c6068")
        if self.update_info.get("latest"):
            from sdexe.cli_home import _newer
            if _newer(self.update_info["latest"], __version__):
                t.append(f" · {self.update_info['latest']} is out: sdexe update", style="#fbbf24")
        if self.note:
            t.append(f" · {self.note}", style="#fbbf24")
        self.query_one("#status", Static).update(t)

    @work(thread=True)
    def _load_checks(self):
        from sdexe.cli_home import system_checks
        checks = system_checks()
        t = Text()
        for ok, name, detail, fix in checks:
            t.append("✓ " if ok else "! ", style="#4ade80" if ok else "#fbbf24")
            t.append(f"{name} ", style="bold")
            t.append(detail, style="#8a8f98")
            if fix:
                t.append(f"  → {fix}", style=ui.colors()[0])
            t.append("\n")
        self.call_from_thread(self.query_one("#home-checks", Static).update, t)

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
        focus = {"download": "#dl-links", "search": "#q", "files": "#file-list"}.get(pane)
        if focus:
            self.query_one(focus).focus()

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
                self.exit()
            else:
                self.action_go(bid[4:])
        elif bid.startswith("go-"):
            if bid == "go-web":
                self.action_open_web()
            else:
                self.action_go(bid[3:])
        elif bid in ("open-web", "help-web"):
            self.action_open_web()
        elif bid == "help-tutorial":
            with self.suspend():
                subprocess.call([sys.executable, "-m", "sdexe", "tutorial"])
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
        elif bid == "file-show" and getattr(self, "last_outputs", None):
            reveal(self.last_outputs[0])

    # downloads
    @on(Input.Submitted, "#dl-links")
    def links_submitted(self):
        self.start_download()

    def start_download(self, links: list | None = None, fmt: str | None = None, quality: str | None = None):
        from sdexe import cli
        links_input = self.query_one("#dl-links", Input)
        raw = links if links is not None else shlex.split(links_input.value.strip() or "''")
        urls = [u for u in (cli.normalize_url(t) for t in raw if t) if u]
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
        self.action_go("download")
        self.notify(f"Downloading {len(urls)} {'link' if len(urls) == 1 else 'links'} as {spec.label}.")

    def _tick(self):
        box = self.query_one("#dl-rows", VerticalScroll)
        for dl in self.downloaders:
            with dl.lock:
                items = [i for i in dl.items if i.status != "expanded"]
            for item in items:
                row = self.rows.get(id(item))
                if row is None:
                    row = DownloadRow(item)
                    self.rows[id(item)] = row
                    box.mount(row)
                    continue  # sync once mounted
                was = getattr(row, "_last", None)
                if item.status in ("done", "failed") and was == item.status:
                    continue
                row.sync()
                if item.status != was and item.status in ("done", "failed"):
                    if item.status == "done":
                        self.notify(f"Saved {item.path.name}", title="Download finished")
                    else:
                        self.notify(item.error, title=f"Couldn't download {item.name[:40]}", severity="error")
                row._last = item.status

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
                table.add_row(r["title"], r["channel"], fmt_time(r["duration"]) if r["duration"] else "",
                              _views(r["views"]), key=str(i))
            for b in ("#q-video", "#q-audio", "#q-open"):
                self.query_one(b, Button).disabled = not results
            self.query_one("#q-status", Label).update(error or f"{len(results)} results · click one, then download")
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
        form = self.query_one("#file-form", VerticalScroll)
        await form.remove_children()
        widgets = [Horizontal(Label(f"sdexe {cmd.full}", classes="title"),
                              Button("Run", variant="primary", id="file-run", compact=True), id="file-head"),
                   Label(cmd.summary[:1].upper() + cmd.summary[1:] + ".", classes="subtitle")]
        if cmd.inputs == "none":
            widgets += [Label(cmd.text_arg.capitalize(), classes="field-label"),
                        Input(placeholder="type here", id="file-text", compact=True)]
        else:
            what = {"many": "files, in order", "pair": cmd.inputs_help.lower(), "each": "one or more files"}[cmd.inputs]
            widgets += [Label(f"Files · {what} · drag them into this window, or Browse", classes="field-label"),
                        Horizontal(Input(placeholder="drop files here", id="file-files", compact=True),
                                   Button("Browse…", id="file-browse", compact=True),
                                   Button("Clear", id="file-clear", compact=True),
                                   classes="setting")]
        for arg in cmd.args:
            label = arg.flag.lstrip("-").replace("-", " ").capitalize() + (" *" if arg.required else "")
            widgets.append(Label(label + (f" · {arg.help}" if arg.help else ""), classes="field-label"))
            if arg.type is bool:
                widgets.append(Switch(value=False, id=f"arg-{arg.dest}"))
            elif arg.choices:
                widgets.append(Select([(str(c), str(c)) for c in arg.choices],
                                      value=str(arg.default) if arg.default is not None else Select.BLANK,
                                      allow_blank=arg.default is None, id=f"arg-{arg.dest}", compact=True))
            else:
                widgets.append(Input(value="" if arg.default in (None, "") else str(arg.default),
                                     placeholder="required" if arg.required else "optional",
                                     id=f"arg-{arg.dest}", compact=True))
        text_out = cmd.name in ("text", "ocr", "ascii")
        widgets += [Label("Save to · a folder" + (" (leave empty to show the text here)" if text_out else ""),
                          classes="field-label"),
                    Input(value="" if text_out else str(Path.cwd()), id="file-out", compact=True),
                    Horizontal(Label("", id="file-status", classes="hint"),
                               Button("Show in Finder" if sys.platform == "darwin" else "Show file",
                                      id="file-show", compact=True, disabled=True), id="file-done"),
                    Static("", id="file-output")]
        await form.mount(*widgets)

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
                        self.notify(f"{arg.flag.lstrip('-')} is required.", severity="warning")
                        return
                    continue
                argv += [arg.flag, str(v)]
        out = self.query_one("#file-out", Input).value.strip()
        if out:
            argv += ["-o", str(Path(out).expanduser()) + ("/" if cmd.name not in ("text", "ocr", "ascii") else "")]
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
            doc = {"ok": False, "results": [{"ok": False, "error": (r.stderr or r.stdout).strip().splitlines()[-1]
                                             if (r.stderr or r.stdout).strip() else "failed"}]}

        def show():
            out = Text()
            self.last_outputs = []
            for res in doc.get("results", []):
                if not res.get("ok"):
                    out.append("✗ ", style="#f87171")
                    out.append(res.get("error", "failed") + "\n", style="#f87171")
                    continue
                for o in res.get("outputs") or []:
                    self.last_outputs.append(o["path"])
                    out.append("✓ ", style="#4ade80")
                    out.append(_short(o["path"]))
                    out.append(f"  {fmt_size(o['size_bytes'])}\n", style="#8a8f98")
                if res.get("text"):
                    out.append(res["text"][:20000])
                if res.get("data"):
                    for k, v in res["data"].items():
                        out.append(f"{k}: ", style="#8a8f98")
                        out.append(f"{v}\n")
            self.query_one("#file-output", Static).update(out)
            self.query_one("#file-run", Button).disabled = False
            ok = doc.get("ok")
            self.query_one("#file-status", Label).update("done" if ok else "something failed")
            self.query_one("#file-show", Button).disabled = not self.last_outputs
            if ok and self.last_outputs:
                self.notify(f"Saved {len(self.last_outputs)} file(s).", title="Done")
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
        self.query_one("#settings-note", Label).update(f"✓ {s.label}: {s.show(new)}")
        if key == "accent":
            theme = _theme()
            self.register_theme(theme)
            self.theme = theme.name
            self.query_one("#brand", Static).update(ui.wordmark(None, None, indent=0))
            self._status()

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
        active = [i for dl in self.downloaders for i in dl.items if i.status in ("queued", "running")]
        if active:
            for dl in self.downloaders:
                dl.cancel.set()
        self.exit()


def run(url: str | None = None, note: str = "", update: dict | None = None):
    SdexeApp(url=url, note=note, update=update).run()
