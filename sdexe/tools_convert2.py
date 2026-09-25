"""Pure functions for the second batch of converter tools (data + file tools).

No Flask imports. Called by routes_convert2.py.
"""

import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import PurePosixPath, PureWindowsPath

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore

try:
    import tomli_w
    _TOMLW_AVAILABLE = True
except ImportError:
    _TOMLW_AVAILABLE = False

try:
    import openpyxl
    _OPENPYXL_AVAILABLE = True
except ImportError:
    _OPENPYXL_AVAILABLE = False

try:
    import html2text
    _HTML2TEXT_AVAILABLE = True
except ImportError:
    _HTML2TEXT_AVAILABLE = False

try:
    import sqlparse
    _SQLPARSE_AVAILABLE = True
except ImportError:
    _SQLPARSE_AVAILABLE = False

try:
    import py7zr
    _PY7ZR_AVAILABLE = True
except ImportError:
    _PY7ZR_AVAILABLE = False


# ── Shared helpers ──

def _zip_bytes(files: list[tuple[str, bytes]], compress: bool = True) -> bytes:
    buf = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", method) as zf:
        for name, data in files:
            zf.writestr(name, data)
    return buf.getvalue()


def _dedupe(name: str, used: set) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, dot, suffix = name.rpartition(".")
    if not dot or "/" in suffix:
        stem, dot, suffix = name, "", ""
    n = 2
    cand = f"{stem}_{n}{dot}{suffix}" if dot else f"{name}_{n}"
    while cand in used:
        n += 1
        cand = f"{stem}_{n}{dot}{suffix}" if dot else f"{name}_{n}"
    used.add(cand)
    return cand


# ── JSON → XML ──

_XML_NAME_RE = re.compile(r"[^A-Za-z0-9_.\-]")


def _xml_name(key) -> str:
    name = _XML_NAME_RE.sub("_", str(key)).strip()
    if not name:
        name = "item"
    if not re.match(r"[A-Za-z_]", name):
        name = "_" + name
    if name.lower().startswith("xml"):
        name = "_" + name
    return name


def _json_scalar(value) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _build_xml(parent: ET.Element, key: str, value) -> None:
    """Append `value` under `parent` as element(s) named `key`."""
    if isinstance(value, list):
        # A list repeats the element name once per item (arrays of arrays nest as <item>).
        for item in value:
            _build_xml(parent, key, item)
        return
    el = ET.SubElement(parent, key)
    if isinstance(value, dict):
        for k, v in value.items():
            _build_xml(el, _xml_name(k), v)
    else:
        el.text = _json_scalar(value)


