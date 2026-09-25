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

from sdexe import media, tools
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


def resolve_spec(tags, output_ext=None) -> Spec:
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
        fmt = "wav" if kind == "audio" else "mp4"

    spec = Spec(fmt=fmt)
    q = qualities[0] if qualities else {}
    if spec.is_audio:
        if q.get("height"):
            spec.warnings.append(f"{q['label']} is a video quality, ignored for {fmt}.")
        if fmt == "mp3":
            spec.bitrate = q.get("bitrate") or "320"
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
            spec.height, spec.fps = 1080, 60
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


def normalize_url(token: str) -> str | None:
    if re.match(r"https?://", token, re.I):
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
    p.add_argument("-j", "--jobs", type=int, default=3)
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--cookies-from-browser", metavar="BROWSER")
    return p


def parse_args(argv):
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
                hint = f" Did you mean -{guess[0]}?" if guess else " Run `sdexe download --help` for options."
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
[bold]sdexe download[/bold] [dim]· save video or audio from a link, straight to disk[/dim]

[bold]Usage[/bold]
  sdexe download [cyan]<url>[/cyan] [cyan]\\[url ...][/cyan] [green]\\[format][/green] [green]\\[quality][/green] \\[options]

  With no tags you get [bold]MP4 video, up to 1080p60[/bold]. Audio only defaults to [bold]WAV[/bold] (lossless).
  Tags can be written as -mp3, --mp3, mp3, -f mp3; quality as -720p, 720p, -q 720p.

[bold]Formats[/bold]
  [green]video[/green]   mp4 [dim](default)[/dim], webm, mkv
  [green]audio[/green]   wav [dim](default for -a)[/dim], mp3, flac, m4a, opus
  [green]-a[/green], [green]--audio[/green]   audio only, as WAV unless a format is given

[bold]Quality[/bold]
  [green]video[/green]   2160p/4k, 1440p, 1080p, 720p, 480p, 360p  [dim]add fps: 1080p30, 720p60[/dim]
          [dim]default 1080p60: the best stream at or under 1080p, 60fps preferred,
          stepping down when a video doesn't offer that[/dim]
  [green]best[/green]    highest available: no resolution cap (4K/8K if offered), top fps and bitrate
  [green]mp3[/green]     128, 192, 256, 320 [dim](default 320 kbps)[/dim]

[bold]Options[/bold]
  -o, --output PATH          folder to save into (default: current folder), or a
                             file name like clip.mp4 when downloading one link
  -i, --input FILE           read links from a file, one per line ([dim]-[/dim] for stdin)
  --playlist                 download every video in a playlist or channel link
  --limit N                  only the first N videos of a playlist (implies --playlist)
  --start TIME, --end TIME   keep only part of the video: 90, 1:30, 1:02:03, 1m30s
  -j, --jobs N               downloads at once (default 3)
  --cookies-from-browser B   use your browser's login: chrome, safari, firefox, brave, edge
  --json                     print one JSON result document on stdout
  --quiet                    no progress output, errors only
  -v, --verbose              show yt-dlp's own log

[bold]Output[/bold]
  Saved file paths are printed to stdout, one per line, as each finishes; progress
  and errors go to stderr. Exit code 0 when everything saved, 1 if any link failed.

[bold]Examples[/bold]
  sdexe download https://youtu.be/dQw4w9WgXcQ
  sdexe download https://youtu.be/dQw4w9WgXcQ -mp3
  sdexe download https://youtu.be/dQw4w9WgXcQ -720p -o ~/Movies
  sdexe download https://youtu.be/dQw4w9WgXcQ --best
  sdexe download URL1 URL2 URL3 -a
  sdexe download URL --start 1:30 --end 2:00 -o clip.mp4
  sdexe download "https://youtube.com/playlist?list=..." --playlist -mp3
  sdexe download URL --json
