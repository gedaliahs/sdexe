#!/usr/bin/env python3
"""Headless test of the clickable terminal app (sdexe/tui.py).

Drives the real app with Textual's pilot: clicks every sidebar button and home
tile, presses the shortcuts, runs a file tool from its form, and flips a
setting. Then the regressions: downloads (with a stand-in downloader), search,
tool results, odd paths, small windows, resizing and quitting.

No network and nothing outside the test folder: search, the clipboard, the
downloader, the browser, Finder and Claude Code are all replaced below. Runs
with a throwaway HOME, so the real config is never touched.

Usage:
    python tests/tui_test.py
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="sdexe-tui-test-"))
os.environ["HOME"] = str(WORK / "home")
os.environ["ZDOTDIR"] = os.environ["HOME"]
(WORK / "home").mkdir()
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from textual import events  # noqa: E402
from textual.widgets import (Button, ContentSwitcher, DataTable, Input, Label, OptionList, ProgressBar,  # noqa: E402
                             Static, Switch)

from sdexe import cli, cli_search, settings, tui, ui  # noqa: E402
from sdexe.tui import PANES, DownloadRow, SdexeApp  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


# ── Stand-ins: nothing here may reach the network, the browser or the real clipboard ──

OPENED, CLIPBOARD = [], []
SEARCH = {"fn": lambda q, n, source: []}
REAL_REVEAL = tui.reveal
webbrowser.open = lambda url, *a, **k: OPENED.append(url) or True
tui.reveal = lambda path: True
cli.clipboard_links = lambda: list(CLIPBOARD)
cli_search.search = lambda q, n=10, source="youtube": SEARCH["fn"](q, n, source)
settings.claude_mcp_on = lambda: None
settings.set_claude_mcp = lambda on: "stand-in"


class FakeDownloader:
    """cli.Downloader's surface as the app uses it. The test moves the items along."""
    made = []

    def __init__(self, urls, spec, args, out_dir, defaults=None, silent=False, **_):
        self.urls, self.spec, self.args, self.out_dir = list(urls), spec, args, out_dir
        self.items = [cli.Item(u) for u in urls]
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.tmp_dirs = set()
        FakeDownloader.made.append(self)

    def start(self):
        pass

    def add(self, urls):
        with self.lock:
            self.items += [cli.Item(u) for u in urls]


REAL_DOWNLOADER = cli.Downloader
cli.Downloader = FakeDownloader


class FakeTool:
    """subprocess.Popen for the tool forms: prints what the test says, after a delay."""
    out, err, delay, fail = "", "", 0.0, None

    def __init__(self, cmd, **kwargs):
        if FakeTool.fail:
            raise FakeTool.fail
        self.done = False

    def communicate(self):
        time.sleep(FakeTool.delay)
        self.done = True
        return FakeTool.out, FakeTool.err

    def poll(self):
        return 0 if self.done else None

    def send_signal(self, sig):
        pass

    terminate = kill = lambda self: None


def result(n, tag="r"):
    return [{"title": f"{tag} {i} [Official Video]", "url": f"https://x.test/{tag}{i}", "channel": "Some Channel",
             "duration": 200 + i, "views": 1234 * i, "id": str(i)} for i in range(n)]


def toasts(app):
    return [n.message for n in app._notifications]


async def open_tool(app, pilot, name):
    app.action_go("files")
    tools = app.query_one("#file-list", OptionList)
    tools.highlighted = next(i for i, o in enumerate(tools._options) if o.id == name)
    tools.focus()
    await pilot.press("enter")
    await pilot.pause(0.3)


