"""Additional audio/video tool functions (second batch).

Pure functions built on ffmpeg. No Flask imports; the routes in
``sdexe.routes_av2`` call these. Everything works with a bare ffmpeg binary
(the bundled imageio-ffmpeg build has no ffprobe), falling back to parsing
``ffmpeg -i`` output where a probe is needed.
"""

import io
import re
import json
import math
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path
from contextlib import contextmanager

from PIL import Image

from sdexe import tools
from sdexe.tools import (
    FFmpegMissingError, AUDIO_CODEC_MAP, VIDEO_CODEC_MAP, _ffmpeg_exe, logger,
)


# ── Low-level helpers ──

@contextmanager
def _workdir():
    d = tempfile.mkdtemp(prefix="sdexe-av-")
    try:
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run an ffmpeg command line; raise a readable RuntimeError on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise FFmpegMissingError("ffmpeg is not installed")
    except subprocess.TimeoutExpired:
        raise RuntimeError("The media operation timed out.")
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        logger.error("ffmpeg failed: %s | stderr: %s", " ".join(cmd), stderr[-2000:])
        raise RuntimeError(tools._friendly_ffmpeg_error(stderr))
    return result


def ffprobe_path() -> str | None:
    """ffprobe next to the resolved ffmpeg, else one on PATH, else None."""
    exe = tools.ffmpeg_path()
    candidates = []
    if exe:
        sibling = Path(exe).with_name("ffprobe" + Path(exe).suffix)
        candidates.append(str(sibling))
    system = shutil.which("ffprobe")
    if system:
        candidates.append(system)
    for c in candidates:
        try:
            if Path(c).is_file() and subprocess.run([c, "-version"], capture_output=True, timeout=10).returncode == 0:
                return c
        except Exception:
            continue
    return None


def _color(value: str, default: str) -> str:
    """Validate a hex colour and return it in ffmpeg's 0xRRGGBB form."""
    v = (value or "").strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", v):
        v = default.lstrip("#")
    return "0x" + v.lower()


def _even(n: int) -> int:
    n = int(n)
    return n if n % 2 == 0 else n - 1


def _parse_resolution(value: str, default=(1280, 720)) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{2,5})\s*[xX]\s*(\d{2,5})\s*", value or "")
    if not m:
        return default
    return _even(int(m.group(1))), _even(int(m.group(2)))


def _audio_out(ext: str) -> tuple[str, list[str]]:
    """Output extension + codec args that keep the input container when we can."""
    ext = (ext or "").lower()
    if ext == "aac":
        ext = "m4a"
    if ext in AUDIO_CODEC_MAP:
        return ext, AUDIO_CODEC_MAP[ext]
    return "mp3", AUDIO_CODEC_MAP["mp3"]


def _video_out(ext: str) -> tuple[str, list[str]]:
    ext = (ext or "").lower()
    if ext in VIDEO_CODEC_MAP:
        return ext, VIDEO_CODEC_MAP[ext]
    return "mp4", VIDEO_CODEC_MAP["mp4"]


# ── Probing ──

