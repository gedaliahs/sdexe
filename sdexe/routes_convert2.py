"""Flask Blueprint for the second batch of converter tools (data + file tools).

Registered by app.py as: from sdexe.routes_convert2 import convert2_bp
                          app.register_blueprint(convert2_bp)
"""

import io

from flask import Blueprint, request, jsonify, send_file

from sdexe import tools
from sdexe import tools_convert2 as t2

convert2_bp = Blueprint("convert2", __name__, url_prefix="/api/convert")


def _text_input(default_error: str):
    """Read text from an uploaded `file` or the `text` form field."""
    f = request.files.get("file")
    if f:
        text = f.stream.read().decode("utf-8-sig", errors="replace")
    else:
        text = request.form.get("text", "")
    if not text.strip():
        raise ValueError(default_error)
    return text, (f.filename if f else "")


def _bool(name: str, default: bool = False) -> bool:
    v = request.form.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "on", "yes")


# ── Data tools ──

@convert2_bp.route("/json-to-xml", methods=["POST"])
def json_to_xml():
    try:
        text, filename = _text_input("No JSON content provided")
        root = request.form.get("root", "root").strip() or "root"
        result = t2.json_to_xml_str(text, root)
        base = tools._base_from_filename(filename, "data") if filename else "data"
        return jsonify({"result": result, "filename": f"{base}.xml"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/xlsx-to-csv", methods=["POST"])
def xlsx_to_csv():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No Excel file provided"}), 400
    sheet = request.form.get("sheet", "")
    try:
        sheets = t2.xlsx_to_csv(f.stream.read(), sheet)
        base = tools._base_from_filename(f.filename or "", "workbook")
        if len(sheets) == 1:
            _, csv_text = sheets[0]
            return send_file(io.BytesIO(csv_text.encode("utf-8")), as_attachment=True,
                             download_name=f"{base}.csv", mimetype="text/csv")
        zip_data = tools.create_zip([(f"{name}.csv", csv_text.encode("utf-8")) for name, csv_text in sheets])
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name=f"{base}_sheets.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/csv-to-xlsx", methods=["POST"])
def csv_to_xlsx():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No CSV files provided"}), 400
    header = _bool("header", True)
    try:
        inputs = [(f.filename or "data.csv", f.stream.read().decode("utf-8-sig", errors="replace")) for f in files]
        result = t2.csv_to_xlsx(inputs, header=header)
        base = tools._base_from_filename(files[0].filename or "", "data") if len(files) == 1 else "workbook"
        return send_file(io.BytesIO(result), as_attachment=True, download_name=f"{base}.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/html-to-md", methods=["POST"])
def html_to_md():
    try:
        text, filename = _text_input("No HTML content provided")
        result = t2.html_to_md_str(text)
        base = tools._base_from_filename(filename, "converted") if filename else "converted"
        return jsonify({"result": result, "filename": f"{base}.md"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/toml-to-json", methods=["POST"])
def toml_to_json():
    try:
        text, filename = _text_input("No TOML content provided")
        result = t2.toml_to_json_str(text)
        base = tools._base_from_filename(filename, "data") if filename else "data"
        return jsonify({"result": result, "filename": f"{base}.json"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/json-to-toml", methods=["POST"])
def json_to_toml():
    try:
        text, filename = _text_input("No JSON content provided")
        result = t2.json_to_toml_str(text)
        base = tools._base_from_filename(filename, "data") if filename else "data"
        return jsonify({"result": result, "filename": f"{base}.toml"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/sql-format", methods=["POST"])
def sql_format():
    try:
        text, _ = _text_input("No SQL provided")
        try:
            indent_width = int(request.form.get("indent_width", 2))
        except ValueError:
            return jsonify({"error": "Invalid indent width"}), 400
        result = t2.sql_format(
            text,
            reindent=_bool("reindent", True),
            keyword_case=request.form.get("keyword_case", "upper"),
            indent_width=indent_width,
            strip_comments=_bool("strip_comments", False),
            minify=_bool("minify", False),
        )
        return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── File tools ──

@convert2_bp.route("/archive-list", methods=["POST"])
def archive_list():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No archive provided"}), 400
    try:
        entries = t2.archive_list(f.stream.read(), f.filename or "")
        total = sum(e["size"] for e in entries)
        return jsonify({"entries": entries, "count": len(entries), "total_size": total})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/extract-archive", methods=["POST"])
def extract_archive():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No archive provided"}), 400
    try:
        extracted = t2.extract_archive(f.stream.read(), f.filename or "")
        zip_data = tools.create_zip(extracted)
        base = t2.archive_base_name(f.filename or "", "archive")
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name=f"{base}_extracted.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/checksum", methods=["POST"])
def checksum():
    files = request.files.getlist("files")
    if not files:
        f = request.files.get("file")
        if f:
            files = [f]
    if not files:
        return jsonify({"error": "No files provided"}), 400
    try:
        out = {}
        used = set()
        for f in files:
            name = t2._dedupe(f.filename or "file", used)
            out[name] = t2.checksum(f.stream)
        return jsonify(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/batch-rename", methods=["POST"])
def batch_rename():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files provided"}), 400
    try:
        start = int(request.form.get("start", 1))
    except ValueError:
        return jsonify({"error": "Invalid start number"}), 400
    case = request.form.get("case", "keep")
    if case not in ("keep", "lower", "upper", "title"):
        return jsonify({"error": "Invalid case option"}), 400
    try:
        names = t2.batch_rename_names(
            [f.filename or "file" for f in files],
            pattern=request.form.get("pattern", "{name}.{ext}"),
            find=request.form.get("find", ""),
            replace=request.form.get("replace", ""),
            case=case,
            start=start,
            date_str=request.form.get("date", ""),
        )
        zip_data = tools.create_zip([(n, f.stream.read()) for n, f in zip(names, files)])
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name="renamed.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/split-file", methods=["POST"])
def split_file():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file provided"}), 400
    try:
        chunk_mb = float(request.form.get("chunk_mb", 100))
    except ValueError:
        return jsonify({"error": "Invalid chunk size"}), 400
    try:
        parts = t2.split_file(f.stream.read(), f.filename or "file", chunk_mb)
        zip_data = t2._zip_bytes(parts, compress=False)
        base = tools._base_from_filename(f.filename or "", "file")
        return send_file(io.BytesIO(zip_data), as_attachment=True,
                         download_name=f"{base}_parts.zip", mimetype="application/zip")
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@convert2_bp.route("/join-files", methods=["POST"])
def join_files():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No part files provided"}), 400
    try:
        name, data = t2.join_files([(f.filename or "part", f.stream.read()) for f in files])
        return send_file(io.BytesIO(data), as_attachment=True, download_name=name,
                         mimetype="application/octet-stream")
    except Exception as e:
        return jsonify({"error": str(e)}), 400