async def run():
    os.chdir(WORK)
    Image.new("RGB", (400, 300), "#3366cc").save("pic.png")
    app = SdexeApp(url="http://127.0.0.1:5999")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.8)
        main = app.query_one("#main", ContentSwitcher)

        for pane in PANES:
            await pilot.click(f"#nav-{pane}")
            await pilot.pause(0.3)
            check(f"sidebar: {pane}", main.current == pane, main.current)

        for group in ("pdf", "image", "audio", "video", "convert", "file"):
            await pilot.click("#nav-home")
            await pilot.pause(0.2)
            await pilot.click(f"#tool-{group}")
            await pilot.pause(0.3)
            highlighted = app.query_one("#file-list", OptionList).highlighted_option
            check(f"home tool button: {group}", main.current == "files" and highlighted is not None
                  and highlighted.id.split(" ")[0] == group, main.current)

        # The home box: words go to search.
        SEARCH["fn"] = lambda q, n, source: result(3)
        await pilot.click("#nav-home")
        await pilot.pause(0.2)
        app.query_one("#home-box", Input).value = "some song name"
        await pilot.click("#home-go")
        await pilot.pause(0.5)
        check("home box sends words to search", main.current == "search"
              and app.query_one("#q", Input).value == "some song name", main.current)
        check("search fills the table", app.query_one("#results", DataTable).row_count == 3)

        seen = []
        for key, pane in (("escape", "home"), ("d", "download"), ("escape", "home"), ("s", "search"),
                          ("escape", "home"), ("f", "files"), ("escape", "home"), ("comma", "settings"),
                          ("escape", "home"), ("question_mark", "help")):
            await pilot.press(key)
            await pilot.pause(0.2)
            seen.append(main.current == pane)
        check("keyboard shortcuts", all(seen), str(seen))
        await pilot.press("escape", "o")
        await pilot.pause(0.2)
        check("o opens the web app", OPENED[-1:] == ["http://127.0.0.1:5999"], str(OPENED))

        # A file tool, filled in and run from its form.
        await pilot.click("#nav-files")
        await pilot.pause(0.3)
        tools = app.query_one("#file-list", OptionList)
        tools.highlighted = next(i for i, o in enumerate(tools._options) if o.id == "image resize")
        tools.focus()
        await pilot.press("enter")
        await pilot.pause(0.5)
        app.query_one("#file-files", Input).value = "pic.png"
        app.query_one("#arg-width", Input).value = "100"
        await pilot.click("#file-run")
        for _ in range(60):
            await pilot.pause(0.25)
            if (WORK / "pic-resized.png").exists():
                break
        await pilot.pause(0.3)
        out = WORK / "pic-resized.png"
        width = 0
        if out.exists():
            with Image.open(out) as im:
                width = im.width
        check("run a tool from its form", width == 100, str(width))

        # A file name with spaces, typed as it is (no quotes).
        Image.new("RGB", (40, 30)).save("my pic (1).png")
        app.query_one("#file-files", Input).value = "my pic (1).png"
        app.query_one("#arg-width", Input).value = "20"
        await pilot.click("#file-run")
        for _ in range(60):
            await pilot.pause(0.25)
            if (WORK / "my pic (1)-resized.png").exists():
                break
        check("a bare file name with spaces runs", (WORK / "my pic (1)-resized.png").exists(),
              str(app.query_one("#file-output", Static).render()))

        # Every tool's form opens without crashing (a dropdown with no default
        # once killed the app).
        tools = app.query_one("#file-list", OptionList)
        opened, broken = 0, []
        for i, opt in enumerate(list(tools._options)):
            if opt.disabled:
                continue
            tools.highlighted = i
            tools.focus()
            await pilot.press("enter")
            await pilot.pause(0.05)
            if not app.is_running:
                broken.append(opt.id)
                break
            opened += 1
        check(f"every tool form opens ({opened})", not broken and opened > 60, str(broken))

        # A setting, saved the moment it changes.
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        await pilot.click("#set-open_browser")
        await pilot.pause(0.3)
        cfg = json.loads((WORK / "home/.config/sdexe/config.json").read_text())
        check("settings switch saves", cfg.get("open_browser") is False, str(cfg))
        check("opening the app doesn't rewrite settings", set(cfg) == {"open_browser"}, str(cfg))

        await pilot.click("#nav-quit")
        await pilot.pause(0.3)
    check("quit button", app.return_code == 0, str(app.return_code))