def _parse_ffmpeg_i(stderr: str) -> dict:
    """Build a media-info dict from `ffmpeg -i` stderr (no ffprobe needed)."""
    info = {"container": None, "duration": 0.0, "bitrate": None, "streams": [],
            "tags": {}, "video": None, "audio": None}
    m = re.search(r"Input #0, ([^,\n]+(?:,[^,\n]+)*?), from", stderr)
    if m:
        info["container"] = m.group(1).strip()
    m = re.search(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)", stderr)
    if m:
        h, mi, s = m.groups()
        info["duration"] = int(h) * 3600 + int(mi) * 60 + float(s)
    m = re.search(r"Duration:.*?bitrate:\s*(\d+)\s*kb/s", stderr)
    if m:
        info["bitrate"] = int(m.group(1)) * 1000

    # Format-level tags: the Metadata block between "Input #0" and "Duration:".
    head = stderr.split("Duration:", 1)[0]
    meta = head.split("Metadata:", 1)[1] if "Metadata:" in head else ""
    for line in meta.splitlines():
        km = re.match(r"^\s{4}([A-Za-z0-9_\-/ ]+?)\s*:\s?(.*)$", line)
        if km:
            info["tags"][km.group(1).strip().lower()] = km.group(2).strip()

    for sm in re.finditer(r"Stream #0:(\d+)(?:\[[^\]]*\])?(?:\([^)]*\))?: (Video|Audio|Subtitle|Data|Attachment): (.*)", stderr):
        idx, kind, rest = int(sm.group(1)), sm.group(2).lower(), sm.group(3)
        parts = [p.strip() for p in rest.split(",")]
        codec_full = parts[0]
        codec = re.split(r"[\s(]", codec_full, 1)[0]
        st = {"index": idx, "type": kind, "codec": codec, "codec_long": codec_full}
        br = re.search(r"(\d+)\s*kb/s", rest)
        if br:
            st["bitrate"] = int(br.group(1)) * 1000
        if kind == "video":
            wh = re.search(r"(\d{2,5})x(\d{2,5})", rest)
            if wh:
                st["width"], st["height"] = int(wh.group(1)), int(wh.group(2))
            fps = re.search(r"([\d.]+)\s*fps", rest)
            if fps:
                st["fps"] = float(fps.group(1))
            else:
                tbr = re.search(r"([\d.]+k?)\s*tbr", rest)
                if tbr:
                    st["fps"] = float(tbr.group(1).replace("k", "e3"))
            if len(parts) > 1:
                st["pix_fmt"] = re.split(r"[\s(]", parts[1], 1)[0]
            st["attached_pic"] = "attached pic" in rest
        elif kind == "audio":
            sr = re.search(r"(\d+)\s*Hz", rest)
            if sr:
                st["sample_rate"] = int(sr.group(1))
            ch = re.search(r"Hz,\s*([^,]+)", rest)
            if ch:
                layout = ch.group(1).strip()
                st["channel_layout"] = layout
                st["channels"] = _channels_from_layout(layout)
        info["streams"].append(st)
    return info


def _channels_from_layout(layout: str) -> int | None:
    layout = layout.lower()
    if layout == "mono":
        return 1
    if layout == "stereo":
        return 2
    m = re.match(r"(\d+)\s*channels?", layout)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\.(\d+)", layout)
    if m:
        return int(m.group(1)) + int(m.group(2))
    return None


def _parse_ffprobe(js: dict) -> dict:
    fmt = js.get("format", {})
    info = {"container": fmt.get("format_name"),
            "duration": float(fmt.get("duration") or 0),
            "bitrate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
            "streams": [], "tags": {k.lower(): v for k, v in (fmt.get("tags") or {}).items()},
            "video": None, "audio": None}
    for s in js.get("streams", []):
        kind = s.get("codec_type", "")
        st = {"index": s.get("index"), "type": kind, "codec": s.get("codec_name"),
              "codec_long": s.get("codec_long_name")}
        if s.get("bit_rate"):
            st["bitrate"] = int(s["bit_rate"])
        if kind == "video":
            st["width"], st["height"] = s.get("width"), s.get("height")
            fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            try:
                num, den = fr.split("/")
                st["fps"] = round(float(num) / float(den), 3) if float(den) else None
            except Exception:
                st["fps"] = None
            st["pix_fmt"] = s.get("pix_fmt")
            st["attached_pic"] = bool((s.get("disposition") or {}).get("attached_pic"))
        elif kind == "audio":
            st["sample_rate"] = int(s["sample_rate"]) if s.get("sample_rate") else None
            st["channels"] = s.get("channels")
            st["channel_layout"] = s.get("channel_layout")
        info["streams"].append(st)
    return info


