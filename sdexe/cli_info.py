"""`sdexe info`: what a link holds and what `sdexe download` would fetch, without
downloading anything.

Takes the same tags as `sdexe download`, so `sdexe info URL -720p` is a dry run
of `sdexe download URL -720p`. Output follows the download command: --json on
stdout, a readable summary otherwise. Exit 0 when every link resolved, 1 if
any failed, 2 on bad usage.
"""

import json
import sys

import yt_dlp

from sdexe import media, ui
from sdexe.app import _friendly_download_error
from sdexe.cli import (UsageError, collect_urls, fmt_size, fmt_time, parse_args, quiet_sdexe_logger,
                       resolve_spec, youtube_warnings, ydl_base_opts, _escape)

HELP = """\
  [title]sdexe info[/title] [muted]· what a link holds, and what sdexe download would fetch · nothing is downloaded[/muted]

  [brand]sdexe info[/brand] [brand2]"<link>" \\["<link>" …] \\[format] \\[quality] \\[options][/brand2]

  [muted]Title, uploader, length, every quality with its size, audio streams, chapters and subtitles.
  Takes the same tags as[/muted] [brand]sdexe download[/brand][muted], so[/muted] [brand]sdexe info[/brand] [brand2]"<link>" -720p[/brand2]
  [muted]shows exactly what[/muted] [brand]sdexe download[/brand] [brand2]"<link>" -720p[/brand2] [muted]would pick.[/muted]

  [brand]◆[/brand] [title]Options[/title]
    [brand2]--json[/brand2]                     one JSON document on stdout
    [brand2]--playlist[/brand2]                 list every video in a playlist or channel link
    [brand2]--limit N[/brand2]                  only the first N entries (implies --playlist)
    [brand2]-i, --input FILE[/brand2]           links from a file, one per line ([brand2]-[/brand2] for stdin)
    [brand2]--cookies-from-browser B[/brand2]   your browser's login: chrome, safari, firefox, brave, edge
    [brand2]-v, --verbose[/brand2]              yt-dlp's own log

  [brand]◆[/brand] [title]Examples[/title]
    [brand]sdexe info[/brand] [brand2]"https://youtu.be/dQw4w9WgXcQ"[/brand2]
    [brand]sdexe info[/brand] [brand2]"https://youtu.be/dQw4w9WgXcQ" --best --json[/brand2]
    [brand]sdexe info[/brand] [brand2]"<playlist>" --limit 20[/brand2]
"""

_UNAVAILABLE = ("[Private video]", "[Deleted video]", "[Unavailable video]")


def _size_of(f):
    return f.get("filesize") or f.get("filesize_approx") or 0


def _rate_of(f):
    return f.get("tbr") or f.get("vbr") or f.get("abr") or 0


def _codec(c):
    """avc1.64002a -> avc1, vp09.00.41.08 -> vp9, mp4a.40.2 -> aac."""
    c = (c or "").split(".")[0].lower()
    return {"vp09": "vp9", "av01": "av1", "mp4a": "aac", "avc1": "h264"}.get(c, c) or None


def _quality_tag(height, fps):
    return f"{height}p{int(round(fps)) if fps else ''}"