class RacyItem:
    """A download whose status changes between two reads inside one screen
    update, as the download thread can do at any moment."""

    def __init__(self, url, path):
        self.url = self.title = self.name = url
        self.stage, self.streams, self.expected, self.speed = "fetching info", {}, 0, None
        self.path, self.error, self.info, self.reads, self.armed = path, "", {}, 0, False

    def quality(self):
        return ""

    @property
    def status(self):
        if not self.armed:
            return "running"
        self.reads += 1
        return "running" if self.reads <= 3 else "done"


def dl_row(app, item):
    return next((r for r in app.query_one("#dl-rows").query(DownloadRow) if r.item is item), None)


async def run_downloads():
    """Download rows, with a stand-in downloader the test moves along."""
    FakeDownloader.made.clear()
    app = SdexeApp(url="http://127.0.0.1:5999")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.5)
        main = app.query_one("#main", ContentSwitcher)
        home = app.query_one("#home-box", Input)

        # Seven links at once. Home lists the newest five; a sixth used to close the app.
        home.value = " ".join(f"https://x.test/{i}" for i in range(7))
        await pilot.press("enter")
        await pilot.pause(1.0)
        check("more than five downloads in a session", app.is_running
              and len(app.query_one("#home-recent").children) == 5 and len(app.query_one("#dl-rows").children) == 7,
              f"{len(app.query_one('#home-recent').children)} on home")
        if not app.is_running:
            return
        dl = FakeDownloader.made[-1]
        a, b, c = dl.items[:3]

        a.status, a.stage, a.title = "running", "downloading", "Song [Official Video] [/x] 日本語 🎵"
        a.streams["v"] = (50, 100)
        app.action_go("download")
        await pilot.pause(0.7)
        row = dl_row(app, a)
        bar = row.query_one(ProgressBar)
        inner = bar.query_one("Bar")
        check("the progress bar fits its box", 0 < inner.region.width <= bar.region.width,
              f"{inner.region.width} in {bar.region.width}")  # a wider bar read 100% at 75%
        check("a title with [brackets] is shown as it is", app.is_running
              and "[Official Video] [/x]" in str(row.query_one(".name", Label).render()))

        # A playlist (or search) link is replaced by its videos; its own row goes away.
        child = cli.Item("https://x.test/child", title="A video in it", playlist="A playlist")
        with dl.lock:
            dl.items.insert(2, child)
        b.status, b.title = "expanded", "A playlist"
        await pilot.pause(0.7)
        check("a playlist link's own row goes away", dl_row(app, b) is None and dl_row(app, child) is not None
              and len(app.query_one("#dl-rows").children) == 7)

        clip = WORK / "clip [1].mp4"
        clip.write_bytes(b"x" * 2048)
        a.path, a.status = clip, "done"
        c.status, c.error = "failed", "This link is a playlist (3 videos). Add --playlist to download all of them."
        await pilot.pause(0.7)
        check("a finished download can be shown", not row.query_one(".show", Button).disabled
              and "2.0 KB" in str(row.query_one(".detail", Label).render()))
        failed = str(dl_row(app, c).query_one(".detail", Label).render())
        check("playlist advice names the switch, not a flag", "Whole playlist" in failed and "--playlist" not in failed, failed)
        check("download toasts", any(t == "Saved clip [1].mp4" for t in toasts(app))
              and any("Whole playlist" in t for t in toasts(app)), str(toasts(app)))
        check("session count", str(app.query_one("#dl-heading", Label).render()) == "THIS SESSION · 1 of 7 saved",
              str(app.query_one("#dl-heading", Label).render()))

        # Status flipping to done in the middle of a screen update: the row must still end up done.
        racy = RacyItem("https://x.test/racy", clip)
        with dl.lock:
            dl.items.append(racy)
        await pilot.pause(0.8)
        racy.armed = True
        await pilot.pause(2.0)
        check("a download finishing mid-update is drawn as finished",
              dl_row(app, racy) is not None and not dl_row(app, racy).query_one(".show", Button).disabled)

        # Enter twice: the second finds an empty box and the same link on the clipboard.
        CLIPBOARD[:] = ["https://x.test/once"]
        app.action_go("home")
        home.value = "https://x.test/once"
        await pilot.press("enter", "enter")
        await pilot.pause(0.4)
        once = sum(i.url == "https://x.test/once" for d in FakeDownloader.made for i in d.items)
        check("Enter twice starts one download", once == 1, str(once))
        CLIPBOARD.clear()

        # A list of links, one per line: every line, not just the first.
        home.focus()
        await pilot.pause(0.1)
        home.post_message(events.Paste("https://x.test/p1\nhttps://x.test/p2\n\nhttps://x.test/p3\n"))
        await pilot.pause(0.2)
        check("a pasted list of links keeps every line",
              home.value == "https://x.test/p1 https://x.test/p2 https://x.test/p3", home.value)
        home.value = ""

        app.action_go("download")
        links, folder = app.query_one("#dl-links", Input), app.query_one("#dl-folder", Input)
        links.value = "hello world"
        await pilot.press("enter")
        await pilot.pause(0.2)
        check("words in the links box", any("isn't a link" in t for t in toasts(app)), str(toasts(app)[-1:]))
        keep, folder.value, links.value = folder.value, "~nosuchuser-sdexe/x", "https://x.test/f"
        links.focus()
        await pilot.press("enter")
        await pilot.pause(0.3)
        check("a folder under an unknown ~user doesn't close the app", app.is_running)
        if not app.is_running:
            return
        folder.value = keep

        # Show in Finder, when there's no way to: a message, and the app stays up.
        tui.reveal = lambda path: False
        app.show_file(str(clip))
        await pilot.pause(0.2)
        tui.reveal = lambda path: True
        check("a file that can't be revealed", app.is_running and any(str(clip) in t for t in toasts(app)))
        real_popen = subprocess.Popen

        def no_opener(*args, **kwargs):
            raise FileNotFoundError("xdg-open")
        subprocess.Popen = no_opener
        try:
            check("reveal without a file manager", REAL_REVEAL(str(clip)) is False
                  and REAL_REVEAL(str(WORK / "gone.mp4")) is False)
        finally:
            subprocess.Popen = real_popen

        # The folder setting reaches the Download page, which Home and Search save into.
        app.action_go("settings")
        await pilot.pause(0.2)
        box = app.query_one("#set-dl_folder", Input)
        box.focus()
        box.value = str(WORK / "music")
        await pilot.press("enter")
        await pilot.pause(0.3)
        check("the folder setting reaches the Download page", folder.value == settings.get("dl_folder") != "",
              folder.value)
        box.value = "~nosuchuser-sdexe/x"
        await pilot.press("enter")
        await pilot.pause(0.3)
        check("an unknown ~user in the folder setting", app.is_running)
        if not app.is_running:
            return
        box.value = ""
        await pilot.press("enter")
        await pilot.pause(0.3)

        # An integration that fails: the switch shows what is true, not what was clicked.
        def fails(on):
            raise RuntimeError("no [/x] luck")
        real_skill, settings.set_skill = settings.set_skill, fails
        sw = app.query_one("#int-skill", Switch)
        sw.focus()
        await pilot.press("enter")
        await pilot.pause(0.8)
        settings.set_skill = real_skill
        check("a failed integration switch goes back", app.is_running and sw.value is False and not sw.disabled)

        check("an accent that isn't a name", ui.set_accent(["x"]) is None and ui.accent_name() == ui.DEFAULT_ACCENT)

        # The real downloader, with the network step replaced: once its links are
        # done its threads end, instead of three more waiting forever per download.
        def instant(self, item):
            item.path = self.out_dir / f"{item.url.rsplit('/', 1)[-1]}.mp4"
            item.path.write_bytes(b"x" * 10)
        real_attempt, REAL_DOWNLOADER._attempt = REAL_DOWNLOADER._attempt, instant
        cli.Downloader = REAL_DOWNLOADER
        try:
            threads = threading.active_count()
            app.action_go("home")
            for n in range(4):
                home.value = f"https://x.test/real{n}"
                await pilot.press("enter")
                await pilot.pause(0.2)
            await pilot.pause(1.2)
            saved = [(WORK / f"real{n}.mp4").exists() for n in range(4)]
            check("finished downloads leave no threads behind", all(saved) and threading.active_count() <= threads,
                  f"{saved} {threading.active_count() - threads} extra threads")
        finally:
            cli.Downloader, REAL_DOWNLOADER._attempt = FakeDownloader, real_attempt