def json_to_xml_str(text: str, root: str = "root") -> str:
    data = json.loads(text)
    root_name = _xml_name(root or "root")
    root_el = ET.Element(root_name)
    if isinstance(data, dict):
        for k, v in data.items():
            _build_xml(root_el, _xml_name(k), v)
    elif isinstance(data, list):
        for item in data:
            _build_xml(root_el, "item", item)
    else:
        root_el.text = _json_scalar(data)
    ET.indent(root_el, space="  ")
    body = ET.tostring(root_el, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


# ── Excel → CSV ──

def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _sheet_to_csv(ws) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([_cell_str(c) for c in row])
    # Trim fully-empty trailing rows and columns (read_only sheets over-report dimensions).
    while rows and not any(rows[-1]):
        rows.pop()
    width = 0
    for r in rows:
        for i in range(len(r) - 1, -1, -1):
            if r[i] != "":
                width = max(width, i + 1)
                break
    for r in rows:
        writer.writerow(r[:width])
    return out.getvalue()


def _safe_name(s: str, default: str = "sheet") -> str:
    s = re.sub(r"[\\/:*?\"<>|]", "_", str(s)).strip()
    return s or default


def xlsx_to_csv(data: bytes, sheet: str = "") -> list[tuple[str, str]]:
    """Return list of (sheet_name, csv_text). `sheet` = "" or "all" for every sheet."""
    if not _OPENPYXL_AVAILABLE:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:
        raise ValueError(f"Could not open workbook: {e}")
    sheet = (sheet or "").strip()
    if sheet and sheet.lower() != "all":
        if sheet not in wb.sheetnames:
            raise ValueError(f"Sheet '{sheet}' not found. Available: {', '.join(wb.sheetnames)}")
        names = [sheet]
    else:
        names = wb.sheetnames
    if not names:
        raise ValueError("Workbook has no sheets")
    results = []
    for name in names:
        results.append((_safe_name(name), _sheet_to_csv(wb[name])))
    wb.close()
    return results


# ── CSV → Excel ──

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


def _coerce_cell(s: str):
    if s == "":
        return None
    t = s.strip()
    if _INT_RE.match(t):
        digits = t.lstrip("+-")
        # Keep leading-zero codes ("007", "00123") as text.
        if len(digits) > 1 and digits[0] == "0":
            return s
        try:
            return int(t)
        except ValueError:
            return s
    if _FLOAT_RE.match(t):
        try:
            return float(t)
        except ValueError:
            return s
    return s


def _sheet_title(filename: str, used: set) -> str:
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    title = re.sub(r"[\\/*?:\[\]]", "_", base).strip() or "Sheet"
    title = title[:31]
    cand = title
    n = 2
    while cand in used:
        suffix = f"_{n}"
        cand = title[:31 - len(suffix)] + suffix
        n += 1
    used.add(cand)
    return cand


def csv_to_xlsx(files: list[tuple[str, str]], header: bool = True) -> bytes:
    """files: list of (filename, csv_text). Each becomes a sheet."""
    if not _OPENPYXL_AVAILABLE:
        raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    used = set()
    for filename, text in files:
        ws = wb.create_sheet(_sheet_title(filename or "data", used))
        text = text.lstrip("﻿")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        widths = {}
        for r_idx, row in enumerate(csv.reader(io.StringIO(text), dialect), 1):
            for c_idx, raw in enumerate(row, 1):
                val = _coerce_cell(raw)
                ws.cell(row=r_idx, column=c_idx, value=val)
                widths[c_idx] = max(widths.get(c_idx, 0), len(raw))
        if header and ws.max_row >= 1:
            for cell in ws[1]:
                cell.font = Font(bold=True)
            ws.freeze_panes = "A2"
            for c_idx, w in widths.items():
                ws.column_dimensions[get_column_letter(c_idx)].width = min(60, max(8, w + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── HTML → Markdown ──

def html_to_md_str(text: str) -> str:
    if not _HTML2TEXT_AVAILABLE:
        raise RuntimeError("html2text not installed. Run: pip install html2text")
    h = html2text.HTML2Text()
    h.body_width = 0            # no hard wrapping
    h.ignore_links = False
    h.ignore_images = False
    h.ignore_emphasis = False
    h.ignore_tables = False
    h.unicode_snob = True
    h.protect_links = False
    h.mark_code = False
    h.single_line_break = False
    out = h.handle(text)
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


# ── TOML ↔ JSON ──

def _json_default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def toml_to_json_str(text: str) -> str:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid TOML: {e}")
    return json.dumps(data, indent=2, ensure_ascii=False, default=_json_default)


def _find_null(obj, path="$"):
    if obj is None:
        return path
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = _find_null(v, f"{path}.{k}")
            if p:
                return p
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = _find_null(v, f"{path}[{i}]")
            if p:
                return p
    return None


def json_to_toml_str(text: str) -> str:
    if not _TOMLW_AVAILABLE:
        raise RuntimeError("tomli-w not installed. Run: pip install tomli-w")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("TOML requires a top-level object (JSON must be {...}, not an array or scalar)")
    null_path = _find_null(data)
    if null_path:
        raise ValueError(f"TOML has no null value; remove or replace the null at {null_path}")
    return tomli_w.dumps(data)


# ── SQL Formatter ──

def sql_format(text: str, reindent: bool = True, keyword_case: str = "upper",
               indent_width: int = 2, strip_comments: bool = False,
               minify: bool = False) -> str:
    if not _SQLPARSE_AVAILABLE:
        raise RuntimeError("sqlparse not installed. Run: pip install sqlparse")
    kw = keyword_case if keyword_case in ("upper", "lower") else None
    if minify:
        out = sqlparse.format(text, keyword_case=kw, strip_comments=True,
                              strip_whitespace=True, reindent=False)
        out = re.sub(r"\s+", " ", out).strip()
        out = re.sub(r"\s*([,;()])\s*", r"\1", out)
        out = re.sub(r"([,;])(?=\S)", r"\1 ", out)
        out = re.sub(r"\(\s+", "(", out)
        return out
    out = sqlparse.format(text, reindent=reindent, keyword_case=kw,
                          indent_width=max(1, min(8, int(indent_width))),
                          strip_comments=strip_comments, use_space_around_operators=True)
    return out.strip() + "\n"


# ── Extract Archive ──

ARCHIVE_CAP = 2 * 1024 * 1024 * 1024  # 2 GB uncompressed


def _safe_member_path(name: str):
    """Return a normalized relative path, or None if the entry must be skipped."""
    raw = name.replace("\\", "/")
    if not raw or raw.startswith("/") or PureWindowsPath(raw).is_absolute() or re.match(r"^[A-Za-z]:", raw):
        return None
    parts = [p for p in PurePosixPath(raw).parts if p not in ("", ".", "/")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def _detect_kind(filename: str, head: bytes) -> str:
    fn = (filename or "").lower()
    if head.startswith(b"PK\x03\x04") or fn.endswith(".zip"):
        return "zip"
    if head.startswith(b"7z\xbc\xaf\x27\x1c") or fn.endswith(".7z"):
        return "7z"
    if head.startswith(b"Rar!") or fn.endswith(".rar"):
        return "rar"
    if fn.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz")):
        return "tar"
    if head.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")):
        return "tar"
    if len(head) > 262 and head[257:262] == b"ustar":
        return "tar"
    raise ValueError("Unsupported archive type. Use .zip, .tar, .tar.gz, .tgz, .tar.bz2, .tar.xz, .7z or .rar")


def _unrar_available() -> bool:
    return shutil.which("unrar") is not None


_UNRAR_MSG = "RAR needs the unrar tool: brew install unrar / apt install unrar"


def archive_list(data: bytes, filename: str = "") -> list[dict]:
    """List entries as [{name, size}] without extracting (skips unsafe paths and directories)."""
    kind = _detect_kind(filename, data[:512])
    entries = []
    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = _safe_member_path(info.filename)
                if name:
                    entries.append({"name": name, "size": info.file_size})
    elif kind == "tar":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                name = _safe_member_path(m.name)
                if name:
                    entries.append({"name": name, "size": m.size})
    elif kind == "7z":
        if not _PY7ZR_AVAILABLE:
            raise RuntimeError("py7zr not installed. Run: pip install py7zr")
        with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as z:
            for info in z.list():
                if info.is_directory:
                    continue
                name = _safe_member_path(info.filename)
                if name:
                    entries.append({"name": name, "size": info.uncompressed or 0})
    elif kind == "rar":
        if not _unrar_available():
            raise RuntimeError(_UNRAR_MSG)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "archive.rar")
            with open(path, "wb") as fh:
                fh.write(data)
            proc = subprocess.run(["unrar", "lt", "-p-", "--", path], capture_output=True, text=True)
            if proc.returncode not in (0, 1):
                raise ValueError(proc.stderr.strip() or "unrar failed to read archive")
            cur = {}
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("Name:"):
                    cur = {"name": line[5:].strip()}
                elif line.startswith("Type:"):
                    cur["type"] = line[5:].strip()
                elif line.startswith("Size:"):
                    try:
                        cur["size"] = int(line[5:].strip())
                    except ValueError:
                        cur["size"] = 0
                    if cur.get("type", "File") == "File":
                        name = _safe_member_path(cur["name"])
                        if name:
                            entries.append({"name": name, "size": cur["size"]})
    return entries


def _collect_dir(out: str, add) -> None:
    """Walk an extraction directory and feed every regular file to add(name, bytes)."""
    real_out = os.path.realpath(out)
    for dirpath, _dirs, files in os.walk(out):
        for fn in sorted(files):
            full = os.path.join(dirpath, fn)
            if os.path.islink(full) or not os.path.realpath(full).startswith(real_out + os.sep):
                continue
            rel = os.path.relpath(full, out).replace(os.sep, "/")
            name = _safe_member_path(rel)
            if not name:
                continue
            with open(full, "rb") as fh:
                add(name, fh.read())


def extract_archive(data: bytes, filename: str = "") -> list[tuple[str, bytes]]:
    """Extract any supported archive. Returns list of (relative_path, bytes)."""
    kind = _detect_kind(filename, data[:512])
    total = 0
    results = []
    used = set()

    def add(name, blob):
        nonlocal total
        total += len(blob)
        if total > ARCHIVE_CAP:
            raise ValueError("Archive contents exceed the 2 GB limit")
        results.append((_dedupe(name, used), blob))

    if kind == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = _safe_member_path(info.filename)
                if not name:
                    continue
                if info.file_size > ARCHIVE_CAP:
                    raise ValueError("Archive contents exceed the 2 GB limit")
                add(name, zf.read(info))
    elif kind == "tar":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                name = _safe_member_path(m.name)
                if not name:
                    continue
                if m.size > ARCHIVE_CAP:
                    raise ValueError("Archive contents exceed the 2 GB limit")
                fh = tf.extractfile(m)
                if fh is None:
                    continue
                add(name, fh.read())
    elif kind == "7z":
        if not _PY7ZR_AVAILABLE:
            raise RuntimeError("py7zr not installed. Run: pip install py7zr")
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "out")
            os.makedirs(out)
            with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as z:
                total_declared = sum((i.uncompressed or 0) for i in z.list() if not i.is_directory)
                if total_declared > ARCHIVE_CAP:
                    raise ValueError("Archive contents exceed the 2 GB limit")
                # py7zr 1.x has no in-memory read; it refuses unsafe paths itself.
                z.extractall(path=out)
            _collect_dir(out, add)
    elif kind == "rar":
        if not _unrar_available():
            raise RuntimeError(_UNRAR_MSG)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "archive.rar")
            with open(path, "wb") as fh:
                fh.write(data)
            out = os.path.join(td, "out")
            os.makedirs(out)
            proc = subprocess.run(["unrar", "x", "-o+", "-p-", "-y", "--", path, out + os.sep],
                                  capture_output=True, text=True)
            if proc.returncode not in (0, 1):
                raise ValueError(proc.stderr.strip() or proc.stdout.strip() or "unrar failed")
            _collect_dir(out, add)
    if not results:
        raise ValueError("Archive is empty (or every entry was skipped as unsafe)")
    return results


def archive_base_name(filename: str, default: str = "archive") -> str:
    fn = filename or ""
    low = fn.lower()
    for ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".tbz", ".txz",
                ".tar", ".zip", ".7z", ".rar"):
        if low.endswith(ext):
            return fn[:-len(ext)] or default
    return fn.rsplit(".", 1)[0] if "." in fn else (fn or default)


