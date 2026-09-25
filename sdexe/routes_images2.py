"""Flask Blueprint for the second batch of image tools.

Registered by app.py as: from sdexe.routes_images2 import images2_bp; app.register_blueprint(images2_bp)
"""

import io

from flask import Blueprint, request, jsonify, send_file
from PIL import Image

from sdexe import tools
from sdexe import tools_images2 as t2

images2_bp = Blueprint("images2", __name__, url_prefix="/api/images")


def _form_float(name: str, default: float) -> float:
    raw = request.form.get(name, "")
    if raw is None or str(raw).strip() == "":
        return default
    return float(raw)


def _form_int(name: str, default: int) -> int:
    raw = request.form.get(name, "")
    if raw is None or str(raw).strip() == "":
        return default
    return int(float(raw))


def _form_bool(name: str, default: bool = False) -> bool:
    raw = request.form.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _files_or_file():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    return [f for f in files if f and f.filename]


def _send_image(img, filename: str, suffix: str, fmt: str | None = None):
    if fmt is None:
        fmt = tools._ext_from_filename(filename)
        if fmt not in tools._PIL_FMT_MAP:
            fmt = "png"
    if fmt == "jpeg":
        fmt = "jpg"
    # Anything with transparency must leave as PNG (or WebP) to keep it.
    if fmt in ("jpg", "gif") and img.mode in ("RGBA", "LA"):
        fmt = "png"
    data = tools._save_image(img, fmt)
    base = tools._base_from_filename(filename, "image")
    mime = tools._MIME_MAP.get(fmt, f"image/{fmt}")
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name=f"{base}_{suffix}.{fmt}", mimetype=mime)


# ── HEIC → JPG / PNG ──

@images2_bp.route("/heic", methods=["POST"])
def image_heic():
    files = _files_or_file()
    if not files:
        return jsonify({"error": "No HEIC file provided"}), 400
    fmt = request.form.get("format", "jpg").lower()
    fmt = "png" if fmt == "png" else "jpg"
    try:
        quality = _form_int("quality", 90)
    except ValueError:
        return jsonify({"error": "Invalid quality"}), 400

    results = []
    for f in files:
        try:
            data = t2.heic_to_image(f.stream, fmt=fmt, quality=quality)
        except Exception as e:
            return jsonify({"error": f"Could not convert {f.filename}: {e}"}), 400
        base = tools._base_from_filename(f.filename, "image")
        results.append((f"{base}.{fmt}", data))

    if len(results) == 1:
        name, data = results[0]
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name,
                         mimetype=tools._MIME_MAP.get(fmt, "image/jpeg"))
    zip_data = tools.create_zip(results)
    return send_file(io.BytesIO(zip_data), as_attachment=True,
                     download_name=f"heic_converted_{fmt}.zip", mimetype="application/zip")


# ── Adjust ──

@images2_bp.route("/adjust", methods=["POST"])
def image_adjust():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        brightness = _form_float("brightness", 100)
        contrast = _form_float("contrast", 100)
        saturation = _form_float("saturation", 100)
        sharpness = _form_float("sharpness", 100)
    except ValueError:
        return jsonify({"error": "Adjustment values must be numbers"}), 400
    try:
        img = Image.open(f.stream)
        out = t2.adjust_image_full(img, brightness, contrast, saturation, sharpness)
        return _send_image(out, f.filename, "adjusted")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── EXIF Viewer ──

@images2_bp.route("/exif", methods=["POST"])
def image_exif():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        data = f.read()
        info = t2.read_exif(io.BytesIO(data), filename=f.filename or "", file_size=len(data))
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Border / Padding ──

@images2_bp.route("/border", methods=["POST"])
def image_border():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        size = _form_int("size", 20)
        radius = _form_int("radius", 0)
    except ValueError:
        return jsonify({"error": "Size and radius must be whole numbers"}), 400
    color = request.form.get("color", "#ffffff")
    mode = request.form.get("mode", "border")
    if mode not in ("border", "padding"):
        return jsonify({"error": "Mode must be border or padding"}), 400
    try:
        img = Image.open(f.stream)
        fmt = tools._ext_from_filename(f.filename)
        if fmt not in tools._PIL_FMT_MAP:
            fmt = "png"
        transparent = mode == "padding" and fmt in ("png", "webp")
        out = t2.add_border(img, size=size, color=color, mode=mode, radius=radius,
                            transparent=transparent)
        return _send_image(out, f.filename, "bordered" if mode == "border" else "padded", fmt)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Favicon Set ──

@images2_bp.route("/favicon-set", methods=["POST"])
def image_favicon_set():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        img = Image.open(f.stream)
        zip_data = t2.favicon_set(img)
        base = tools._base_from_filename(f.filename, "favicon")
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name=f"{base}_favicons.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Upscale ──

@images2_bp.route("/upscale", methods=["POST"])
def image_upscale():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        factor = _form_int("factor", 2)
    except ValueError:
        return jsonify({"error": "Invalid factor"}), 400
    try:
        img = Image.open(f.stream)
        out = t2.upscale_image(img, factor)
        return _send_image(out, f.filename, f"{factor}x")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Collage / Sprite Sheet ──

@images2_bp.route("/collage", methods=["POST"])
def image_collage():
    files = _files_or_file()
    if not files:
        return jsonify({"error": "No images provided"}), 400
    try:
        columns = _form_int("columns", 0)
        cell = _form_int("cell", 256)
        gap = _form_int("gap", 0)
    except ValueError:
        return jsonify({"error": "Columns, cell and gap must be whole numbers"}), 400
    background = request.form.get("background", "#ffffff")
    fit = request.form.get("fit", "contain")
    if fit not in ("contain", "cover"):
        return jsonify({"error": "Fit must be contain or cover"}), 400
    output = request.form.get("output", "image")
    transparent = _form_bool("transparent", False)

    images = []
    for f in files:
        try:
            img = Image.open(f.stream)
            img.load()
        except Exception as e:
            return jsonify({"error": f"Invalid image {f.filename}: {e}"}), 400
        images.append((f.filename or f"image-{len(images) + 1}", img))

    try:
        sheet, css = t2.make_collage(images, columns=columns, cell=cell, gap=gap,
                                     background=background, fit=fit, transparent=transparent)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if output == "zip":
        zip_data = t2.collage_zip(sheet, css)
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name="sprite_sheet.zip", mimetype="application/zip")
    data = tools._save_image(sheet, "png")
    return send_file(io.BytesIO(data), as_attachment=True,
                     download_name="collage.png", mimetype="image/png")


# ── Image → ASCII ──

@images2_bp.route("/ascii", methods=["POST"])
def image_ascii():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No image provided"}), 400
    try:
        width = _form_int("width", 100)
    except ValueError:
        return jsonify({"error": "Width must be a whole number"}), 400
    charset = request.form.get("charset", "standard")
    invert = _form_bool("invert", False)
    try:
        img = Image.open(f.stream)
        text = t2.image_to_ascii(img, width=width, charset=charset, invert=invert)
        return jsonify({"text": text, "width": width, "lines": text.count("\n") + 1})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
