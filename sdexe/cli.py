"""`sdexe download`: media downloads from the terminal, for people and agents.

stdout carries only results (saved paths, or one JSON document with --json) so
a caller can capture them. Progress, warnings, and errors go to stderr: a live
display on a terminal, plain one-line events when piped.

Exit codes: 0 all saved, 1 at least one failed, 2 bad usage, 130 interrupted.
"""

import argparse
import difflib
import json
import logging
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from sdexe import media, tools, ui
from sdexe.app import _friendly_download_error, _safe_filename


class UsageError(Exception):
    pass


# ── Tags ──
# Format and quality can be given as flags (-mp3, --1080p), bare words (mp3,
# 1080p), or -f/-q values. They all resolve through the same tables.

FORMAT_ALIASES = {f: f for f in media.VIDEO_FORMATS + media.AUDIO_FORMATS}
FORMAT_ALIASES.update({"aac": "m4a", "ogg": "opus"})
KIND_ALIASES = {"audio": "audio", "video": "video"}
BEST_ALIASES = {"best", "max", "highest", "hq"}
RES_ALIASES = {"8k": 4320, "4k": 2160, "uhd": 2160, "2k": 1440, "qhd": 1440, "fhd": 1080, "hd": 720, "sd": 480}
_RES_RE = re.compile(r"(\d{3,4})p(\d{2,3})?")
_RES_ALIAS_RE = re.compile(r"(8k|4k|uhd|2k|qhd|fhd|hd|sd)(\d{2,3})?")
_BITRATE_RE = re.compile(r"(\d{2,3})(k|kb|kbps)?")

VIDEO_QUALITY_HELP = "2160p/4k, 1440p, 1080p, 720p, 480p, 360p (add 30 or 60 for fps, e.g. 720p30), best"
MEDIA_EXTS = set(media.VIDEO_FORMATS + media.AUDIO_FORMATS)


def classify_tag(token: str):
    """Return ("format", fmt) / ("kind", k) / ("quality", dict) or None."""
    t = token.lower().strip()
    if t in FORMAT_ALIASES:
        return ("format", FORMAT_ALIASES[t])
    if t in KIND_ALIASES:
        return ("kind", KIND_ALIASES[t])
    if t in BEST_ALIASES:
        return ("quality", {"best": True, "label": "best"})
    m = _RES_RE.fullmatch(t)
    if m and int(m.group(1)) in (144, 240, 360, 480, 720, 1080, 1440, 2160, 4320):
        fps = int(m.group(2)) if m.group(2) else None
        return ("quality", {"height": int(m.group(1)), "fps": fps, "label": t})
    m = _RES_ALIAS_RE.fullmatch(t)
    if m:
        fps = int(m.group(2)) if m.group(2) else None
        h = RES_ALIASES[m.group(1)]
        return ("quality", {"height": h, "fps": fps, "label": f"{h}p{fps or ''}"})
    if t in ("360", "480", "720", "1080", "1440", "2160"):
        return ("quality", {"height": int(t), "fps": None, "label": f"{t}p"})
    m = _BITRATE_RE.fullmatch(t)
    if m and m.group(1) in media.MP3_BITRATES:
        return ("quality", {"bitrate": m.group(1), "label": f"{m.group(1)} kbps"})
    return None


@dataclass
class Spec:
    fmt: str
    height: int | None = None
    fps: int | None = None
    bitrate: str | None = None
    best: bool = False
    warnings: list = field(default_factory=list)

    @property
    def is_audio(self):
        return self.fmt in media.AUDIO_FORMATS

    @property
    def label(self):
        name = self.fmt.upper()
        if self.fmt == "mp3":
            return f"{name} · {self.bitrate} kbps"
        if self.is_audio:
            return f"{name} · lossless" if self.fmt in ("wav", "flac") else name
        if self.best:
            return f"{name} · best available"
        return f"{name} · up to {self.height}p{self.fps or ''}"


def download_defaults() -> dict:
    """The user's defaults from `sdexe settings`, for when no tag says otherwise."""
    try:
        from sdexe import settings
        v = settings.all_values()
    except Exception:  # noqa: BLE001 - a broken config must not break downloads
        v = {}
    return {
        "video": v.get("dl_video_format", "mp4"),
        "quality": v.get("dl_quality", "1080p60"),
        "audio": v.get("dl_audio_format", "wav"),
        "bitrate": v.get("dl_mp3_bitrate", "320"),
        "folder": v.get("dl_folder", ""),
        "jobs": v.get("dl_jobs", 3),
        "cover_art": v.get("dl_cover_art", True),
        "tags": v.get("dl_tags", True),
    }