# ── Checksum ──

def checksum(stream, chunk: int = 1024 * 1024) -> dict:
    hashes = {
        "md5": hashlib.md5(),
        "sha1": hashlib.sha1(),
        "sha256": hashlib.sha256(),
        "sha512": hashlib.sha512(),
    }
    size = 0
    while True:
        block = stream.read(chunk)
        if not block:
            break
        size += len(block)
        for h in hashes.values():
            h.update(block)
    out = {k: h.hexdigest() for k, h in hashes.items()}
    out["size"] = size
    return out


# ── Batch Rename ──
#
# The same rules are implemented in convert.js (renamePreview). Keep both in sync:
#   1. split into stem / ext (ext = text after last dot, no dot; none if no dot)
#   2. plain find → replace on the stem (all occurrences, case-sensitive)
#   3. apply case (keep | lower | upper | title) to the stem
#   4. expand pattern: {name} {ext} {n} {n:03} {date}; ".{ext}" collapses when ext is empty
#   5. strip path separators; fall back to original name if empty; dedupe with _2, _3…

_N_TOKEN_RE = re.compile(r"\{n(?::0?(\d+))?\}")


def _apply_case(s: str, mode: str) -> str:
    if mode == "lower":
        return s.lower()
    if mode == "upper":
        return s.upper()
    if mode == "title":
        return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), s)
    return s


