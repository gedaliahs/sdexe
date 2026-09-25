"""Flask blueprint for the second batch of AV tools (/api/av/...).

Registered by app.py via ``app.register_blueprint(av2_bp)``.
"""

import io

from flask import Blueprint, request, jsonify, send_file

from sdexe import tools
from sdexe import tools_av2 as av2

av2_bp = Blueprint("av2", __name__, url_prefix="/api/av")


def _ffmpeg_missing_response():
    return jsonify({
        "error": "ffmpeg is required for this tool but isn't available.",
        "code": "ffmpeg_missing",
    }), 503


def _error(e: Exception):
    if isinstance(e, tools.FFmpegMissingError):
        return _ffmpeg_missing_response()
    if isinstance(e, ValueError):
        return jsonify({"error": str(e)[-500:]}), 400
    return jsonify({"error": str(e)[-500:]}), 500


def _send(data: bytes, name: str, mimetype: str | None = None):
    return send_file(io.BytesIO(data), as_attachment=True, download_name=name,
                     mimetype=mimetype)


def _form_float(key: str, default: float) -> float:
    try:
        return float(request.form.get(key, default))
    except (TypeError, ValueError):
        raise ValueError(f"Invalid value for {key}")


def _form_int(key: str, default: int) -> int:
    try:
        return int(float(request.form.get(key, default)))
    except (TypeError, ValueError):
        raise ValueError(f"Invalid value for {key}")


def _names(f, default_ext: str, default_base: str):
    return (tools._ext_from_filename(f.filename, default_ext),
            tools._base_from_filename(f.filename, default_base))


# ── Audio ──

@av2_bp.route("/remove-silence", methods=["POST"])
def av_remove_silence():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, base = _names(f, "mp3", "audio")
    try:
        threshold = _form_float("threshold_db", -40)
        min_silence = _form_float("min_silence", 0.5)
        out, out_ext = av2.remove_silence(f.stream.read(), ext, threshold, min_silence)
        return _send(out, f"{base}_nosilence.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/split-audio", methods=["POST"])
def av_split_audio():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, base = _names(f, "mp3", "audio")
    mode = request.form.get("mode", "duration")
    if mode not in ("duration", "count"):
        return jsonify({"error": "Mode must be duration or count"}), 400
    try:
        value = _form_float("value", 60)
        out = av2.split_audio(f.stream.read(), ext, mode, value, base)
        return _send(out, f"{base}_parts.zip", "application/zip")
    except Exception as e:
        return _error(e)


@av2_bp.route("/channels", methods=["POST"])
def av_channels():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, base = _names(f, "mp3", "audio")
    mode = request.form.get("mode", "mono")
    try:
        out, out_ext = av2.audio_channels(f.stream.read(), ext, mode)
        return _send(out, f"{base}_{mode}.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/bitrate", methods=["POST"])
def av_bitrate():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, base = _names(f, "mp3", "audio")
    fmt = request.form.get("format", "keep").lower()
    try:
        bitrate = _form_int("bitrate", 128)
        out, out_ext = av2.audio_bitrate(f.stream.read(), ext, bitrate, fmt)
        return _send(out, f"{base}_{bitrate}k.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/tags/read", methods=["POST"])
def av_tags_read():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, _ = _names(f, "mp3", "audio")
    try:
        return jsonify(av2.read_tags(f.stream.read(), ext))
    except Exception as e:
        return _error(e)


@av2_bp.route("/tags/write", methods=["POST"])
def av_tags_write():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, base = _names(f, "mp3", "audio")
    fields = {k: request.form.get(k, "").strip()[:1000] for k in av2.TAG_FIELDS if k in request.form}
    cover = request.files.get("cover")
    cover_data = cover.stream.read() if cover and cover.filename else None
    try:
        out, out_ext = av2.write_tags(f.stream.read(), ext, fields, cover_data)
        return _send(out, f"{base}_tagged.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/audio-to-video", methods=["POST"])
def av_audio_to_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No audio file provided"}), 400
    ext, base = _names(f, "mp3", "audio")
    style = request.form.get("style", "waveform")
    if style not in ("waveform", "spectrum", "image"):
        return jsonify({"error": "Unknown style"}), 400
    image = request.files.get("image")
    image_data = image.stream.read() if image and image.filename else None
    image_ext = tools._ext_from_filename(image.filename, "png") if image and image.filename else "png"
    try:
        out = av2.audio_to_video(
            f.stream.read(), ext, style, image_data, image_ext,
            request.form.get("color", "#4285f4"), request.form.get("background", "#000000"),
            request.form.get("resolution", "1280x720"))
        return _send(out, f"{base}_video.mp4", "video/mp4")
    except Exception as e:
        return _error(e)