def resolve_spec(tags, output_ext=None, defaults=None) -> Spec:
    d = defaults or download_defaults()
    formats, kinds, qualities = [], [], []
    for kind, value in tags:
        {"format": formats, "kind": kinds, "quality": qualities}[kind].append(value)

    if output_ext:
        formats.append(output_ext)
    formats = list(dict.fromkeys(formats))
    if len(formats) > 1:
        raise UsageError(f"Pick one format, got {' and '.join(formats)}.")
    if len(set(kinds)) > 1:
        raise UsageError("Pick audio or video, not both.")
    labels = list(dict.fromkeys(q["label"] for q in qualities))
    if len(labels) > 1:
        raise UsageError(f"Pick one quality, got {' and '.join(labels)}.")

    kind = kinds[0] if kinds else None
    if formats:
        fmt = formats[0]
        if kind == "audio" and fmt in media.VIDEO_FORMATS:
            raise UsageError(f"{fmt} is a video format. For audio use wav, mp3, flac, m4a or opus.")
        if kind == "video" and fmt in media.AUDIO_FORMATS:
            raise UsageError(f"{fmt} is an audio format. For video use mp4, webm or mkv.")
    else:
        fmt = d["audio"] if kind == "audio" else d["video"]

    spec = Spec(fmt=fmt)
    q = qualities[0] if qualities else {}
    if spec.is_audio:
        if q.get("height"):
            spec.warnings.append(f"{q['label']} is a video quality, ignored for {fmt}.")
        if fmt == "mp3":
            spec.bitrate = q.get("bitrate") or d["bitrate"]
        elif q.get("bitrate"):
            why = "lossless" if fmt in ("wav", "flac") else "kept at the source stream's quality"
            spec.warnings.append(f"{fmt} is {why}, so {q['label']} is ignored. Bitrate applies to mp3.")
    else:
        if q.get("bitrate"):
            spec.warnings.append(f"{q['label']} is an audio bitrate, ignored for {fmt} video.")
        if q.get("best"):
            spec.best = True
        elif q.get("height"):
            spec.height, spec.fps = q["height"], q.get("fps")
        else:
            tag = classify_tag(d["quality"]) or ("quality", {"height": 1080, "fps": 60})
            spec.best = bool(tag[1].get("best"))
            spec.height, spec.fps = tag[1].get("height"), tag[1].get("fps")
    return spec


def parse_time(value: str) -> float:
    """Seconds from "90", "1:30", "1:02:03", "1m30s" or "2h"."""
    v = value.strip().lower()
    try:
        if ":" in v:
            total = 0.0
            for part in v.split(":"):
                total = total * 60 + float(part)
            return total
        if re.fullmatch(r"(\d+(\.\d+)?h)?(\d+(\.\d+)?m)?(\d+(\.\d+)?s)?", v) and v:
            total = 0.0
            for num, unit in re.findall(r"(\d+(?:\.\d+)?)([hms])", v):
                total += float(num) * {"h": 3600, "m": 60, "s": 1}[unit]
            return total
        return float(v)
    except ValueError:
        raise UsageError(f"Can't read time '{value}'. Use seconds (90), 1:30, 1:02:03 or 1m30s.")


def fmt_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


_SEARCH_RE = re.compile(r"(ytsearch|scsearch)(\d*):.+", re.I | re.S)


def is_search(url: str) -> bool:
    """yt-dlp search pseudo-links: "ytsearch:words" is the top YouTube hit."""
    return bool(_SEARCH_RE.fullmatch(url or ""))


def normalize_url(token: str) -> str | None:
    if re.match(r"https?://", token, re.I) or is_search(token):
        return token
    # youtu.be/abc, www.youtube.com/watch?v=..., soundcloud.com/x/y
    if re.match(r"^[\w-]+(\.[\w-]+)+(/\S*)?$", token) and not token.lower().endswith(tuple("." + e for e in MEDIA_EXTS)):
        return "https://" + token
    return None


# ── Argument parsing ──

VALUE_OPTS = {"-o", "--output", "-i", "--input", "-f", "--format", "-q", "--quality", "--limit",
              "--start", "--end", "-j", "--jobs", "--cookies-from-browser"}
FLAG_OPTS = {"-h", "--help", "--playlist", "--json", "--quiet", "-v", "--verbose", "--"}
TAG_HINTS = sorted(set(FORMAT_ALIASES) | set(KIND_ALIASES) | BEST_ALIASES | {"1080p", "720p", "4k", "320"})


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message[0].upper() + message[1:] + ".")


def _parser():
    p = _Parser(prog="sdexe download", add_help=False)
    p.add_argument("urls", nargs="*")
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("-o", "--output")
    p.add_argument("-i", "--input", action="append", default=[])
    p.add_argument("--playlist", action="store_true")
    p.add_argument("--limit", type=int)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("-j", "--jobs", type=int)
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--cookies-from-browser", metavar="BROWSER")
    return p