async def run_search_and_tools():
    app = SdexeApp(url="http://127.0.0.1:5999")
    real_popen = subprocess.Popen
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.5)
        main = app.query_one("#main", ContentSwitcher)

        def slow_then_fast(q, n, source):
            time.sleep(1.2 if q == "slow" else 0.05)
            return result(2, q)
        SEARCH["fn"] = slow_then_fast
        app.action_go("search")
        q = app.query_one("#q", Input)
        q.value = "slow"
        app.run_search()
        await pilot.pause(0.1)
        q.value = "fast"
        app.run_search()
        await pilot.pause(1.8)
        check("an earlier, slower search doesn't replace a newer one",
              bool(app.search_results) and app.search_results[0]["title"].startswith("fast"),
              str(app.search_results[:1]))

        def boom(q, n, source):
            raise RuntimeError("ERROR: [youtube] abc: boom [/red] [bold")
        SEARCH["fn"] = boom
        q.value = "x"
        app.run_search()
        await pilot.pause(0.5)
        check("a search error with [brackets]", app.is_running and any("[/red]" in t for t in toasts(app)),
              str(toasts(app)[-1:]))
        if not app.is_running:
            return

        # Keyboard only: Enter on a result, Enter again downloads it.
        SEARCH["fn"] = lambda q, n, source: result(3)
        q.value = "y"
        app.run_search()
        await pilot.pause(0.5)
        await pilot.press("down", "enter", "enter")
        await pilot.pause(0.4)
        got = [i.url for d in FakeDownloader.made for i in d.items]
        check("a result downloads from the keyboard", main.current == "download" and "https://x.test/r1" in got, str(got[-2:]))

        try:
            subprocess.Popen = FakeTool
            bad = []
            for out, err in (("[1, 2]", ""), ("", ""), ("warning: [/x] not json", ""),
                             ("", "sdexe image info: Not found: pic.png"), ('{"ok": true, "results": [3]}', "")):
                FakeTool.out, FakeTool.err, FakeTool.delay = out, err, 0.0
                await open_tool(app, pilot, "image info")
                app.query_one("#file-files", Input).value = "pic.png"
                await pilot.click("#file-run")
                await pilot.pause(0.4)
                if not app.is_running:
                    bad.append(out or err)
                    break
                if app.query_one("#file-run", Button).disabled \
                        or str(app.query_one("#file-status", Label).render()) != "Something failed.":
                    bad.append(out or err)
            check("tool output that isn't a result document", not bad, str(bad))
            if not app.is_running:
                return
            FakeTool.fail = OSError("cannot start")
            await pilot.click("#file-run")
            await pilot.pause(0.4)
            FakeTool.fail = None
            check("a tool that can't start", app.is_running
                  and "cannot start" in str(app.query_one("#file-output", Static).render()))
            if not app.is_running:
                return

            # A result that arrives after another tool's form was opened.
            FakeTool.out = json.dumps({"ok": True, "command": "image info", "results": [
                {"ok": True, "inputs": ["/x/pic.png"], "data": {"width": 40}}]})
            FakeTool.err, FakeTool.delay = "", 1.0
            await pilot.click("#file-run")
            await pilot.pause(0.2)
            await open_tool(app, pilot, "pdf merge")
            waits = app.query_one("#file-run", Button).disabled
            await pilot.pause(1.5)
            check("a result isn't drawn into another tool's form", waits
                  and str(app.query_one("#file-output", Static).render()) == ""
                  and not app.query_one("#file-run", Button).disabled, f"run waited: {waits}")

            await open_tool(app, pilot, "image info")
            FakeTool.delay = 0.0
            app.query_one("#file-files", Input).value = "~nosuchuser-sdexe/x.png"
            await pilot.click("#file-run")
            await pilot.pause(0.4)
            check("a file under an unknown ~user doesn't close the app", app.is_running)
            if not app.is_running:
                return
        finally:
            subprocess.Popen = real_popen

        # File names as people and terminals write them.
        check("file names: escaped, quoted, with spaces",
              tui._split_paths(r"My\ File\ \(1\).pdf other.pdf", windows=False) == ["My File (1).pdf", "other.pdf"]
              and tui._split_paths("'a b.pdf' \"c d.pdf\"", windows=False) == ["a b.pdf", "c d.pdf"]
              and tui._split_paths("my pic (1).png") == ["my pic (1).png"]
              and len(tui._split_paths(" ".join(f"picture-number-{n}.png" for n in range(20)))) == 20
              and tui._split_paths(r'C:\Users\me\a.pdf "C:\My Files\b.pdf"', windows=True)
              == [r"C:\Users\me\a.pdf", r"C:\My Files\b.pdf"])
        await open_tool(app, pilot, "image resize")
        box = app.query_one("#file-files", Input)
        check("form fields keep their text when tabbed into",
              not any(i.select_on_focus for i in app.query("#file-form Input")))
        box.focus()
        await pilot.pause(0.1)
        box.post_message(events.Paste("my pic (1).png\npic.png\n"))
        await pilot.pause(0.2)
        check("several dropped files, one per line", tui._split_paths(box.value) == ["my pic (1).png", "pic.png"], box.value)

        await open_tool(app, pilot, "image qr")
        before = len(toasts(app))
        await pilot.click("#file-run")
        await pilot.pause(0.3)
        check("a text tool with no text isn't run", not app._tool_busy and "Type the text first." in toasts(app)[before:],
              str(toasts(app)[before:]))