def summarize(info):
    """Per-(resolution, fps) video rows and distinct audio streams."""
    formats = info.get("formats") or []
    duration = info.get("duration") or 0

    audio = [f for f in formats if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
             and not f.get("has_drm") and "drc" not in (f.get("format_id") or "")]
    audio.sort(key=lambda f: (f.get("abr") or _rate_of(f)), reverse=True)
    best_audio = _size_of(audio[0]) if audio else 0

    def rank(f):
        # Known size beats HLS; then bitrate.
        return (bool(_size_of(f)), "m3u8" not in (f.get("protocol") or ""), _rate_of(f))

    best = {}
    for f in formats:
        if f.get("vcodec") in (None, "none") or not f.get("height") or f.get("has_drm"):
            continue
        if not _rate_of(f) and not _size_of(f):
            continue  # storyboards
        key = (f["height"], int(round(f.get("fps") or 0)))
        if key not in best or rank(f) > rank(best[key]):
            best[key] = f

    video = []
    for (h, fps) in sorted(best, reverse=True):
        f = best[(h, fps)]
        size, approx = _size_of(f), not f.get("filesize")
        if not size and _rate_of(f) and duration:
            size = int(_rate_of(f) * 125 * duration)
        if size and f.get("acodec") in (None, "none"):
            size += best_audio
        video.append({
            "quality": _quality_tag(h, fps), "height": h, "width": f.get("width"), "fps": fps or None,
            "vcodec": _codec(f.get("vcodec")), "size_bytes": size or None, "approx_size": approx,
        })

    audio_rows, seen = [], set()
    for f in audio:
        abr = int(round(f.get("abr") or _rate_of(f) or 0))
        codec = _codec(f.get("acodec"))
        if not abr or (codec, abr // 16) in seen:
            continue
        seen.add((codec, abr // 16))
        audio_rows.append({"abr_kbps": abr, "acodec": codec, "ext": f.get("ext"),
                           "size_bytes": _size_of(f) or None})
    return video, audio_rows


def _selection(info, spec):
    """What `sdexe download` with this spec would fetch."""
    picked = info.get("requested_formats") or ([info] if info.get("format_id") else [])
    if not picked:
        return None
    duration = info.get("duration") or 0
    size, approx = 0, False
    for f in picked:
        s = f.get("filesize")
        if not s:
            s = f.get("filesize_approx") or (int(_rate_of(f) * 125 * duration) if duration else 0)
            approx = True
        size += s or 0
    v = next((f for f in picked if f.get("vcodec") not in (None, "none")), None)
    a = next((f for f in picked if f.get("acodec") not in (None, "none")), None)
    out = {"format": spec.fmt, "requested": spec.label}
    if v and not spec.is_audio:
        out.update({"quality": _quality_tag(v.get("height"), v.get("fps")), "width": v.get("width"),
                    "height": v.get("height"), "fps": v.get("fps"), "vcodec": _codec(v.get("vcodec"))})
    if a:
        out.update({"acodec": _codec(a.get("acodec")), "abr_kbps": int(round(a.get("abr") or 0)) or None})
    # Audio formats are converted after download, so source size says little.
    if not spec.is_audio or spec.fmt in ("m4a", "opus"):
        out.update({"size_bytes": size or None, "approx_size": approx})
    return out


def describe(url, info, spec):
    if info.get("_type") in ("playlist", "multi_video"):
        entries = []
        for e in info.get("entries") or []:
            if not e or (e.get("title") or "") in _UNAVAILABLE:
                continue
            entries.append({"title": e.get("title"), "url": e.get("url") or e.get("webpage_url"),
                            "id": e.get("id"), "duration": e.get("duration")})
        return {"url": url, "ok": True, "type": "playlist", "title": info.get("title"),
                "uploader": info.get("uploader") or info.get("channel"),
                "count": info.get("playlist_count") or len(entries), "entries": entries}

    video, audio = summarize(info)
    upload = info.get("upload_date") or ""
    if len(upload) == 8:
        upload = f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"
    subs = sorted((info.get("subtitles") or {}).keys())
    return {
        "url": url, "ok": True, "type": "video",
        "id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration"),
        "upload_date": upload or None,
        "view_count": info.get("view_count"),
        "is_live": bool(info.get("is_live")),
        "source": info.get("extractor_key"),
        "webpage_url": info.get("webpage_url") or url,
        "thumbnail": info.get("thumbnail"),
        "description": info.get("description") or "",
        "chapters": [{"title": c.get("title"), "start": c.get("start_time"), "end": c.get("end_time")}
                     for c in info.get("chapters") or []],
        "subtitles": [s for s in subs if s != "live_chat"],
        "auto_captions": bool(info.get("automatic_captions")),
        "video_formats": video,
        "audio_formats": audio,
        "download": _selection(info, spec),
    }


def _num(n):
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + unit
    return str(n)


def _size_label(size, approx):
    return f"{'~' if approx else ''}{fmt_size(size)}" if size else ""


def render(console, r, args):
    from rich.table import Table
    from rich.text import Text
    if not r["ok"]:
        console.print(f"  [err]✗[/err] {_escape(r['url'])}")
        console.print(f"    [err]{_escape(r['error'])}[/err]\n")
        return
    if r["type"] == "playlist":
        n = r["count"]
        console.print(f"  [title]{_escape(r['title'] or 'Playlist')}[/title]")
        meta = " · ".join(x for x in (r.get("uploader"), f"{n} video{'s' if n != 1 else ''}", "playlist") if x)
        console.print(f"  [muted]{_escape(meta)}[/muted]")
        console.print(f"  [faint]{_escape(r['url'])}[/faint]\n")
        t = Table.grid(padding=(0, 2))
        t.add_column(style="faint", justify="right")
        t.add_column(no_wrap=True, overflow="ellipsis", max_width=max(console.width - 20, 20))
        t.add_column(style="muted", justify="right")
        for i, e in enumerate(r["entries"], 1):
            t.add_row(str(i), _escape(e["title"] or e["url"]), fmt_time(e["duration"]) if e.get("duration") else "")
        console.print(ui._indent(t, 2))
        if r.get("note") and r["count"] > len(r["entries"]):
            console.print(f"\n  [muted]… {r['count'] - len(r['entries'])} more ·[/muted] [brand2]--playlist[/brand2] "
                          f"[muted]lists them all[/muted]")
        console.print()
        return

    meta = [r.get("uploader"), fmt_time(r["duration"]) if r.get("duration") else None, r.get("upload_date"),
            f"{_num(r['view_count'])} views" if r.get("view_count") else None, r.get("source")]
    console.print(f"  [title]{_escape(r['title'])}[/title]")
    console.print(f"  [muted]{_escape(' · '.join(m for m in meta if m))}[/muted]")
    console.print(f"  [faint]{_escape(r['webpage_url'])}[/faint]")
    if r["is_live"]:
        console.print("  [warn]● live stream[/warn]")
    console.print()

    d = r.get("download")
    if d:
        line = Text("    ")
        line.append(d["format"].upper(), style="brand.bold")
        for part in (d.get("quality"), " + ".join(x for x in (d.get("vcodec"), d.get("acodec")) if x),
                     _size_label(d.get("size_bytes"), d.get("approx_size"))):
            if part:
                line.append("  ·  ", style="faint")
                line.append(part)
        line.append(f"    {d['requested']}", style="faint")
        console.print(ui.section("sdexe download would get"))
        console.print(line)
        console.print()

    if r["video_formats"]:
        console.print(ui.section("Video qualities"))
        t = Table.grid(padding=(0, 3))
        t.add_column(style="brand", no_wrap=True)
        t.add_column(style="muted")
        t.add_column(style="muted", justify="right")
        for v in r["video_formats"]:
            t.add_row(v["quality"], v["vcodec"] or "", _size_label(v["size_bytes"], v["approx_size"]))
        console.print(ui._indent(t, 4))
        console.print()
    if r["audio_formats"]:
        console.print(ui.section("Audio"))
        console.print("    " + "  [faint]·[/faint]  ".join(
            f"{a['abr_kbps']} kbps [muted]{a['acodec'] or ''}[/muted]" for a in r["audio_formats"]))
        console.print()
    if r["chapters"]:
        console.print(ui.section(f"Chapters · {len(r['chapters'])}"))
        for ch in r["chapters"][:8]:
            console.print(f"    [muted]{fmt_time(ch['start'] or 0):>7}[/muted]  {_escape(ch['title'])}")
        if len(r["chapters"]) > 8:
            console.print(f"    [faint]… {len(r['chapters']) - 8} more[/faint]")
        console.print()
    if r["subtitles"] or r["auto_captions"]:
        subs = ", ".join(r["subtitles"][:12]) or "none"
        console.print(ui.section("Subtitles"))
        console.print(f"    {subs}" + ("  [muted]+ auto captions[/muted]" if r["auto_captions"] else ""))
        console.print()


def info_main(argv) -> int:
    quiet_sdexe_logger()
    try:
        args, tags = parse_args(argv, prog="info")
        if args.help:
            c = ui.console()
            c.print()
            c.print(HELP, soft_wrap=True)
            return 0
        urls = collect_urls(args, "info")
        spec = resolve_spec(tags)  # the user's defaults when no tag is given
    except UsageError as e:
        print(f"sdexe info: {e}", file=sys.stderr)
        return 2

    log = (lambda m: print(m, file=sys.stderr)) if args.verbose else None
    opts = {
        **media.build_ydl_opts(spec.fmt, height=spec.height, fps=spec.fps, bitrate=spec.bitrate,
                               prefer_fps=True, thumbnail=False),
        **ydl_base_opts(args, log),
    }
    if not args.playlist:
        opts["playlistend"] = 10  # a preview; don't page through a whole channel

    console = None
    if not args.json:
        console = ui.console()
        for w in spec.warnings + youtube_warnings(urls):
            ui.console(stderr=True).print(f"  [warn]![/warn] [muted]{_escape(w)}[/muted]")
        console.print()

    results = []
    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in urls:
            try:
                if console and sys.stdout.isatty():
                    with console.status(f"  [muted]reading {_escape(url)}[/muted]", spinner="dots"):
                        info = ydl.extract_info(url, download=False)
                else:
                    info = ydl.extract_info(url, download=False)
                r = describe(url, info, spec)
                if r["type"] == "playlist" and not args.playlist:
                    r["note"] = "First 10 entries only. Add --playlist for all."
            except Exception as e:  # noqa: BLE001
                r = {"url": url, "ok": False, "error": _friendly_download_error(str(e), cli=True)}
            results.append(r)
            if console:
                render(console, r, args)

    if args.json:
        doc = {"ok": all(r["ok"] for r in results), "results": results, "warnings": spec.warnings}
        print(json.dumps(doc, indent=2, ensure_ascii=False))
    return 0 if all(r["ok"] for r in results) else 1