def parse_args(argv, prog="download"):
    """Split tags out of argv, then parse the rest. Returns (args, tags)."""
    rest, tags = [], []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            rest.extend(argv[i:])
            break
        opt = tok.split("=", 1)[0]
        if opt in ("-f", "--format", "-q", "--quality"):
            value = tok.split("=", 1)[1] if "=" in tok else (argv[i + 1] if i + 1 < len(argv) else None)
            if value is None:
                raise UsageError(f"{opt} needs a value.")
            tag = classify_tag(value)
            if opt in ("-f", "--format") and (not tag or tag[0] == "quality"):
                raise UsageError(f"Unknown format '{value}'. Video: mp4, webm, mkv. Audio: wav, mp3, flac, m4a, opus.")
            if opt in ("-q", "--quality") and (not tag or tag[0] != "quality"):
                raise UsageError(f"Unknown quality '{value}'. Video: {VIDEO_QUALITY_HELP}. MP3: 128, 192, 256, 320.")
            tags.append(tag)
            i += 1 if "=" in tok else 2
            continue
        if opt in VALUE_OPTS:
            rest.append(tok)
            if "=" not in tok and i + 1 < len(argv):
                rest.append(argv[i + 1])
                i += 1
            i += 1
            continue
        if tok == "-a":
            tags.append(("kind", "audio"))
        elif tok in FLAG_OPTS:
            rest.append(tok)
        elif tok.startswith("-"):
            tag = classify_tag(tok.lstrip("-"))
            if not tag and tok[:2] in ("-o", "-i", "-j") and len(tok) > 2:
                rest.append(tok)  # attached value, e.g. -j4
                i += 1
                continue
            if not tag:
                guess = difflib.get_close_matches(tok.lstrip("-").lower(), TAG_HINTS, n=1)
                hint = f" Did you mean -{guess[0]}?" if guess else f" Run `sdexe {prog} --help` for options."
                raise UsageError(f"Unknown option {tok}.{hint}")
            tags.append(tag)
        else:
            tag = classify_tag(tok)
            if tag:
                tags.append(tag)
            else:
                rest.append(tok)
        i += 1
    return _parser().parse_args(rest), tags


HELP = """\
  [title]sdexe download[/title] [muted]· save video or audio from a link, straight to disk[/muted]

  [brand]sdexe download[/brand] [brand2]"<link>" \\["<link>" …] \\[format] \\[quality] \\[options][/brand2]

  With no tags you get [title]{video_default}[/title]; [brand2]-a[/brand2] gets [title]{audio_default}[/title].
  [muted]Those are your defaults: change them in[/muted] [brand]sdexe settings[/brand][muted].[/muted]
  [muted]Tags can be written -mp3, --mp3, mp3 or -f mp3; quality as -720p, 720p or -q 720p.[/muted]

  [brand]◆[/brand] [title]Formats[/title]
    [brand2]video[/brand2]        mp4 · webm · mkv
    [brand2]audio[/brand2]        wav · mp3 · flac · m4a · opus
    [brand2]-a, --audio[/brand2]  audio only, in your audio format unless a tag says otherwise

  [brand]◆[/brand] [title]Quality[/title]
    [brand2]video[/brand2]        2160p/4k · 1440p · 1080p · 720p · 480p · 360p   [muted]add fps: 1080p30, 720p60[/muted]
                 [muted]a ceiling: the best stream at or under it, stepping down when a video has less[/muted]
    [brand2]best[/brand2]         no cap: 4K/8K when offered, top frame rate and bitrate
    [brand2]mp3[/brand2]          128 · 192 · 256 · 320 kbps

  [brand]◆[/brand] [title]Options[/title]
    [brand2]-o, --output PATH[/brand2]          a folder, or a file name like clip.mp4 for one link
    [brand2]-i, --input FILE[/brand2]           links from a file, one per line ([brand2]-[/brand2] for stdin)
    [brand2]--playlist[/brand2]                 every video in a playlist or channel link
    [brand2]--limit N[/brand2]                  only the first N of a playlist (implies --playlist)
    [brand2]--start TIME, --end TIME[/brand2]   only part: 90, 1:30, 1:02:03, 1m30s
    [brand2]-j, --jobs N[/brand2]               downloads at once (yours: {jobs})
    [brand2]--cookies-from-browser B[/brand2]   your browser's login: chrome, safari, firefox, brave, edge
    [brand2]--json[/brand2]                     one JSON result document on stdout
    [brand2]--quiet[/brand2]                    no progress, errors only
    [brand2]-v, --verbose[/brand2]              yt-dlp's own log

  [brand]◆[/brand] [title]Output[/title]
    [muted]Saved paths go to stdout, one per line, as each finishes; progress and errors to stderr.
    Exit code 0 when everything saved, 1 if any link failed. Folder: {folder}.[/muted]

  [brand]◆[/brand] [title]Examples[/title]
    [brand]sdexe download[/brand] [brand2]"https://youtu.be/dQw4w9WgXcQ"[/brand2]
    [brand]sdexe download[/brand] [brand2]"https://youtu.be/dQw4w9WgXcQ" -mp3[/brand2]
    [brand]sdexe download[/brand] [brand2]"https://youtu.be/dQw4w9WgXcQ" -720p -o ~/Movies[/brand2]
    [brand]sdexe download[/brand] [brand2]"<link>" --start 1:30 --end 2:00 -o clip.mp4[/brand2]
    [brand]sdexe download[/brand] [brand2]"<playlist>" --playlist --limit 10 -mp3[/brand2]
    [brand]sdexe download[/brand] [brand2]"<link>" --json[/brand2]
"""