def media_info_path(path: str) -> dict:
    """Probe a file on disk. Uses ffprobe when present, else `ffmpeg -i`."""
    probe = ffprobe_path()
    info = None
    if probe:
        try:
            r = subprocess.run([probe, "-v", "quiet", "-print_format", "json",
                                "-show_format", "-show_streams", path],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and r.stdout.strip():
                info = _parse_ffprobe(json.loads(r.stdout))
        except Exception:
            info = None
    if info is None:
        exe = _ffmpeg_exe()
        r = subprocess.run([exe, "-hide_banner", "-i", path],
                           capture_output=True, text=True, timeout=60)
        stderr = r.stderr or ""
        if "Input #0" not in stderr:
            raise RuntimeError("Could not read this file. Is it a valid media file?")
        info = _parse_ffmpeg_i(stderr)
    info["video"] = next((s for s in info["streams"]
                          if s["type"] == "video" and not s.get("attached_pic")), None)
    info["audio"] = next((s for s in info["streams"] if s["type"] == "audio"), None)
    return info


def media_info(data: bytes, ext: str) -> dict:
    with _workdir() as wd:
        p = wd / f"in.{ext}"
        p.write_bytes(data)
        info = media_info_path(str(p))
        info["size"] = len(data)
        return info


# ── Audio tools ──

def remove_silence(data: bytes, ext: str, threshold_db: float = -40,
                   min_silence: float = 0.5) -> tuple[bytes, str]:
    """Strip leading, trailing and internal silence."""
    threshold_db = max(-90.0, min(0.0, float(threshold_db)))
    min_silence = max(0.05, min(30.0, float(min_silence)))
    out_ext, codec = _audio_out(ext)
    filt = (f"silenceremove=start_periods=1:start_duration=0:start_threshold={threshold_db}dB:"
            f"stop_periods=-1:stop_duration={min_silence}:stop_threshold={threshold_db}dB")
    out = tools.run_ffmpeg(data, f".{ext}", f".{out_ext}",
                           ["-map", "0:a", "-af", filt] + codec)
    return out, out_ext


def split_audio(data: bytes, ext: str, mode: str, value: float, base: str) -> bytes:
    """Cut audio into parts by duration or count; returns a ZIP."""
    with _workdir() as wd:
        src = wd / f"in.{ext}"
        src.write_bytes(data)
        duration = media_info_path(str(src))["duration"]
        if duration <= 0:
            raise ValueError("Could not determine the audio duration")
        if mode == "count":
            n = int(value)
            if n < 2:
                raise ValueError("Number of parts must be at least 2")
            seg = duration / n
        else:
            seg = float(value)
            if seg <= 0:
                raise ValueError("Part length must be greater than 0 seconds")
            n = max(1, math.ceil(duration / seg - 1e-6))
        if n > 500:
            raise ValueError("Too many parts (limit 500). Use a longer part length.")
        out_ext, codec = _audio_out(ext)
        exe = _ffmpeg_exe()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i in range(n):
                start = i * seg
                out = wd / f"part_{i:03d}.{out_ext}"
                cmd = [exe, "-y", "-ss", f"{start:.3f}", "-t", f"{seg:.3f}", "-i", str(src),
                       "-map", "0:a"] + codec + [str(out)]
                _run(cmd, timeout=300)
                zf.write(out, f"{base}_{i + 1:02d}.{out_ext}")
        return buf.getvalue()


def audio_channels(data: bytes, ext: str, mode: str) -> tuple[bytes, str]:
    out_ext, codec = _audio_out(ext)
    if mode == "mono":
        args = ["-ac", "1"]
    elif mode == "stereo":
        args = ["-ac", "2"]
    elif mode == "swap":
        args = ["-af", "pan=stereo|c0=c1|c1=c0"]
    elif mode == "left":
        args = ["-af", "pan=stereo|c0=c0|c1=c0"]
    elif mode == "right":
        args = ["-af", "pan=stereo|c0=c1|c1=c1"]
    else:
        raise ValueError("Unknown channel mode")
    out = tools.run_ffmpeg(data, f".{ext}", f".{out_ext}", ["-map", "0:a"] + args + codec)
    return out, out_ext


BITRATES = (64, 96, 128, 192, 256, 320)


def audio_bitrate(data: bytes, ext: str, bitrate: int, fmt: str = "keep") -> tuple[bytes, str]:
    if bitrate not in BITRATES:
        raise ValueError("Unsupported bitrate")
    ext = (ext or "").lower()
    if fmt == "keep":
        fmt = ext if ext in ("mp3", "m4a", "aac", "ogg") else "mp3"
    if fmt == "aac":
        fmt = "m4a"
    codecs = {"mp3": ["-codec:a", "libmp3lame"], "m4a": ["-codec:a", "aac"],
              "ogg": ["-codec:a", "libvorbis"]}
    if fmt not in codecs:
        raise ValueError("Unsupported output format")
    out = tools.run_ffmpeg(data, f".{ext}", f".{fmt}",
                           ["-map", "0:a"] + codecs[fmt] + ["-b:a", f"{bitrate}k"])
    return out, fmt


TAG_FIELDS = ("title", "artist", "album", "year", "genre", "track", "comment")


def read_tags(data: bytes, ext: str) -> dict:
    info = media_info(data, ext)
    tags = info.get("tags") or {}
    result = {k: "" for k in TAG_FIELDS}
    aliases = {"title": ("title",), "artist": ("artist", "album_artist", "author"),
               "album": ("album",), "year": ("date", "year", "tyer"),
               "genre": ("genre",), "track": ("track", "tracknumber"),
               "comment": ("comment", "description")}
    for field, keys in aliases.items():
        for k in keys:
            if tags.get(k):
                result[field] = str(tags[k])
                break
    result["has_cover"] = any(s["type"] == "video" for s in info["streams"])
    result["can_cover"] = ext.lower() in ("mp3", "m4a", "aac", "mp4")
    result["duration"] = info["duration"]
    return result


def write_tags(data: bytes, ext: str, fields: dict, cover: bytes | None = None) -> tuple[bytes, str]:
    """Rewrite metadata tags (and optionally cover art for mp3/m4a) without re-encoding."""
    ext = (ext or "").lower()
    out_ext = "m4a" if ext == "aac" else ext
    meta_args: list[str] = []
    for field in TAG_FIELDS:
        if field not in fields:
            continue
        key = "date" if field == "year" else field
        meta_args += ["-metadata", f"{key}={fields[field]}"]
    with _workdir() as wd:
        src = wd / f"in.{ext}"
        src.write_bytes(data)
        out = wd / f"out.{out_ext}"
        exe = _ffmpeg_exe()
        cmd = [exe, "-y", "-i", str(src)]
        if cover and out_ext in ("mp3", "m4a", "mp4"):
            # Normalise to a baseline JPEG so every player shows it.
            img = Image.open(io.BytesIO(cover))
            img = img.convert("RGB")
            img.thumbnail((1200, 1200))
            cov = wd / "cover.jpg"
            img.save(cov, "JPEG", quality=90)
            cmd += ["-i", str(cov), "-map", "0:a", "-map", "1:v", "-c", "copy",
                    "-disposition:v:0", "attached_pic"]
            if out_ext == "mp3":
                cmd += ["-id3v2_version", "3", "-metadata:s:v", "title=Album cover",
                        "-metadata:s:v", "comment=Cover (front)"]
        else:
            cmd += ["-map", "0", "-c", "copy"]
            if out_ext == "mp3":
                cmd += ["-id3v2_version", "3"]
        cmd += meta_args + [str(out)]
        _run(cmd, timeout=120)
        return out.read_bytes(), out_ext


def audio_to_video(data: bytes, ext: str, style: str = "waveform",
                   image: bytes | None = None, image_ext: str = "png",
                   color: str = "#4285f4", background: str = "#000000",
                   resolution: str = "1280x720") -> bytes:
    w, h = _parse_resolution(resolution)
    fg = _color(color, "#4285f4")
    bg = _color(background, "#000000")
    with _workdir() as wd:
        src = wd / f"in.{ext}"
        src.write_bytes(data)
        out = wd / "out.mp4"
        exe = _ffmpeg_exe()
        common = ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest"]
        if style == "image":
            if not image:
                raise ValueError("An image is required for the image style")
            img = wd / f"img.{image_ext}"
            img.write_bytes(image)
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1,format=yuv420p")
            cmd = [exe, "-y", "-loop", "1", "-framerate", "25", "-i", str(img),
                   "-i", str(src), "-map", "0:v", "-map", "1:a", "-vf", vf,
                   "-tune", "stillimage"] + common + [str(out)]
        else:
            if style == "spectrum":
                vis = (f"[0:a]showfreqs=s={w}x{h}:mode=bar:ascale=log:fscale=log:"
                       f"win_size=2048:colors={fg}[vis]")
            else:
                vis = f"[0:a]showwaves=s={w}x{h}:mode=cline:rate=25:colors={fg}[vis]"
            fc = (f"color=c={bg}:s={w}x{h}:r=25[bg];{vis};"
                  f"[bg][vis]overlay=format=auto:shortest=1,format=yuv420p[v]")
            cmd = [exe, "-y", "-i", str(src), "-filter_complex", fc,
                   "-map", "[v]", "-map", "0:a"] + common + [str(out)]
        _run(cmd, timeout=600)
        return out.read_bytes()


# ── Video tools ──

def merge_videos(files: list[tuple[str, bytes]], resolution: str = "auto") -> bytes:
    """Normalise clips to a common size/fps/audio layout and concatenate."""
    if len(files) < 2:
        raise ValueError("Need at least 2 video files")
    with _workdir() as wd:
        paths, infos = [], []
        for i, (ext, data) in enumerate(files):
            p = wd / f"in_{i}.{ext}"
            p.write_bytes(data)
            info = media_info_path(str(p))
            if not info["video"]:
                raise ValueError(f"File {i + 1} has no video stream")
            paths.append(p)
            infos.append(info)
        if resolution == "match-first":
            w, h = infos[0]["video"]["width"], infos[0]["video"]["height"]
        elif resolution == "auto":
            w = max(i["video"]["width"] for i in infos)
            h = max(i["video"]["height"] for i in infos)
        else:
            w, h = _parse_resolution(resolution)
        w, h = _even(w), _even(h)
        fps = infos[0]["video"].get("fps") or 30
        fps = min(max(float(fps), 1.0), 120.0)

        exe = _ffmpeg_exe()
        cmd = [exe, "-y"]
        fc, extra_inputs = [], 0
        for i, (p, info) in enumerate(zip(paths, infos)):
            cmd += ["-i", str(p)]
        concat_in = ""
        for i, info in enumerate(infos):
            fc.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                      f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},format=yuv420p[v{i}]")
            if info["audio"]:
                fc.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
            else:
                dur = info["duration"] or 1
                idx = len(paths) + extra_inputs
                extra_inputs += 1
                cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                fc.append(f"[{idx}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
            concat_in += f"[v{i}][a{i}]"
        fc.append(f"{concat_in}concat=n={len(infos)}:v=1:a=1[v][a]")
        out = wd / "out.mp4"
        cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
        _run(cmd, timeout=900)
        return out.read_bytes()


POSITIONS = {
    "top-left": "{m}:{m}",
    "top-right": "main_w-overlay_w-{m}:{m}",
    "bottom-left": "{m}:main_h-overlay_h-{m}",
    "bottom-right": "main_w-overlay_w-{m}:main_h-overlay_h-{m}",
    "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
}


def _overlay_xy(position: str, margin: int) -> str:
    if position not in POSITIONS:
        raise ValueError("Unknown position")
    return POSITIONS[position].format(m=int(margin))


def video_watermark(video: bytes, video_ext: str, image: bytes, image_ext: str,
                    position: str = "bottom-right", scale: float = 15,
                    opacity: float = 100, margin: int = 16) -> tuple[bytes, str]:
    scale = max(1.0, min(100.0, float(scale)))
    opacity = max(0.0, min(100.0, float(opacity))) / 100.0
    margin = max(0, min(2000, int(margin)))
    out_ext, vcodec = _video_out(video_ext)
    with _workdir() as wd:
        src = wd / f"in.{video_ext}"
        src.write_bytes(video)
        logo = wd / f"logo.{image_ext}"
        logo.write_bytes(image)
        info = media_info_path(str(src))
        if not info["video"]:
            raise ValueError("The file has no video stream")
        tw = max(2, _even(round(info["video"]["width"] * scale / 100)))
        fc = (f"[1:v]scale={tw}:-1,format=rgba,colorchannelmixer=aa={opacity:.3f}[wm];"
              f"[0:v][wm]overlay={_overlay_xy(position, margin)}:format=auto,format=yuv420p[v]")
        out = wd / f"out.{out_ext}"
        cmd = [_ffmpeg_exe(), "-y", "-i", str(src), "-i", str(logo),
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?"] + vcodec
        if out_ext in ("mp4", "mov"):
            cmd += ["-preset", "fast", "-crf", "20", "-movflags", "+faststart"]
        cmd.append(str(out))
        _run(cmd, timeout=900)
        return out.read_bytes(), out_ext


def extract_frames(data: bytes, ext: str, mode: str, base: str, time: float = 0,
                   interval: float = 1, count: int = 10, fmt: str = "png") -> tuple[bytes, str, str]:
    """Returns (bytes, filename, mimetype). Single → image, otherwise ZIP."""
    fmt = "jpg" if fmt in ("jpg", "jpeg") else "png"
    enc = ["-q:v", "2"] if fmt == "jpg" else []
    mime = "image/jpeg" if fmt == "jpg" else "image/png"
    with _workdir() as wd:
        src = wd / f"in.{ext}"
        src.write_bytes(data)
        exe = _ffmpeg_exe()
        if mode == "single":
            t = max(0.0, float(time))
            out = wd / f"frame.{fmt}"
            _run([exe, "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1"] + enc + [str(out)],
                 timeout=120)
            if not out.exists():
                raise RuntimeError("No frame at that time (past the end of the video?)")
            return out.read_bytes(), f"{base}_{t:g}s.{fmt}", mime

        duration = media_info_path(str(src))["duration"]
        if mode == "interval":
            interval = float(interval)
            if interval <= 0:
                raise ValueError("Interval must be greater than 0")
            if duration and duration / interval > 1000:
                raise ValueError("That would produce more than 1000 frames; use a longer interval.")
            pattern = wd / f"f_%04d.{fmt}"
            _run([exe, "-y", "-i", str(src), "-vf", f"fps=1/{interval}", "-vsync", "vfr"] + enc + [str(pattern)],
                 timeout=900)
            frames = sorted(wd.glob(f"f_*.{fmt}"))
            names = [f"{base}_{i * interval:g}s.{fmt}" for i in range(len(frames))]
        elif mode == "count":
            n = int(count)
            if n < 1 or n > 500:
                raise ValueError("Count must be between 1 and 500")
            if duration <= 0:
                raise ValueError("Could not determine the video duration")
            frames, names = [], []
            for i in range(n):
                t = (i + 0.5) * duration / n
                out = wd / f"f_{i:04d}.{fmt}"
                _run([exe, "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1"] + enc + [str(out)],
                     timeout=120)
                if out.exists():
                    frames.append(out)
                    names.append(f"{base}_{i + 1:03d}_{t:.2f}s.{fmt}")
        else:
            raise ValueError("Unknown mode")
        if not frames:
            raise RuntimeError("No frames were extracted")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, name in zip(frames, names):
                zf.write(p, name)
        return buf.getvalue(), f"{base}_frames.zip", "application/zip"


def _atempo_chain(speed: float) -> str:
    parts = []
    while speed > 2.0:
        parts.append("atempo=2.0")
        speed /= 2.0
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed /= 0.5
    parts.append(f"atempo={speed:.4f}")
    return ",".join(parts)


def video_speed(data: bytes, ext: str, speed: float, keep_pitch: bool = True) -> tuple[bytes, str]:
    speed = float(speed)
    if speed < 0.25 or speed > 4.0:
        raise ValueError("Speed must be between 0.25 and 4")
    out_ext, vcodec = _video_out(ext)
    with _workdir() as wd:
        src = wd / f"in.{ext}"
        src.write_bytes(data)
        info = media_info_path(str(src))
        if not info["video"]:
            raise ValueError("The file has no video stream")
        fc = [f"[0:v]setpts=PTS/{speed:.4f}[v]"]
        maps = ["-map", "[v]"]
        if info["audio"]:
            if keep_pitch:
                fc.append(f"[0:a]{_atempo_chain(speed)}[a]")
            else:
                sr = info["audio"].get("sample_rate") or 44100
                fc.append(f"[0:a]asetrate={sr}*{speed:.4f},aresample={sr}[a]")
            maps += ["-map", "[a]"]
        out = wd / f"out.{out_ext}"
        cmd = [_ffmpeg_exe(), "-y", "-i", str(src), "-filter_complex", ";".join(fc)] + maps + vcodec
        if out_ext in ("mp4", "mov"):
            cmd += ["-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        cmd.append(str(out))
        _run(cmd, timeout=900)
        return out.read_bytes(), out_ext


def stabilize_video(data: bytes, ext: str, strength: str = "medium") -> tuple[bytes, str]:
    r = {"low": 16, "medium": 32, "high": 64}.get(strength)
    if r is None:
        raise ValueError("Unknown strength")
    out_ext, vcodec = _video_out(ext)
    args = ["-vf", f"deshake=rx={r}:ry={r}:edge=mirror:blocksize=8:contrast=125", "-map", "0:v",
            "-map", "0:a?"] + vcodec
    if out_ext in ("mp4", "mov"):
        args += ["-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    return tools.run_ffmpeg(data, f".{ext}", f".{out_ext}", args, timeout=900), out_ext


def gif_to_video(data: bytes, fmt: str = "mp4", loop_count: int = 1) -> bytes:
    if fmt not in ("mp4", "webm"):
        raise ValueError("Unsupported format")
    loop_count = max(1, min(100, int(loop_count)))
    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,format=yuv420p"
    if fmt == "mp4":
        args = ["-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    else:
        args = ["-vf", vf, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p"]
    pre = ["-stream_loop", str(loop_count - 1)]
    return tools.run_ffmpeg(data, ".gif", f".{fmt}", args, timeout=600, pre_input_args=pre)


def picture_in_picture(main: bytes, main_ext: str, overlay: bytes, overlay_ext: str,
                       position: str = "bottom-right", scale: float = 25,
                       margin: int = 16) -> bytes:
    scale = max(5.0, min(100.0, float(scale)))
    margin = max(0, min(2000, int(margin)))
    if position == "center":
        raise ValueError("Unknown position")
    with _workdir() as wd:
        src = wd / f"main.{main_ext}"
        src.write_bytes(main)
        ov = wd / f"overlay.{overlay_ext}"
        ov.write_bytes(overlay)
        info = media_info_path(str(src))
        if not info["video"]:
            raise ValueError("The main file has no video stream")
        tw = max(2, _even(round(info["video"]["width"] * scale / 100)))
        fc = (f"[1:v]scale={tw}:-2,setsar=1[pip];"
              f"[0:v][pip]overlay={_overlay_xy(position, margin)}:shortest=0:eof_action=pass,"
              f"format=yuv420p[v]")
        out = wd / "out.mp4"
        cmd = [_ffmpeg_exe(), "-y", "-i", str(src), "-i", str(ov),
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac",
               "-movflags", "+faststart", str(out)]
        _run(cmd, timeout=900)
        return out.read_bytes()