# ── Video ──

@av2_bp.route("/merge-video", methods=["POST"])
def av_merge_video():
    files = request.files.getlist("files")
    if len(files) < 2:
        return jsonify({"error": "Need at least 2 video files"}), 400
    resolution = request.form.get("resolution", "auto")
    try:
        data = [(tools._ext_from_filename(f.filename, "mp4"), f.stream.read()) for f in files]
        out = av2.merge_videos(data, resolution)
        return _send(out, "merged.mp4", "video/mp4")
    except Exception as e:
        return _error(e)


@av2_bp.route("/video-watermark", methods=["POST"])
def av_video_watermark():
    video = request.files.get("video")
    image = request.files.get("image")
    if not video:
        return jsonify({"error": "No video file provided"}), 400
    if not image:
        return jsonify({"error": "No watermark image provided"}), 400
    vext, base = _names(video, "mp4", "video")
    iext = tools._ext_from_filename(image.filename, "png")
    try:
        out, out_ext = av2.video_watermark(
            video.stream.read(), vext, image.stream.read(), iext,
            request.form.get("position", "bottom-right"),
            _form_float("scale", 15), _form_float("opacity", 100), _form_int("margin", 16))
        return _send(out, f"{base}_watermarked.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/frames", methods=["POST"])
def av_frames():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    ext, base = _names(f, "mp4", "video")
    mode = request.form.get("mode", "single")
    try:
        out, name, mime = av2.extract_frames(
            f.stream.read(), ext, mode, base,
            time=_form_float("time", 0), interval=_form_float("interval", 1),
            count=_form_int("count", 10), fmt=request.form.get("format", "png").lower())
        return _send(out, name, mime)
    except Exception as e:
        return _error(e)


@av2_bp.route("/video-speed", methods=["POST"])
def av_video_speed():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    ext, base = _names(f, "mp4", "video")
    keep_pitch = request.form.get("keep_pitch", "true").lower() in ("1", "true", "on", "yes")
    try:
        speed = _form_float("speed", 1.0)
        out, out_ext = av2.video_speed(f.stream.read(), ext, speed, keep_pitch)
        return _send(out, f"{base}_{speed:g}x.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/stabilize", methods=["POST"])
def av_stabilize():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No video file provided"}), 400
    ext, base = _names(f, "mp4", "video")
    try:
        out, out_ext = av2.stabilize_video(f.stream.read(), ext, request.form.get("strength", "medium"))
        return _send(out, f"{base}_stabilized.{out_ext}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/gif-to-video", methods=["POST"])
def av_gif_to_video():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No GIF file provided"}), 400
    _, base = _names(f, "gif", "animation")
    fmt = request.form.get("format", "mp4").lower()
    try:
        out = av2.gif_to_video(f.stream.read(), fmt, _form_int("loop_count", 1))
        return _send(out, f"{base}.{fmt}")
    except Exception as e:
        return _error(e)


@av2_bp.route("/info", methods=["POST"])
def av_info():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No media file provided"}), 400
    ext, _ = _names(f, "bin", "media")
    try:
        info = av2.media_info(f.stream.read(), ext)
        info["filename"] = f.filename
        return jsonify(info)
    except Exception as e:
        return _error(e)


@av2_bp.route("/pip", methods=["POST"])
def av_pip():
    main = request.files.get("main")
    overlay = request.files.get("overlay")
    if not main:
        return jsonify({"error": "No main video provided"}), 400
    if not overlay:
        return jsonify({"error": "No overlay video provided"}), 400
    mext, base = _names(main, "mp4", "video")
    oext = tools._ext_from_filename(overlay.filename, "mp4")
    try:
        out = av2.picture_in_picture(
            main.stream.read(), mext, overlay.stream.read(), oext,
            request.form.get("position", "bottom-right"),
            _form_float("scale", 25), _form_int("margin", 16))
        return _send(out, f"{base}_pip.mp4", "video/mp4")
    except Exception as e:
        return _error(e)