def print_help(file=None):
    from sdexe import settings
    d = download_defaults()
    spec_v = resolve_spec([], defaults=d)
    spec_a = resolve_spec([("kind", "audio")], defaults=d)
    c = ui.console(file=file or sys.stdout)
    c.print()
    c.print(HELP.format(video_default=spec_v.label, audio_default=spec_a.label, jobs=d["jobs"],
                        folder=settings.BY_KEY["dl_folder"].show(d["folder"])), soft_wrap=True)


# ── Downloading ──

PP_STAGES = {
    "FFmpegMerger": "merging video + audio",
    "FFmpegVideoRemuxer": "remuxing",
    "FFmpegMetadata": "writing tags",
    "EmbedThumbnail": "adding cover art",
    "FFmpegEmbedSubtitle": "embedding subtitles",
    "MoveFiles": "finishing",
}
_THUMB_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ATTEMPTS = media.ATTEMPTS


@dataclass(eq=False)
class Item:
    url: str
    entry: dict | None = None      # flat playlist entry, when expanded from one
    playlist: str | None = None
    title: str = ""
    status: str = "queued"         # queued, running, done, failed, expanded
    stage: str = "waiting"
    streams: dict = field(default_factory=dict)
    expected: float = 0
    speed: float | None = None
    eta: int | None = None
    path: Path | None = None
    error: str = ""
    info: dict = field(default_factory=dict)
    spinner: object = None
    thumbnail: bool = True

    @property
    def downloaded(self):
        return sum(d for d, _ in self.streams.values())

    @property
    def total(self):
        known = sum(t or 0 for _, t in self.streams.values())
        return max(self.expected, known) or None

    @property
    def name(self):
        return self.title or self.url

    def quality(self):
        i = self.info
        if not i:
            return ""
        if i.get("height") and i.get("vcodec") not in (None, "none"):
            fps = i.get("fps")
            return f"{i['height']}p{int(round(fps)) if fps else ''}"
        return ""


class _YtdlpLog:
    def __init__(self, emit=None):
        self.emit = emit

    def debug(self, msg):
        if self.emit:
            self.emit(msg)

    info = debug

    def warning(self, msg):
        if self.emit:
            self.emit(f"warning: {msg}")

    def error(self, msg):
        if self.emit:
            self.emit(msg)


def ydl_base_opts(args, log=None) -> dict:
    """yt-dlp options every command shares: quiet, JS runtime, cookies,
    playlist handling. log receives yt-dlp's messages (for --verbose)."""
    opts = {
        "quiet": True,
        "no_warnings": log is None,
        "noprogress": True,
        "logger": _YtdlpLog(log),
        "noplaylist": not args.playlist,
        "extract_flat": "in_playlist",
        "js_runtimes": media.js_runtimes(),
    }
    if args.limit:
        opts["playlistend"] = args.limit  # don't page through a whole channel
    ffmpeg = tools.ffmpeg_path()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    if args.cookies_from_browser:
        opts["cookiesfrombrowser"] = (args.cookies_from_browser.lower(), None, None, None)
    return opts


