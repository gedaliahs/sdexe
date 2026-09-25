"""Flask blueprint for the second batch of PDF tools (see tools_pdf2.py)."""

import io

from flask import Blueprint, request, jsonify, send_file

from sdexe import tools
from sdexe import tools_pdf2

pdf2_bp = Blueprint("pdf2", __name__, url_prefix="/api/pdf")


@pdf2_bp.route("/to-images", methods=["POST"])
def pdf_to_images():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    fmt = request.form.get("format", "png").lower()
    try:
        dpi = int(request.form.get("dpi", 150))
        parts = tools_pdf2.pdf_to_images(f.stream, fmt, dpi, request.form.get("pages", "all"))
        base = tools._base_from_filename(f.filename, "document")
        if len(parts) == 1:
            name, data = parts[0]
            mime = "image/jpeg" if fmt == "jpg" else "image/png"
            return send_file(io.BytesIO(data), as_attachment=True,
                             download_name=f"{base}_{name}", mimetype=mime)
        zip_data = tools.create_zip(parts)
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name=f"{base}_pages.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@pdf2_bp.route("/ocr", methods=["POST"])
def pdf_ocr():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400
    try:
        text, pages = tools_pdf2.ocr_document(f.stream, f.filename or "",
                                              request.form.get("language", "eng"))
        return jsonify({"text": text, "pages": pages})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@pdf2_bp.route("/from-office", methods=["POST"])
def pdf_from_office():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No document provided"}), 400
    try:
        result = tools_pdf2.office_to_pdf(f.stream, f.filename or "")
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@pdf2_bp.route("/stamp", methods=["POST"])
def pdf_stamp():
    f = request.files.get("file")
    img = request.files.get("image")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    if not img:
        return jsonify({"error": "No stamp image provided"}), 400
    try:
        result = tools_pdf2.stamp_pdf(
            f.stream, img.stream,
            position=request.form.get("position", "bottom-right"),
            scale=float(request.form.get("scale", 25)),
            opacity=float(request.form.get("opacity", 100)),
            pages_str=request.form.get("pages", "all"),
        )
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_stamped.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@pdf2_bp.route("/page-size", methods=["POST"])
def pdf_page_size():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    size = request.form.get("size", "a4").lower()
    try:
        result = tools_pdf2.resize_pdf_pages(f.stream, size, request.form.get("fit", "fit"))
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_{size}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@pdf2_bp.route("/flatten", methods=["POST"])
def pdf_flatten():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No PDF file provided"}), 400
    try:
        result = tools_pdf2.flatten_pdf(f.stream)
        base = tools._base_from_filename(f.filename, "document")
        return send_file(io.BytesIO(result), as_attachment=True,
                         download_name=f"{base}_flattened.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 400