async def run_small():
    """An 80-column terminal, a tiny one, and resizing."""
    for width, height in ((80, 24), (40, 15)):
        SEARCH["fn"] = lambda q, n, source: result(3)
        app = SdexeApp(url="http://127.0.0.1:5999")
        async with app.run_test(size=(width, height)) as pilot:
            await pilot.pause(0.5)
            app.action_go("download")
            app.query_one("#dl-links", Input).value = "https://x.test/small"
            await pilot.press("enter")
            await pilot.pause(0.8)
            item = FakeDownloader.made[-1].items[-1]
            item.status, item.stage, item.title = "running", "downloading", "A fairly ordinary song title (Official Video)"
            item.streams["v"] = (50_000_000, 100_000_000)
            await pilot.pause(0.7)
            if (width, height) == (80, 24):
                row = dl_row(app, item)
                show = row.query_one(".show", Button).region
                check("80x24: the download list is on screen", 3 <= row.region.y < height - 1 and row.region.height == 1,
                      str(row.region))
                check("80x24: a download row fits", show.width > 0 and show.right <= width
                      and row.query_one(".name", Label).region.width >= 16, str(show))
                app.action_go("home")
                await pilot.pause(0.3)
                hint = app.query_one("#home-hint", Label).region
                check("80x24: the home hint wraps instead of being cut off", hint.height >= 2 and hint.right <= width, str(hint))
                app.query_one("#home").scroll_end(animate=False)
                await pilot.pause(0.3)
                last = app.query_one("#tool-file", Button).region
                check("80x24: every tool button fits", last.width > 0 and last.right <= width, str(last))
                app.action_go("search")
                app.query_one("#q", Input).value = "abc"
                app.run_search()
                await pilot.pause(0.5)
                status = app.query_one("#q-status", Label).region
                check("80x24: the search status is on screen", status.width >= len("3 results") and status.right <= width,
                      str(status))
                await open_tool(app, pilot, "image resize")
                box = app.query_one("#file-files", Input).region
                check("80x24: the files box is wide enough to use", box.width >= 12, str(box))
                app.action_go("settings")
                await pilot.pause(0.3)
                over = [w.id for w in app.query(".setting Switch, .setting Select, .setting Input")
                        if w.region.right > width or w.region.width == 0]
                check("80x24: every setting's control fits", not over, str(over))
            for pane in PANES:
                app.action_go(pane)
                await pilot.pause(0.15)
            check(f"{width}x{height}: every pane opens", app.is_running)

    app = SdexeApp(url="http://127.0.0.1:5999")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause(0.5)
        app.action_go("search")
        app.query_one("#q", Input).value = "abc"
        app.run_search()
        await pilot.pause(0.5)
        table = app.query_one("#results", DataTable)
        await pilot.press("down", "down")

        def title_width():
            return next(iter(table.columns.values())).width
        wide = title_width()
        await pilot.resize_terminal(80, 24)
        await pilot.pause(0.4)
        narrow = title_width()
        for size in ((30, 8), (200, 60), (120, 36)):
            await pilot.resize_terminal(*size)
            await pilot.pause(0.3)
        check("resizing refits the results table", app.is_running and narrow < wide == title_width()
              and table.row_count == 3 and table.cursor_row == 2, f"{wide} {narrow} {title_width()} {table.cursor_row}")