def rename_one(filename: str, index: int, pattern: str = "{name}.{ext}", find: str = "",
               replace: str = "", case: str = "keep", date_str: str = "") -> str:
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in base and not base.startswith(".") :
        stem, ext = base.rsplit(".", 1)
    elif base.startswith(".") and base.count(".") > 1:
        stem, ext = base.rsplit(".", 1)
    else:
        stem, ext = base, ""
    if find:
        stem = stem.replace(find, replace)
    stem = _apply_case(stem, case)
    pat = pattern if pattern.strip() else "{name}.{ext}"
    out = pat.replace("{name}", stem)
    out = out.replace(".{ext}", ("." + ext) if ext else "")
    out = out.replace("{ext}", ext)
    out = out.replace("{date}", date_str or date.today().isoformat())
    out = _N_TOKEN_RE.sub(lambda m: str(index).zfill(int(m.group(1))) if m.group(1) else str(index), out)
    out = out.replace("/", "_").replace("\\", "_").strip()
    return out or base


def batch_rename_names(filenames: list[str], pattern: str = "{name}.{ext}", find: str = "",
                       replace: str = "", case: str = "keep", start: int = 1,
                       date_str: str = "") -> list[str]:
    used = set()
    out = []
    for i, fn in enumerate(filenames):
        out.append(_dedupe(rename_one(fn, start + i, pattern, find, replace, case, date_str), used))
    return out


