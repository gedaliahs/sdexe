"""`sdexe search`: find videos and songs by name, no link needed.

Uses yt-dlp's own search (YouTube or SoundCloud), so there is no account or API
key. Results come back as links for `sdexe download`, and
`sdexe download "ytsearch:<words>"` downloads the top hit in one step.
"""

import json
import sys

import yt_dlp

from sdexe import media, ui
from sdexe.cli import UsageError, fmt_time, _escape

SOURCES = {"youtube": "ytsearch", "soundcloud": "scsearch"}

HELP = """\
  [title]sdexe search[/title] [muted]· find videos and songs by name · no link, account or key needed[/muted]

  [brand]sdexe search[/brand] [brand2]"<words>" \\\\[options][/brand2]

  [brand]◆[/brand] [title]Options[/title]
    [brand2]-n, --limit N[/brand2]              how many results (default 10, up to 50)
    [brand2]-s, --source NAME[/brand2]          youtube (default) or soundcloud
    [brand2]--json[/brand2]                     one JSON document on stdout

  [brand]◆[/brand] [title]Then[/title]
    [brand]sdexe download[/brand] [brand2]"<link from the results>"[/brand2]
    [brand]sdexe download[/brand] [brand2]"ytsearch:<words>" -mp3[/brand2]      [muted]top YouTube hit, in one step[/muted]
    [brand]sdexe download[/brand] [brand2]"scsearch:<words>"[/brand2]           [muted]top SoundCloud hit[/muted]
"""


def search(query: str, limit: int = 10, source: str = "youtube") -> list:
    """[{title, url, channel, duration, views, id}] for the top results."""
    prefix = SOURCES[source]
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "noprogress": True,
            "js_runtimes": media.js_runtimes(), "logger": _Quiet()}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"{prefix}{limit}:{query}", download=False)
    results = []
    for e in info.get("entries") or []:
        if not e:
            continue
        url = e.get("webpage_url") or e.get("url") or ""  # the page people know, not the API link
        if url and not url.startswith("http") and source == "youtube":
            url = f"https://www.youtube.com/watch?v={url}"
        results.append({
            "title": e.get("title") or "",
            "url": url,
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration"),
            "views": e.get("view_count"),
            "id": e.get("id"),
        })
    return results


class _Quiet:
    def debug(self, msg):
        pass

    info = warning = error = debug


def _views(n) -> str:
    if not n:
        return ""
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + unit
    return str(n)


def search_main(argv) -> int:
    import argparse
    from sdexe.cli import quiet_sdexe_logger
    quiet_sdexe_logger()

    class P(argparse.ArgumentParser):
        def error(self, message):
            raise UsageError(message[0].upper() + message[1:] + ".")

    p = P(prog="sdexe search", add_help=False)
    p.add_argument("words", nargs="*")
    p.add_argument("-n", "--limit", type=int, default=10)
    p.add_argument("-s", "--source", default="youtube", choices=tuple(SOURCES))
    p.add_argument("--json", action="store_true")
    p.add_argument("-h", "--help", action="store_true")
    try:
        args = p.parse_args(argv)
        if args.help:
            c = ui.console()
            c.print()
            c.print(HELP, soft_wrap=True)
            return 0
        query = " ".join(args.words).strip()
        if not query:
            raise UsageError('What should I look for? Example: sdexe search "lofi hip hop"')
        if not 1 <= args.limit <= 50:
            raise UsageError("--limit must be between 1 and 50.")
    except UsageError as e:
        print(f"sdexe search: {e}", file=sys.stderr)
        return 2

    c = ui.console()
    try:
        if c.is_terminal and not args.json:
            with c.status(f"  [muted]searching {args.source} for[/muted] {_escape(query)}", spinner="dots",
                          spinner_style="brand"):
                results = search(query, args.limit, args.source)
        else:
            results = search(query, args.limit, args.source)
    except Exception as e:  # noqa: BLE001
        from sdexe.app import _friendly_download_error
        msg = _friendly_download_error(str(e), cli=True)
        if args.json:
            print(json.dumps({"ok": False, "query": query, "error": msg}))
        else:
            print(f"sdexe search: {msg}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"ok": True, "query": query, "source": args.source, "results": results},
                         indent=2, ensure_ascii=False))
        return 0
    if not c.is_terminal:
        for r in results:
            print("\t".join([r["url"], r["title"], r["channel"], fmt_time(r["duration"]) if r["duration"] else ""]))
        return 0 if results else 1

    from rich.table import Table
    c.print()
    if not results:
        c.print(f"  [warn]![/warn] Nothing found for {_escape(query)}.\n")
        return 1
    t = Table.grid(padding=(0, 2))
    t.add_column(style="faint", justify="right")
    t.add_column(no_wrap=True, overflow="ellipsis", max_width=max(c.width - 40, 24))
    t.add_column(style="muted", no_wrap=True, overflow="ellipsis", max_width=20)
    t.add_column(style="muted", justify="right")
    t.add_column(style="faint", justify="right")
    for i, r in enumerate(results, 1):
        t.add_row(str(i), f"[link={r['url']}]{_escape(r['title'])}[/link]", _escape(r["channel"]),
                  fmt_time(r["duration"]) if r["duration"] else "", _views(r["views"]))
    c.print(ui.section(f"{len(results)} results for “{query}”"))
    c.print(ui._indent(t, 2))
    c.print()
    c.print(f"  [muted]download one:[/muted] [brand]sdexe download[/brand] [brand2]\"{_escape(results[0]['url'])}\"[/brand2]")
    c.print(f"  [muted]or the top hit directly:[/muted] [brand]sdexe download[/brand] "
            f"[brand2]\"{SOURCES[args.source]}:{_escape(query)}\"[/brand2]\n")
    return 0