async def run_quit():
    """Closing the app stops what it started instead of waiting for it."""
    real_popen, children = subprocess.Popen, []

    def sleeper(cmd, **kwargs):
        children.append(real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs))
        return children[-1]

    def slow_search(q, n, source):
        time.sleep(8)
        return []
    SEARCH["fn"] = slow_search
    partial = Path(tempfile.mkdtemp(prefix="sdexe-dl-", dir=WORK))
    (partial / "video.mp4.part").write_bytes(b"x" * 100)
    app = SdexeApp(url="http://127.0.0.1:5999")
    try:
        subprocess.Popen = sleeper
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.5)
            await open_tool(app, pilot, "image info")
            app.query_one("#file-files", Input).value = "pic.png"
            await pilot.click("#file-run")
            await pilot.pause(0.6)
            app.action_go("search")
            app.query_one("#q", Input).value = "x"
            app.run_search()
            app.action_go("home")
            app.query_one("#home-box", Input).value = "https://x.test/quit"
            await pilot.press("enter")
            await pilot.pause(0.3)
            dl = FakeDownloader.made[-1]
            dl.tmp_dirs.add(partial)
            await pilot.press("ctrl+q")
            await pilot.pause(0.2)
    finally:
        subprocess.Popen = real_popen
    started = time.monotonic()
    app.stop_work()
    took = time.monotonic() - started
    check("ctrl+q", app.return_code == 0, str(app.return_code))
    check("quitting stops a running tool", bool(children) and children[0].poll() is not None and took < 4,
          f"{took:.1f}s")
    check("quitting cancels downloads and removes partial files", dl.cancel.is_set() and not partial.exists())
    for child in children:
        if child.poll() is None:
            child.kill()


def main() -> int:
    try:
        os.chdir(WORK)
        asyncio.run(run())
        asyncio.run(run_downloads())
        asyncio.run(run_search_and_tools())
        asyncio.run(run_small())
        started = time.monotonic()
        asyncio.run(run_quit())
        # An 8-second search was still running: closing must not wait for it.
        check("quitting doesn't wait for a search", time.monotonic() - started < 7,
              f"{time.monotonic() - started:.1f}s")
    finally:
        os.chdir(ROOT)
        shutil.rmtree(WORK, ignore_errors=True)
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    passed = sum(ok for _, ok, _ in results)
    print(f"\n  {len(results)} checks:  {passed} PASS   {len(results) - passed} FAIL")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