"""


def print_help(file=None):
    from rich.console import Console
    Console(file=file or sys.stdout, highlight=False).print(HELP, soft_wrap=True)


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
ATTEMPTS = 3
_RETRYABLE = re.compile(r"ffmpeg exited|http error 403|http error 5\d\d|timed out|timeout|"
                        r"connection|incomplete|unable to download|fragment", re.I)


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


class Downloader:
    def __init__(self, urls, spec, args, out_dir, out_file=None, clip=(None, None)):
        self.items = [Item(u) for u in urls]
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
        if self.stderr_tty and not args.quiet:
            from rich.console import Console
            self.console = Console(stderr=True, highlight=False)

    # stderr events, for when there is no live display
    def _event(self, text, error=False):
        if self.live:
            return
        if self.args.quiet and not error:
            return
        if self.args.json and not self.stderr_tty and not error:
            return
        print(text, file=sys.stderr, flush=True)

    def _log(self, msg):
        if self.live:
            self.live.console.print(f"[dim]{_escape(msg)}[/dim]")
        else:
            print(msg, file=sys.stderr, flush=True)

    def _ydl_opts(self, item, tmp):
        opts = media.build_ydl_opts(
            self.spec.fmt,
            height=self.spec.height,
            fps=self.spec.fps,
            bitrate=self.spec.bitrate,
            prefer_fps=True,
            embed_metadata=True,
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

        opts.update({
            "outtmpl": str(tmp / "%(id).60s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [pp_hook],
            "quiet": True,
            "no_warnings": not self.args.verbose,
            "noprogress": True,
            "logger": _YtdlpLog(self._log if self.args.verbose else None),
            "noplaylist": not self.args.playlist,
            "extract_flat": "in_playlist",
            "concurrent_fragment_downloads": 4,
            "retries": 5,
            "fragment_retries": 5,
        })
        if self.args.limit:
            opts["playlistend"] = self.args.limit  # don't page through a whole channel
        ffmpeg = tools.ffmpeg_path()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        if self.args.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.args.cookies_from_browser.lower(), None, None, None)
        return opts

    def _expand(self, item, info):
        entries = [e for e in (info.get("entries") or []) if e]
        title = info.get("title") or "playlist"
        if self.args.playlist and self.args.limit:
            entries = entries[:self.args.limit]
        if not self.args.playlist:
            raise _Fail(f"This link is a playlist ({_videos(len(entries))}). Add --playlist to download all of them.")
        if self.out_file:
            raise _Fail(f"-o {self.out_file.name} names a single file, but this playlist has {_videos(len(entries))}. "
                        "Pass a folder instead.")
        if not entries:
            raise _Fail("This playlist is empty.")
        children = []
        for e in entries:
            url = e.get("url") or e.get("webpage_url")
            if not url:
                continue
            children.append(Item(url, entry=e, playlist=title, title=e.get("title") or ""))
        with self.lock:
            idx = self.items.index(item)
            self.items[idx:idx + 1] = [item] + children
            item.status = "expanded"
            item.title = title
        for c in children:
            self.q.put(c)
        self._event(f"playlist: {title} ({_videos(len(children))})")

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
                if item.thumbnail and "unable to embed" in raw.lower() and attempt < ATTEMPTS:
                    # Cover art is a nicety; never lose the download over it.
                    item.thumbnail = False
                    item.stage = "retrying without cover art"
                    item.streams.clear()
                    continue
                if attempt < ATTEMPTS and not self.cancel.is_set() and _RETRYABLE.search(raw):
                    # A fresh extraction gets fresh stream URLs, which is what
                    # clears YouTube's intermittent 403s and ffmpeg HLS drops.
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
            if not self.stdout_tty and not self.args.json:
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

        width = self.console.width
        title_w = max(16, min(46, width - 52))
        grid = Table.grid(padding=(0, 1))
        grid.add_column(width=1)
        grid.add_column(width=title_w, no_wrap=True, overflow="ellipsis")
        grid.add_column(width=18)
        grid.add_column(no_wrap=True, overflow="ellipsis")

        for i in visible:
            name = Text(i.name, overflow="ellipsis", no_wrap=True)
            if i.status == "queued":
                grid.add_row(Text("·", style="dim"), Text(i.name, style="dim"), "", Text("waiting", style="dim"))
            elif i.status == "running":
                if i.spinner is None:
                    i.spinner = Spinner("dots", style="cyan")
                total = i.total
                downloading = i.stage == "downloading"
                if downloading and total:
                    pct = min(100.0, i.downloaded / total * 100)
                    bar = ProgressBar(total=100, completed=pct, width=18, complete_style="cyan")
                    parts = [f"{pct:3.0f}%", f"{fmt_size(i.downloaded)} / {fmt_size(total)}"]
                    if i.speed:
                        parts.append(f"{fmt_size(i.speed)}/s")
                    if i.eta:
                        parts.append(fmt_time(i.eta))
                    detail = Text("  ".join(parts))
                elif downloading:
                    bar = ProgressBar(total=None, width=18, pulse=True, complete_style="cyan")
                    detail = Text(fmt_size(i.downloaded) if i.downloaded else "downloading")
                else:
                    bar = ProgressBar(total=None, width=18, pulse=True, complete_style="magenta")
                    detail = Text(i.stage, style="magenta" if i.stage not in ("fetching info", "connecting") else "dim")
                grid.add_row(i.spinner, name, bar, detail)
            elif i.status == "done":
                bits = [b for b in (i.quality(), fmt_size(i.path.stat().st_size) if i.path and i.path.exists() else "") if b]
                grid.add_row(Text("✓", style="green"), name, Text("saved", style="green"), Text(" · ".join(bits), style="dim"))
            else:
                grid.add_row(Text("✗", style="red"), name, Text("failed", style="red"), Text(i.error, style="red"))

        n_done = sum(i.status == "done" for i in items)
        n_fail = sum(i.status == "failed" for i in items)
        speed = sum(i.speed or 0 for i in running)
        foot = [f"{n_done}/{len(items)} saved"]
        if n_fail:
            foot.append(f"[red]{n_fail} failed[/red]")
        hidden = len(items) - len(visible)
        if hidden:
            foot.append(f"{hidden} more not shown")
        if speed:
            foot.append(f"{fmt_size(speed)}/s")
        foot.append(fmt_time(time.time() - self.started))
        return Group(grid, Text.from_markup("  [dim]" + "  ·  ".join(foot) + "[/dim]"))

    # ── Run ──

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
            clip = f"  [dim]clip[/dim] {fmt_time(start or 0)}–{fmt_time(end) if end else 'end'}"
        c.print(f"\n [bold]sdexe[/bold] [dim]download[/dim]  {self._count_label()}  [dim]as[/dim] "
                f"[cyan]{self.spec.label}[/cyan]{clip}  [dim]→[/dim] {self._where()}")
        for w in self.spec.warnings:
            c.print(f" [yellow]![/yellow] {w}")
        c.print()

    def _summary(self, items, interrupted):
        c = self.console
        done = [i for i in items if i.status == "done"]
        failed = [i for i in items if i.status == "failed"]
        elapsed = fmt_time(time.time() - self.started)
        if done:
            noun = "file" if len(done) == 1 else "files"
            c.print(f" [green]✓[/green] Saved {len(done)} {noun} to {self._where()} [dim]in {elapsed}[/dim]\n")
            for i in done:
                meta = " · ".join(b for b in (i.quality(), fmt_size(i.path.stat().st_size)) if b)
                c.print(f"   [link=file://{i.path}]{_escape(i.path.name)}[/link]  [dim]{meta}[/dim]",
                        overflow="ellipsis", no_wrap=True)
            c.print()
        if failed:
            noun = "link" if len(failed) == 1 else "links"
            c.print(f" [red]✗[/red] {len(failed)} {noun} failed\n")
            for i in failed:
                c.print(f"   {_escape(i.title or i.url)}", overflow="ellipsis", no_wrap=True)
                if i.title:
                    c.print(f"   [dim]{_escape(i.url)}[/dim]", overflow="ellipsis", no_wrap=True)
                c.print(f"   [red]{_escape(i.error)}[/red]\n")
        if interrupted:
            c.print(" [yellow]Stopped.[/yellow] Unfinished downloads were discarded.\n")

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


def download_main(argv) -> int:
    # _friendly_download_error logs the raw error; without a handler Python
    # would print it to stderr on top of our own message.
    logging.getLogger("sdexe").addHandler(logging.NullHandler())
    logging.getLogger("sdexe").propagate = False

    try:
        args, tags = parse_args(argv)
        if args.help:
            print_help()
            return 0

        raw = list(args.urls) + _read_links(args.input)
        urls = []
        for tok in raw:
            url = normalize_url(tok)
            if not url:
                raise UsageError(f"'{tok}' is not a link or a known tag. Run `sdexe download --help`.")
            urls.append(url)
        urls = list(dict.fromkeys(urls))
        if not urls:
            raise UsageError("No links given. Example: sdexe download https://youtu.be/dQw4w9WgXcQ")

        out_dir, out_file = Path.cwd(), None
        if args.output:
            out = Path(args.output).expanduser()
            if out.suffix.lstrip(".").lower() in MEDIA_EXTS and not out.is_dir():
                if len(urls) > 1:
                    raise UsageError(f"-o {out.name} names a single file, but {len(urls)} links were given. Pass a folder.")
                out_file = out.resolve()
            else:
                out_dir = out.resolve()
        spec = resolve_spec(tags, output_ext=out_file.suffix.lstrip(".").lower() if out_file else None)

        start = parse_time(args.start) if args.start else None
        end = parse_time(args.end) if args.end else None
        if start is not None and end is not None and end <= start:
            raise UsageError("--end must be after --start.")
        if args.limit is not None:
            if args.limit < 1:
                raise UsageError("--limit must be 1 or more.")
            args.playlist = True
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

    dl = Downloader(urls, spec, args, out_dir, out_file, clip=(start, end))
    if not dl.console:
        for w in spec.warnings:
            print(f"warning: {w}", file=sys.stderr)
    return dl.run()
