"""yt-dlp option building shared by the web downloader and `sdexe download`.

No Flask imports. Callers add their own hooks, output template, and logging.
"""

import functools
import glob
import os
import re
import shutil
import subprocess

VIDEO_FORMATS = ("mp4", "webm", "mkv")
AUDIO_FORMATS = ("wav", "mp3", "flac", "m4a", "opus")
MP3_BITRATES = ("128", "192", "256", "320")

# Containers yt-dlp's EmbedThumbnail can write cover art into. flac, opus and
# m4a need mutagen (ffmpeg's fallback fails on audio-only m4a), which is
# optional, so they are checked at runtime.
_THUMB_FFMPEG = {"mp4", "mkv", "mp3"}
_THUMB_MUTAGEN = {"flac", "opus", "m4a"}


def _can_embed_thumbnail(ext: str) -> bool:
    if ext in _THUMB_FFMPEG:
        return True
    if ext in _THUMB_MUTAGEN:
        try:
            import mutagen  # noqa: F401
            return True
        except ImportError:
            return False
    return False


def build_ydl_opts(
    fmt: str,
    *,
    height: int | None = None,
    fps: int | None = None,
    bitrate: str | None = None,
    prefer_fps: bool = False,
    subtitles: bool = False,
    embed_metadata: bool = False,
    force_container: bool = False,
    thumbnail: bool = True,
) -> dict:
    """yt-dlp options for one output format.

    fmt: a VIDEO_FORMATS or AUDIO_FORMATS name.
    height: upper bound for video resolution. None means no cap.
    fps: preferred frame rate. Resolution wins over it: a video offered only
        at 720p60 still comes down at 720p for a 720p30 request.
    bitrate: mp3 kbps ("128".."320"). Defaults to 320.
    prefer_fps: rank frame rate above bitrate, so 1080p60 beats 1080p30.
    embed_metadata: write title/artist/date/description tags via ffmpeg.
    force_container: remux a single-file download that arrived in another
        container, so an mp4 request always ends in .mp4.
    """
    postprocessors = []
    opts: dict = {}

    if fmt in VIDEO_FORMATS:
        filt = f"[height<={height}]" if height else ""
        if fmt == "webm":
            # Prefer native VP9/AV1 + Opus streams, which mux into WebM with no
            # re-encode. Anything else falls back to MKV rather than failing.
            format_str = (f"bestvideo[ext=webm]{filt}+bestaudio[ext=webm]/"
                          f"bestvideo{filt}+bestaudio/best{filt}/best")
            merge = "webm/mkv"
        else:
            # Codec-agnostic: take the highest-bitrate stream at/under the chosen
            # resolution (H.264 / VP9 / AV1). An [ext=mp4] filter makes yt-dlp
            # fall back to a low-bitrate stream (or a 360p progressive file)
            # when an mp4-codec 1080p isn't offered.
            format_str = f"bestvideo{filt}+bestaudio/best{filt}/best" if filt else "bestvideo+bestaudio/best"
            merge = fmt

        if force_container and fmt != "webm":
            postprocessors.append({"key": "FFmpegVideoRemuxer", "preferedformat": fmt})
        if subtitles:
            postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
            opts.update({"writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["en"]})
        if embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
        if thumbnail and _can_embed_thumbnail(fmt):
            postprocessors.append({"key": "EmbedThumbnail"})

        fps_key = f"fps:{fps}" if fps else "fps"
        opts.update({
            "format": format_str,
            # Prefer resolution, then raw bitrate, over yt-dlp's default codec-
            # efficiency ranking, so we get the best-looking stream, not the
            # smallest one.
            "format_sort": ["res", fps_key, "br"] if prefer_fps or fps else ["res", "br"],
            "merge_output_format": merge,
        })

    elif fmt in AUDIO_FORMATS:
        # Pick a source already in the target codec so m4a/opus are a remux,
        # not a lossy-to-lossy re-encode.
        source = {
            "m4a": "bestaudio[ext=m4a]/bestaudio/best",
            "opus": "bestaudio[acodec=opus]/bestaudio/best",
        }.get(fmt, "bestaudio/best")
        extract = {"key": "FFmpegExtractAudio", "preferredcodec": fmt}
        if fmt == "mp3":
            extract["preferredquality"] = bitrate if bitrate in MP3_BITRATES else "320"
        postprocessors.append(extract)
        if embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        if thumbnail and _can_embed_thumbnail(fmt):
            postprocessors.append({"key": "EmbedThumbnail"})
        opts["format"] = source

    else:
        raise ValueError(f"Unknown format: {fmt}")

    if any(pp["key"] == "EmbedThumbnail" for pp in postprocessors):
        opts["writethumbnail"] = True
    opts["postprocessors"] = postprocessors
    return opts


def apply_clip(opts: dict, start: float | None, end: float | None) -> None:
    """Limit a download to [start, end] seconds. Cuts are re-encoded at the
    boundaries so they land on the exact frame."""
    if start is None and end is None:
        return
    from yt_dlp.utils import download_range_func
    opts["download_ranges"] = download_range_func(None, [(start or 0, end or float("inf"))])
    opts["force_keyframes_at_cuts"] = True


# ── Retries ──
# YouTube intermittently refuses a stream URL (403) or drops an HLS fragment,
# which surfaces as "ffmpeg exited with code 8" on clips. A fresh extraction
# gets fresh URLs and almost always succeeds.
ATTEMPTS = 3
_RETRYABLE = re.compile(r"ffmpeg exited|http error 403|http error 5\d\d|timed out|timeout|"
                        r"connection|incomplete|unable to download|fragment", re.I)


def is_retryable(message: str) -> bool:
    return bool(_RETRYABLE.search(message or ""))


def is_thumbnail_failure(message: str) -> bool:
    """Cover-art embedding failed. Worth retrying without it: the art is a
    nicety, the download is not."""
    return "unable to embed" in (message or "").lower()


def without_thumbnail(opts: dict) -> dict:
    opts["postprocessors"] = [pp for pp in opts.get("postprocessors", []) if pp["key"] != "EmbedThumbnail"]
    return opts


# ── JavaScript runtime ──
# YouTube hides formats (and is moving to refuse downloads) unless yt-dlp can
# solve its JS challenges, which needs the yt-dlp-ejs scripts plus a runtime.
# yt-dlp only tries deno, and only on PATH, which a tray or Finder launch
# barely has. Offer every supported runtime at its resolved path instead.
_JS_RUNTIMES = (("deno", "deno"), ("node", "node"), ("bun", "bun"), ("quickjs", "qjs"))
_JS_DIRS = ("~/.deno/bin", "~/.bun/bin", "~/.volta/bin", "~/.local/node/bin", "~/.local/bin",
            "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


def _find_exe(exe: str) -> str | None:
    found = shutil.which(exe)
    if found:
        return found
    dirs = [os.path.expanduser(d) for d in _JS_DIRS]
    # nvm keeps each Node version in its own folder; newest last.
    if exe == "node":
        dirs += sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin")),
                       key=lambda d: [int(x) for x in re.findall(r"\d+", d)])[::-1]
    for d in dirs:
        path = os.path.join(d, exe)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


@functools.lru_cache(maxsize=1)
def js_runtimes() -> dict:
    """yt-dlp's js_runtimes option: every installed runtime, with its path.
    yt-dlp skips any that are too old."""
    found = {}
    for name, exe in _JS_RUNTIMES:
        path = _find_exe(exe)
        if path:
            found[name] = {"path": path}
    return found or {"deno": {}}


def ejs_installed() -> bool:
    try:
        import yt_dlp_ejs  # noqa: F401
        return True
    except ImportError:
        return False


@functools.lru_cache(maxsize=1)
def js_runtime_label() -> str | None:
    """"node 24.2.0" for the first runtime found, or None."""
    for name, cfg in js_runtimes().items():
        path = cfg.get("path")
        if not path:
            continue
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5).stdout
        except Exception:
            continue
        m = re.search(r"\d+(\.\d+)+", out)
        return f"{name} {m.group(0)}" if m else name
    return None


JS_RUNTIME_HINT = ("No JavaScript runtime found, so YouTube may hide some formats. "
                   "Install one (macOS: brew install deno) and sdexe will use it.")