class Downloader:
    def __init__(self, urls, spec, args, out_dir, out_file=None, clip=(None, None), defaults=None,
                 silent=False):
        self.defaults = defaults or download_defaults()
        self.items = [Item(u, thumbnail=bool(self.defaults["cover_art"])) for u in urls]
        self.spec = spec
        self.args = args
        self.out_dir = out_dir
        self.out_file = out_file
        self.clip = clip
        self.q = queue.Queue()
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.claimed = set()
        self.tmp_dirs = set()
        self.started = time.time()
        self.stderr_tty = sys.stderr.isatty()
        self.stdout_tty = sys.stdout.isatty()
        self.live = None
        self.console = None
        self.silent = silent
        if self.stderr_tty and not args.quiet and not silent:
            from rich.console import Console
            self.console = ui.console(stderr=True)

    # stderr events, for when there is no live display
    def _event(self, text, error=False):
        if self.live or self.silent:
            return
        if self.args.quiet and not error:
            return
        if self.args.json and not self.stderr_tty and not error:
            return
        print(text, file=sys.stderr, flush=True)

    def _log(self, msg):
        if self.live:
            self.live.console.print(f"[faint]{_escape(msg)}[/faint]")
        else:
            print(msg, file=sys.stderr, flush=True)

    def _ydl_opts(self, item, tmp):
        opts = media.build_ydl_opts(
            self.spec.fmt,
            height=self.spec.height,
            fps=self.spec.fps,
            bitrate=self.spec.bitrate,
            prefer_fps=True,
            embed_metadata=bool(self.defaults["tags"]),
            force_container=True,
            thumbnail=item.thumbnail,
        )
        media.apply_clip(opts, *self.clip)

        def progress_hook(d):
            if self.cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")
            key = d.get("filename") or d.get("tmpfilename") or "?"
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                item.streams[key] = (d.get("downloaded_bytes") or 0, total)
                item.speed, item.eta = d.get("speed"), d.get("eta")
                item.stage = "downloading"
            elif d["status"] == "finished":
                done = d.get("total_bytes") or d.get("downloaded_bytes") or 0
                item.streams[key] = (done, done)
                item.speed = item.eta = None

        def pp_hook(d):
            if d["status"] != "started":
                return
            name = d.get("postprocessor", "")
            if name == "FFmpegExtractAudio":
                item.stage = f"converting to {self.spec.fmt.upper()}"
            elif name.startswith("FFmpegFixup"):
                item.stage = "fixing up stream"
            else:
                item.stage = PP_STAGES.get(name, item.stage)

        opts.update(ydl_base_opts(self.args, self._log if self.args.verbose else None))
        opts.update({
            "outtmpl": str(tmp / "%(id).60s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [pp_hook],
            "concurrent_fragment_downloads": 4,
            "retries": 5,
            "fragment_retries": 5,
        })
        return opts

    def _expand(self, item, info):
        entries = [e for e in (info.get("entries") or []) if e]
        title = info.get("title") or "playlist"
        if self.args.playlist and self.args.limit:
            entries = entries[:self.args.limit]
        searching = is_search(item.url)
        if not self.args.playlist and not searching:
            raise _Fail(f"This link is a playlist ({_videos(len(entries))}). Add --playlist to download all of them.")
        if searching and not entries:
            raise _Fail("Nothing found for that search.")
        if self.out_file and not (searching and len(entries) == 1):
            raise _Fail(f"-o {self.out_file.name} names a single file, but this playlist has {_videos(len(entries))}. "
                        "Pass a folder instead.")
        if not entries:
            raise _Fail("This playlist is empty.")
        children = []
        for e in entries:
            url = e.get("url") or e.get("webpage_url")
            # Flat extraction still lists members nobody can fetch.
            if not url or (e.get("title") or "") in ("[Private video]", "[Deleted video]", "[Unavailable video]") \
                    or e.get("availability") in ("private", "needs_auth", "subscriber_only", "premium_only"):
                continue
            children.append(Item(url, entry=e, playlist=title, title=e.get("title") or "",
                                 thumbnail=bool(self.defaults["cover_art"])))
        with self.lock:
            idx = self.items.index(item)
            self.items[idx:idx + 1] = [item] + children
            item.status = "expanded"
            item.title = title
        for c in children:
            self.q.put(c)
        self._event(f"top result for “{title}”" if searching else f"playlist: {title} ({_videos(len(children))})")

    def _run(self, item):
        item.status = "running"
        item.stage = "fetching info"
        self._event(f"→ {item.title or item.url}")
        for attempt in range(1, ATTEMPTS + 1):
            if self.cancel.is_set():
                item.status, item.error = "failed", "Download cancelled."
                break
            try:
                if self._attempt(item) == "expanded":
                    return
                item.status = "done"
                break
            except _Fail as e:
                item.status, item.error = "failed", str(e)
                break
            except Exception as e:  # noqa: BLE001 - one bad link must not end the batch
                raw = str(e)
                if item.thumbnail and media.is_thumbnail_failure(raw) and attempt < ATTEMPTS:
                    # Cover art is a nicety; never lose the download over it.
                    item.thumbnail = False
                    item.stage = "retrying without cover art"
                    item.streams.clear()
                    continue
                if attempt < ATTEMPTS and not self.cancel.is_set() and media.is_retryable(raw):
                    item.stage = f"retrying ({attempt + 1}/{ATTEMPTS})"
                    item.streams.clear()
                    time.sleep(attempt)
                    continue
                item.status = "failed"
                item.error = _friendly_download_error(raw, cancelled=self.cancel.is_set(), cli=True)
                break

        if item.status == "done":
            size = item.path.stat().st_size
            bits = ", ".join(b for b in (item.quality(), fmt_size(size)) if b)
            self._event(f"✓ {item.name} → {item.path} ({bits})")
            if not self.stdout_tty and not self.args.json and not self.silent:
                print(item.path, flush=True)
        else:
            self._event(f"✗ {item.url}: {item.error}", error=True)

    def _attempt(self, item):
        tmp = Path(tempfile.mkdtemp(prefix="sdexe-dl-"))
        self.tmp_dirs.add(tmp)
        try:
            with yt_dlp.YoutubeDL(self._ydl_opts(item, tmp)) as ydl:
                if item.entry:
                    info = ydl.extract_info(item.url, ie_key=item.entry.get("ie_key"), download=False)
                else:
                    info = ydl.extract_info(item.url, download=False)
                if info.get("_type") in ("playlist", "multi_video"):
                    if item.entry:
                        raise _Fail("Nested playlists are not downloaded. Pass that playlist's own link.")
                    self._expand(item, info)
                    return "expanded"
                item.title = info.get("title") or item.title
                if self.clip == (None, None):
                    fmts = info.get("requested_formats") or [info]
                    item.expected = sum(f.get("filesize") or f.get("filesize_approx") or 0 for f in fmts)
                item.stage = "connecting"
                info = ydl.process_ie_result(info, download=True)
            item.info = info
            item.path = self._save(item, info, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            self.tmp_dirs.discard(tmp)

    def _save(self, item, info, tmp):
        produced = None
        for d in info.get("requested_downloads") or []:
            p = Path(d.get("filepath") or "")
            if p.is_file():
                produced = p
                break
        if produced is None:
            candidates = [f for f in tmp.iterdir() if f.is_file() and f.suffix.lower() not in _THUMB_EXTS
                          and not f.name.endswith((".part", ".ytdl"))]
            if not candidates:
                raise _Fail("Download finished but produced no file.")
            produced = max(candidates, key=lambda f: f.stat().st_size)
        if produced.stat().st_size == 0:
            raise _Fail("Download finished but the file is empty.")
        ext = produced.suffix.lstrip(".")

        with self.lock:
            if self.out_file:
                dest = self.out_file.with_suffix("." + ext)
                if ext != self.out_file.suffix.lstrip("."):
                    self._event(f"note: saved as .{ext}, the source had no {self.out_file.suffix} stream")
            else:
                stem = _safe_filename(info.get("title") or item.title, "download", max_len=180)
                start, end = self.clip
                if start is not None or end is not None:
                    stem += f" ({fmt_time(start or 0).replace(':', '.')}-{fmt_time(end).replace(':', '.') if end else 'end'})"
                dest = self.out_dir / f"{stem}.{ext}"
                n = 2
                while dest.exists() or dest in self.claimed:
                    dest = self.out_dir / f"{stem} ({n}).{ext}"
                    n += 1
            self.claimed.add(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(dest))
        return dest.resolve()

    def _worker(self):
        while True:
            item = self.q.get()
            try:
                if item is None:
                    return
                if self.cancel.is_set():
                    item.status, item.error = "failed", "Download cancelled."
                else:
                    self._run(item)
            finally:
                self.q.task_done()

    # ── Live display ──

    def _render(self):
        from rich.console import Group
        from rich.progress_bar import ProgressBar
        from rich.spinner import Spinner
        from rich.table import Table
        from rich.text import Text

        with self.lock:
            items = [i for i in self.items if i.status != "expanded"]
        running = [i for i in items if i.status == "running"]
        queued = [i for i in items if i.status == "queued"]
        finished = [i for i in items if i.status in ("done", "failed")]
        if len(items) > 12:
            shown = set(map(id, running + queued[:2] + finished[-4:]))
            visible = [i for i in items if id(i) in shown]
        else:
            visible = items

        # Exact widths that always add up to the terminal, so Rich never has
        # to squeeze a column (it would drop the one-character status first).
        room = self.console.width - 2 - 1 - 18 - 3
        detail_w = max(12, min(44, room - 16))
        title_w = max(10, min(46, room - detail_w))
        grid = Table.grid(padding=(0, 1))
        grid.add_column(width=1, no_wrap=True)
        grid.add_column(width=title_w, no_wrap=True, overflow="ellipsis")
        grid.add_column(width=18, no_wrap=True)
        grid.add_column(width=detail_w, no_wrap=True, overflow="ellipsis")

        for i in visible:
            name = Text(i.name, overflow="ellipsis", no_wrap=True)
            if i.status == "queued":
                grid.add_row(Text("·", style="faint"), Text(i.name, style="faint"), "", Text("waiting", style="faint"))
            elif i.status == "running":
                if i.spinner is None:
                    i.spinner = Spinner("dots", style="brand")
                total = i.total
                downloading = i.stage == "downloading"
                if downloading and total:
                    pct = min(100.0, i.downloaded / total * 100)
                    bar = ProgressBar(total=100, completed=pct, width=18, complete_style="brand",
                                      finished_style="ok", style="faint")
                    parts = [f"{pct:3.0f}%", f"{fmt_size(i.downloaded)} / {fmt_size(total)}"]
                    if i.speed:
                        parts.append(f"{fmt_size(i.speed)}/s")
                    if i.eta:
                        parts.append(fmt_time(i.eta))
                    detail = Text("  ".join(parts))
                elif downloading:
                    bar = ProgressBar(total=None, width=18, pulse=True, complete_style="brand", pulse_style="brand",
                                      style="faint")
                    detail = Text(fmt_size(i.downloaded) if i.downloaded else "downloading")
                else:
                    bar = ProgressBar(total=None, width=18, pulse=True, complete_style="brand2", pulse_style="brand2",
                                      style="faint")
                    detail = Text(i.stage, style="brand2" if i.stage not in ("fetching info", "connecting") else "muted")
                grid.add_row(i.spinner, name, bar, detail)
            elif i.status == "done":
                bits = [b for b in (i.quality(), fmt_size(i.path.stat().st_size) if i.path and i.path.exists() else "") if b]
                grid.add_row(Text("✓", style="ok"), name, Text("saved", style="ok"), Text(" · ".join(bits), style="muted"))
            else:
                grid.add_row(Text("✗", style="err"), name, Text("failed", style="err"), Text(i.error, style="err"))

        n_done = sum(i.status == "done" for i in items)
        n_fail = sum(i.status == "failed" for i in items)
        speed = sum(i.speed or 0 for i in running)
        foot = [f"{n_done}/{len(items)} saved"]
        if n_fail:
            foot.append(f"[err]{n_fail} failed[/err]")
        hidden = len(items) - len(visible)
        if hidden:
            foot.append(f"{hidden} more not shown")
        if speed:
            foot.append(f"{fmt_size(speed)}/s")
        foot.append(fmt_time(time.time() - self.started))
        from rich.padding import Padding
        return Group(Padding(grid, (0, 0, 0, 2)), Text(""),
                     Text.from_markup("  [muted]" + "  ·  ".join(foot) + "[/muted]"))

    # ── Run ──

    def start(self):
        """Start downloading in the background and return at once. For apps
        that draw their own progress from self.items (the terminal app)."""
        self.silent = True
        for i in self.items:
            self.q.put(i)
        self._workers = [threading.Thread(target=self._worker, daemon=True) for _ in range(self.args.jobs)]
        for w in self._workers:
            w.start()

    def add(self, urls):
        """Queue more links on a downloader started with start()."""
        for u in urls:
            item = Item(u, thumbnail=bool(self.defaults["cover_art"]))
            with self.lock:
                self.items.append(item)
            self.q.put(item)

    def run(self) -> int:
        if self.console:
            self._header()
            from rich.live import Live
            self.live = Live(get_renderable=self._render, console=self.console,
                             refresh_per_second=10, transient=True)
            self.live.start()
        else:
            self._event(f"sdexe: {self._count_label()} as {self.spec.label} into {self.out_file or self.out_dir}")

        for i in self.items:
            self.q.put(i)
        workers = [threading.Thread(target=self._worker, daemon=True) for _ in range(self.args.jobs)]
        for w in workers:
            w.start()

        interrupted = False
        try:
            while self.q.unfinished_tasks:
                time.sleep(0.1)
        except KeyboardInterrupt:
            interrupted = True
            self.cancel.set()
            # Workers notice at their next progress tick; ffmpeg children got
            # the same SIGINT. Give them a moment, then clean up regardless.
            deadline = time.time() + 3
            while self.q.unfinished_tasks and time.time() < deadline:
                try:
                    time.sleep(0.1)
                except KeyboardInterrupt:
                    break
        finally:
            if self.live:
                self.live.stop()
                self.live = None
            for _ in workers:
                self.q.put(None)
            for tmp in list(self.tmp_dirs):
                shutil.rmtree(tmp, ignore_errors=True)

        items = [i for i in self.items if i.status != "expanded"]
        for i in items:
            if i.status in ("queued", "running"):
                i.status, i.error = "failed", "Download cancelled."

        if self.args.json:
            print(json.dumps(self._json(items), indent=2, ensure_ascii=False), flush=True)
        if self.console:
            self._summary(items, interrupted)
        else:
            ok = sum(i.status == "done" for i in items)
            self._event(f"done: {ok} saved, {len(items) - ok} failed in {fmt_time(time.time() - self.started)}")

        if interrupted:
            return 130
        return 0 if items and all(i.status == "done" for i in items) else 1

    def _count_label(self):
        n = len(self.items)
        return f"{n} link" if n == 1 else f"{n} links"

    def _where(self):
        target = self.out_file or self.out_dir
        try:
            rel = target.resolve().relative_to(Path.cwd().resolve())
            return f"./{rel}" if str(rel) != "." else "current folder"
        except ValueError:
            return str(target).replace(str(Path.home()), "~", 1)

    def _header(self):
        c = self.console
        clip = ""
        start, end = self.clip
        if start is not None or end is not None:
            clip = f"  [muted]·  clip[/muted] {fmt_time(start or 0)}–{fmt_time(end) if end else 'end'}"
        c.print()
        c.print(f"  [brand]↓[/brand] [title]{self._count_label()}[/title]  [muted]as[/muted] "
                f"{self.spec.label}{clip}  [muted]→[/muted] {_escape(self._where())}")
        for w in self.spec.warnings:
            c.print(f"  [warn]![/warn] [muted]{_escape(w)}[/muted]")
        c.print()

    def _summary(self, items, interrupted):
        c = self.console
        done = [i for i in items if i.status == "done"]
        failed = [i for i in items if i.status == "failed"]
        elapsed = fmt_time(time.time() - self.started)
        if done:
            noun = "file" if len(done) == 1 else "files"
            c.print(f"  [ok]✓[/ok] [title]Saved {len(done)} {noun}[/title] [muted]to[/muted] {_escape(self._where())} "
                    f"[muted]in {elapsed}[/muted]\n")
            for i in done:
                meta = " · ".join(b for b in (i.quality(), fmt_size(i.path.stat().st_size)) if b)
                c.print(f"    [link=file://{i.path}]{_escape(i.path.name)}[/link]  [muted]{meta}[/muted]",
                        overflow="ellipsis", no_wrap=True)
            c.print()
        if failed:
            noun = "link" if len(failed) == 1 else "links"
            c.print(f"  [err]✗[/err] [title]{len(failed)} {noun} failed[/title]\n")
            for i in failed:
                c.print(f"    {_escape(i.title or i.url)}", overflow="ellipsis", no_wrap=True)
                if i.title:
                    c.print(f"    [faint]{_escape(i.url)}[/faint]", overflow="ellipsis", no_wrap=True)
                c.print(f"    [err]{_escape(i.error)}[/err]\n")
        if interrupted:
            c.print("  [warn]![/warn] [title]Stopped.[/title] [muted]Unfinished downloads were discarded.[/muted]\n")

    def _json(self, items):
        results = []
        for i in items:
            r = {"url": i.url, "ok": i.status == "done", "title": i.title or None}
            if i.playlist:
                r["playlist"] = i.playlist
            if i.status == "done":
                info = i.info
                r.update({
                    "path": str(i.path),
                    "format": i.path.suffix.lstrip("."),
                    "size_bytes": i.path.stat().st_size,
                    "duration": info.get("duration"),
                    "id": info.get("id"),
                    "uploader": info.get("uploader") or info.get("channel"),
                    "source": info.get("extractor_key"),
                })
                if not self.spec.is_audio:
                    r.update({"width": info.get("width"), "height": info.get("height"), "fps": info.get("fps"),
                              "vcodec": info.get("vcodec"), "acodec": info.get("acodec")})
            else:
                r["error"] = i.error
            results.append(r)
        return {
            "ok": bool(items) and all(r["ok"] for r in results),
            "requested": {"format": self.spec.fmt, "quality": self.spec.label, "output": str(self.out_file or self.out_dir)},
            "saved": sum(r["ok"] for r in results),
            "failed": sum(not r["ok"] for r in results),
            "results": results,
            "warnings": self.spec.warnings,
        }


class _Fail(Exception):
    """A failure whose message is already fit to show."""


def _videos(n):
    return f"{n} video" if n == 1 else f"{n} videos"


def _escape(text):
    from rich.markup import escape
    return escape(str(text))


def youtube_warnings(urls):
    if not any(re.search(r"(youtube\.com|youtu\.be)/", u) for u in urls):
        return []
    if not any(cfg.get("path") for cfg in media.js_runtimes().values()):
        return [media.JS_RUNTIME_HINT]
    if not media.ejs_installed():
        return ["YouTube's challenge solver (yt-dlp-ejs) is missing. Run `sdexe update`."]
    return []


def _read_links(sources):
    links = []
    for src in sources:
        try:
            text = sys.stdin.read() if src == "-" else Path(src).expanduser().read_text()
        except OSError as e:
            raise UsageError(f"Can't read {src}: {e.strerror}.")
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                links.extend(line.split())
    return links


def collect_urls(args, prog):
    urls = []
    for tok in list(args.urls) + _read_links(args.input):
        url = normalize_url(tok)
        if not url:
            raise UsageError(f"'{tok}' is not a link or a known tag. Run `sdexe {prog} --help`.")
        urls.append(url)
    urls = list(dict.fromkeys(urls))
    if not urls:
        raise UsageError(f"No links given. Example: sdexe {prog} https://youtu.be/dQw4w9WgXcQ")
    if args.limit is not None:
        if args.limit < 1:
            raise UsageError("--limit must be 1 or more.")
        args.playlist = True
    return urls


def quiet_sdexe_logger():
    # _friendly_download_error logs the raw error; without a handler Python
    # would print it to stderr on top of our own message.
    logging.getLogger("sdexe").addHandler(logging.NullHandler())
    logging.getLogger("sdexe").propagate = False


def download_main(argv) -> int:
    quiet_sdexe_logger()

    try:
        args, tags = parse_args(argv)
        if args.help:
            print_help()
            return 0

        urls = collect_urls(args, "download")
        defaults = download_defaults()
        if args.jobs is None:
            args.jobs = defaults["jobs"]

        out_dir = Path(defaults["folder"]).expanduser() if defaults["folder"] else Path.cwd()
        out_file = None
        if args.output:
            out = Path(args.output).expanduser()
            if out.suffix.lstrip(".").lower() in MEDIA_EXTS and not out.is_dir():
                if len(urls) > 1:
                    raise UsageError(f"-o {out.name} names a single file, but {len(urls)} links were given. Pass a folder.")
                out_file = out.resolve()
            else:
                out_dir = out.resolve()
        spec = resolve_spec(tags, output_ext=out_file.suffix.lstrip(".").lower() if out_file else None,
                            defaults=defaults)

        start = parse_time(args.start) if args.start else None
        end = parse_time(args.end) if args.end else None
        if start is not None and end is not None and end <= start:
            raise UsageError("--end must be after --start.")
        if not 1 <= args.jobs <= 8:
            raise UsageError("--jobs must be between 1 and 8.")
    except UsageError as e:
        print(f"sdexe download: {e}", file=sys.stderr)
        return 2

    if not tools.ffmpeg_path():
        print("sdexe download: ffmpeg is required to merge and convert media. Install it "
              "(macOS: brew install ffmpeg) or run `sdexe` once, which offers to install it.", file=sys.stderr)
        return 1

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"sdexe download: can't create {out_dir}: {e.strerror}", file=sys.stderr)
        return 1

    spec.warnings += youtube_warnings(urls)
    dl = Downloader(urls, spec, args, out_dir, out_file, clip=(start, end), defaults=defaults)
    if not dl.console:
        for w in spec.warnings:
            print(f"warning: {w}", file=sys.stderr)
    return dl.run()