# ── File Splitter / Joiner ──

def split_file(data: bytes, filename: str, chunk_mb: float = 100) -> list[tuple[str, bytes]]:
    """Split into <name>.001, .002… plus JOIN.txt. Returns list of (name, bytes)."""
    if chunk_mb <= 0:
        raise ValueError("Chunk size must be greater than 0 MB")
    chunk = int(chunk_mb * 1024 * 1024)
    if chunk < 1:
        raise ValueError("Chunk size too small")
    name = (filename or "file").rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or "file"
    if len(data) <= chunk:
        raise ValueError(f"File is {len(data) / 1048576:.1f} MB, not larger than the {chunk_mb:g} MB chunk size; nothing to split")
    count = (len(data) + chunk - 1) // chunk
    if count > 999:
        raise ValueError(f"Would produce {count} parts; increase the chunk size (max 999 parts)")
    parts = []
    for i in range(count):
        parts.append((f"{name}.{i + 1:03d}", data[i * chunk:(i + 1) * chunk]))
    part_names = [p[0] for p in parts]
    join_txt = (
        f"Reassemble {name} ({len(data)} bytes, {count} parts of {chunk_mb:g} MB)\n"
        f"Put all parts in one folder, open a terminal there, and run:\n\n"
        f"macOS / Linux:\n"
        f"  cat {' '.join(part_names)} > \"{name}\"\n\n"
        f"Windows (Command Prompt):\n"
        f"  copy /b {'+'.join(part_names)} \"{name}\"\n\n"
        f"Windows (PowerShell):\n"
        f"  cmd /c copy /b {'+'.join(part_names)} \"{name}\"\n\n"
        f"Or use the Join Files option in the sdexe File Splitter tool.\n"
        f"SHA-256 of the original: {hashlib.sha256(data).hexdigest()}\n"
    )
    parts.append(("JOIN.txt", join_txt.encode("utf-8")))
    return parts


_PART_RE = re.compile(r"^(.*)\.(\d{3,})$")


def join_files(files: list[tuple[str, bytes]]) -> tuple[str, bytes]:
    """Concatenate part files sorted by name. Returns (output_name, bytes)."""
    parts = [(n, d) for n, d in files if n.upper() != "JOIN.TXT"]
    if not parts:
        raise ValueError("No part files provided")
    parts.sort(key=lambda p: p[0])
    first = parts[0][0]
    m = _PART_RE.match(first)
    base = m.group(1) if m else first
    if m:
        for n, _ in parts:
            mm = _PART_RE.match(n)
            if not mm or mm.group(1) != base:
                raise ValueError(f"'{n}' does not look like a part of '{base}' (expected {base}.NNN)")
        nums = [int(_PART_RE.match(n).group(2)) for n, _ in parts]
        expected = list(range(nums[0], nums[0] + len(nums)))
        if nums != expected:
            raise ValueError(f"Parts are not consecutive: found {nums}")
    return base or "joined", b"".join(d for _, d in parts)
