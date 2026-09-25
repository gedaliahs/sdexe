#!/usr/bin/env python3
"""Headless test of the clickable terminal app (sdexe/tui.py).

Drives the real app with Textual's pilot: clicks every sidebar button and home
tile, presses the shortcuts, runs a file tool from its form, and flips a
setting. No network. Runs with a throwaway HOME, so the real config is never
touched.

Usage:
    python tests/tui_test.py
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(tempfile.mkdtemp(prefix="sdexe-tui-test-"))
os.environ["HOME"] = str(WORK / "home")
os.environ["ZDOTDIR"] = os.environ["HOME"]
(WORK / "home").mkdir()
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from textual.widgets import ContentSwitcher, Input, OptionList  # noqa: E402

from sdexe.tui import PANES, SdexeApp  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


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
        await pilot.click("#nav-home")
        await pilot.pause(0.2)
        app.query_one("#home-box", Input).value = "some song name"
        await pilot.click("#home-go")
        await pilot.pause(0.3)
        check("home box sends words to search", main.current == "search"
              and app.query_one("#q", Input).value == "some song name", main.current)

        for key, pane in (("escape", "home"), ("d", "download"), ("escape", "home"), ("s", "search"),
                          ("escape", "home"), ("f", "files"), ("escape", "home"), ("comma", "settings")):
            await pilot.press(key)
            await pilot.pause(0.2)
        check("keyboard shortcuts", main.current == "settings", main.current)

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
        check("run a tool from its form", out.exists() and Image.open(out).width == 100)

        # A setting, saved the moment it changes.
        await pilot.click("#nav-settings")
        await pilot.pause(0.3)
        await pilot.click("#set-open_browser")
        await pilot.pause(0.3)
        cfg = json.loads((WORK / "home/.config/sdexe/config.json").read_text())
        check("settings switch saves", cfg.get("open_browser") is False, str(cfg))

        await pilot.click("#nav-quit")
        await pilot.pause(0.3)
    check("quit button", app.return_code == 0, str(app.return_code))


def main() -> int:
    try:
        asyncio.run(run())
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
