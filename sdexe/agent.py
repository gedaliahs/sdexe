"""Agent integration: `sdexe mcp` (an MCP server over stdio) and `sdexe skill`
(a Claude Code skill file).

Both are generated from the CLI's own command table, so every command the CLI
has is a tool here too. The MCP server runs each call as `python -m sdexe ...
--json` in a subprocess: stdout stays pure JSON-RPC, a crash in one tool can't
take the server down, and a cancelled request kills its process.

No dependency on the MCP SDK; the stdio protocol is small enough to speak
directly (JSON-RPC 2.0, one message per line).
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from sdexe import __version__, media
from sdexe.cli_tools import COMMANDS, GROUPS, Cmd

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "sdexe runs media, PDF, image, audio/video, data-conversion and file tools locally. "
    "Inputs are file paths on this machine; outputs are written to disk and their paths "
    "are returned. Use media_info before download to see available qualities."
)

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


# ── Tool definitions ──

def _download_tool():
    return {
        "name": "download",
        "title": "Download media",
        "description": (
            "Download video or audio from YouTube and 1000+ other sites to disk. Default: MP4, "
            "the best stream up to 1080p60. Audio-only defaults to WAV (lossless). Returns saved "
            "paths, sizes and resolution. Batch several URLs in one call."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                         "description": "links to download"},
                "format": {"type": "string", "enum": list(media.VIDEO_FORMATS + media.AUDIO_FORMATS),
                           "description": "container; mp4 by default, wav when audio_only"},
                "quality": {"type": "string",
                            "description": "video: 2160p, 1440p, 1080p, 720p, 480p, 360p, optionally "
                                           "with fps (1080p30), or best for no cap. mp3: 128/192/256/320"},
                "audio_only": {"type": "boolean"},
                "output": {"type": "string", "description": "folder, or a file name for one URL"},
                "playlist": {"type": "boolean", "description": "download every video in a playlist/channel"},
                "limit": {"type": "integer", "minimum": 1, "description": "first N playlist entries"},
                "start": {"type": "string", "description": "clip start, like 1:30"},
                "end": {"type": "string", "description": "clip end, like 2:00"},
                "cookies_from_browser": {"type": "string",
                                         "description": "chrome, safari, firefox, brave or edge"},
            },
            "required": ["urls"],
        },
    }


def _info_tool():
    return {
        "name": "media_info",
        "title": "Inspect a media link",
        "description": (
            "Title, uploader, duration, every available video quality with sizes, audio streams, "
            "chapters and subtitles for a link, without downloading. Also reports exactly which "
            "streams `download` would pick for the given format/quality."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "format": {"type": "string", "enum": list(media.VIDEO_FORMATS + media.AUDIO_FORMATS)},
                "quality": {"type": "string"},
                "playlist": {"type": "boolean", "description": "list every entry of a playlist"},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["urls"],
        },
    }


def _cmd_tool(cmd: Cmd) -> dict:
    props, required = {}, []
    if cmd.inputs == "none":
        props[cmd.text_arg] = {"type": "string"}
        required.append(cmd.text_arg)
    else:
        files = {"type": "array", "items": {"type": "string"},
                 "description": "absolute paths of the input files"}
        if cmd.inputs == "pair":
            files.update(minItems=2, maxItems=2, description=f"exactly two paths: {cmd.inputs_help}")
        elif cmd.inputs == "many":
            files.update(minItems=1, description="paths to combine, in order")
        else:
            files.update(minItems=1, description="paths; each is processed separately")
        props["files"] = files
        required.append("files")
    for arg in cmd.args:
        schema = {"type": _JSON_TYPES.get(arg.type, "string")}
        if arg.help:
            schema["description"] = arg.help
        if arg.choices:
            schema["enum"] = list(arg.choices)
        if arg.default not in (None, "") and arg.type is not bool:
            schema["default"] = arg.default
        props[arg.dest] = schema
        if arg.required:
            required.append(arg.dest)
    text_out = cmd.name in ("text", "ocr", "ascii")
    props["output"] = {"type": "string", "description": (
        "file to save the text to (default: returned inline)" if text_out
        else "output folder, or a file name for a single input")}
    desc = f"{cmd.group}: {cmd.summary}."
    if cmd.example:
        desc += f" CLI equivalent: {cmd.example}"
    return {
        "name": cmd.tool_name,
        "title": f"sdexe {cmd.full}",
        "description": desc,
        "inputSchema": {"type": "object", "properties": props, "required": required},
    }


def tool_definitions() -> list:
    return [_download_tool(), _info_tool()] + [_cmd_tool(c) for c in COMMANDS]


_CMD_BY_TOOL = {c.tool_name: c for c in COMMANDS}


# ── Turning a tool call into CLI arguments ──

def _abs(p: str, base: Path) -> str:
    path = Path(os.path.expanduser(p))
    return str(path if path.is_absolute() else base / path)


def tool_argv(name: str, a: dict, base: Path) -> list:
    if name in ("download", "media_info"):
        argv = ["download" if name == "download" else "info", *a.get("urls", [])]
        if a.get("format"):
            argv += ["-f", a["format"]]
        if a.get("quality"):
            argv += ["-q", str(a["quality"])]
        if a.get("audio_only"):
            argv.append("--audio")
        if a.get("playlist"):
            argv.append("--playlist")
        if a.get("limit"):
            argv += ["--limit", str(a["limit"])]
        for key in ("start", "end"):
            if a.get(key):
                argv += [f"--{key}", str(a[key])]
        if a.get("cookies_from_browser"):
            argv += ["--cookies-from-browser", a["cookies_from_browser"]]
        if name == "download" and a.get("output"):
            argv += ["-o", _abs(a["output"], base)]
        return argv

    cmd = _CMD_BY_TOOL.get(name)
    if not cmd:
        raise KeyError(name)
    argv = cmd.full.split()
    if cmd.inputs != "none":
        argv += [_abs(f, base) for f in a.get("files", [])]
    for arg in cmd.args:
        if arg.dest not in a or a[arg.dest] is None:
            continue
        if arg.type is bool:
            if a[arg.dest]:
                argv.append(arg.flag)
        else:
            argv += [arg.flag, str(a[arg.dest])]
    if a.get("output"):
        argv += ["-o", _abs(a["output"], base)]
    if cmd.inputs == "none":
        argv += ["--", str(a.get(cmd.text_arg, ""))]  # text may start with "-"
    return argv


def _default_dir() -> Path:
    """Where outputs go when a call names no folder: $SDEXE_OUTPUT_DIR, else the
    client's working folder, else ~/Downloads (desktop clients often start
    servers in /, which is not writable)."""
    env = os.environ.get("SDEXE_OUTPUT_DIR")
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd()
    if str(cwd) != "/" and os.access(cwd, os.W_OK):
        return cwd
    return Path.home() / "Downloads"


# ── Server ──

class Server:
    def __init__(self):
        self.out_lock = threading.Lock()
        self.procs = {}
        self.base = _default_dir()

    def send(self, msg: dict):
        line = json.dumps(msg, ensure_ascii=False)
        with self.out_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def reply(self, id_, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": id_}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result
        self.send(msg)

    def handle(self, msg: dict):
        method, id_ = msg.get("method"), msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            asked = params.get("protocolVersion")
            self.reply(id_, {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "sdexe", "title": "sdexe", "version": __version__},
                "instructions": INSTRUCTIONS,
            })
        elif method == "ping":
            self.reply(id_, {})
        elif method == "tools/list":
            self.reply(id_, {"tools": tool_definitions()})
        elif method == "tools/call":
            threading.Thread(target=self.call, args=(id_, params), daemon=True).start()
        elif method == "notifications/cancelled":
            proc = self.procs.get(params.get("requestId"))
            if proc:
                proc.kill()
        elif id_ is not None and not (method or "").startswith("notifications/"):
            self.reply(id_, error={"code": -32601, "message": f"Method not found: {method}"})

    def call(self, id_, params):
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            argv = tool_argv(name, args, self.base)
        except KeyError:
            self.reply(id_, error={"code": -32602, "message": f"Unknown tool: {name}"})
            return
        self.base.mkdir(parents=True, exist_ok=True)
        # --json must come before a "--" that ends the options.
        cut = argv.index("--") if "--" in argv else len(argv)
        cmd = [sys.executable, "-m", "sdexe", *argv[:cut], "--json", *argv[cut:]]
        try:
            proc = subprocess.Popen(cmd, cwd=self.base, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            self.procs[id_] = proc
            out, err = proc.communicate()
        finally:
            self.procs.pop(id_, None)

        try:
            doc = json.loads(out)
        except json.JSONDecodeError:
            # Usage errors (exit 2) print a one-line message on stderr, no JSON.
            text = (err or out or "sdexe produced no output").strip().splitlines()[-1]
            self.reply(id_, {"content": [{"type": "text", "text": text}], "isError": True})
            return
        self.reply(id_, {
            "content": [{"type": "text", "text": json.dumps(doc, indent=2, ensure_ascii=False)}],
            "structuredContent": doc,
            "isError": not doc.get("ok", False),
        })

    def serve(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                continue
            for m in (msg if isinstance(msg, list) else [msg]):
                if isinstance(m, dict):
                    self.handle(m)
        for proc in list(self.procs.values()):
            proc.kill()


MCP_HELP = """\
  [title]sdexe mcp[/title] [muted]· sdexe as an MCP server (stdio), so AI apps can call every tool[/muted]

  [brand]◆[/brand] [title]Add it to[/title]
    [brand2]Claude Code[/brand2]      [brand]claude mcp add -s user sdexe -- sdexe mcp[/brand]   [muted]or: sdexe settings[/muted]
    [brand2]Claude Desktop[/brand2]   [muted]claude_desktop_config.json:[/muted]
                     [faint]{{"mcpServers": {{"sdexe": {{"command": "{exe}", "args": ["mcp"]}}}}}}[/faint]
    [brand2]Cursor & others[/brand2]  [muted]command[/muted] [brand]{exe}[/brand][muted], args[/muted] [brand]mcp[/brand]

  [brand]◆[/brand] [title]{count} tools[/title]
    [muted]download, media_info, and every pdf / image / audio / video / convert / file command.
    Outputs go to the client's folder, or ~/Downloads when that isn't writable;
    SDEXE_OUTPUT_DIR changes it, and each call can pass "output".[/muted]
"""


def mcp_main(argv) -> int:
    if argv and argv[0] in ("-h", "--help"):
        import shutil
        from sdexe import ui
        exe = shutil.which("sdexe") or "sdexe"
        c = ui.console()
        c.print()
        c.print(MCP_HELP.format(exe=exe, count=len(tool_definitions())), soft_wrap=True)
        return 0
    if sys.stdin.isatty():
        print("sdexe mcp speaks MCP over stdin/stdout and is meant to be started by an AI app.\n"
              "Run `sdexe mcp --help` to see how to add it.", file=sys.stderr)
        return 2
    Server().serve()
    return 0


# ── Skill ──

def skill_markdown() -> str:
    lines = [
        "---",
        "name: sdexe",
        "description: Download video/audio from YouTube and 1000+ sites, and run local PDF, image, "
        "audio, video, data-conversion and file tools with the `sdexe` CLI. Use when asked to download "
        "media, get a video's info or available qualities, or to merge/split/compress/convert/trim/"
        "resize/watermark PDFs, images, audio or video, convert csv/json/yaml/xml/xlsx, or hash/zip files.",
        "---",
        "",
        "# sdexe",
        "",
        "Every command writes outputs to the current folder (or `-o PATH`) and never overwrites an "
        "existing file. Add `--json` for one machine-readable result document on stdout; otherwise "
        "stdout carries only saved paths (or the text, for text commands). Exit code 0 = all inputs "
        "succeeded, 1 = some failed, 2 = bad usage. Every command has `--help`.",
        "",
        "## Media downloads",
        "",
        "```",
        "sdexe download URL [URL ...]          # MP4, best stream up to 1080p60",
        "sdexe download URL -mp3               # MP3 320 kbps (also: -wav -flac -m4a -opus -webm -mkv)",
        "sdexe download URL -a                 # audio only, WAV (lossless)",
        "sdexe download URL -720p              # cap resolution (-1080p30, -4k, -1440p ...)",
        "sdexe download URL --best             # highest available, no cap",
        "sdexe download URL --start 1:30 --end 2:00 -o clip.mp4",
        "sdexe download PLAYLIST_URL --playlist --limit 20 -mp3",
        "sdexe info URL --json                 # qualities, sizes, chapters; dry run of download",
        "```",
        "",
        "If YouTube says to confirm you're not a bot or the video is age-restricted, retry with "
        "`--cookies-from-browser chrome` (or safari, firefox, brave, edge).",
        "",
        "## Local tools",
        "",
    ]
    for group in GROUPS:
        lines.append(f"### {group}")
        lines.append("")
        for c in (c for c in COMMANDS if c.group == group):
            opts = " ".join(
                (f"{a.flag} {'|'.join(map(str, a.choices)) if a.choices and len(a.choices) <= 5 else a.dest.upper()}"
                 if a.type is not bool else a.flag) if a.required else
                (f"[{a.flag}]" if a.type is bool else f"[{a.flag} {a.dest.upper()}]")
                for a in c.args)
            lines.append(f"- `sdexe {c.full} {c.inputs_help}{(' ' + opts) if opts else ''}`: {c.summary}")
        lines.append("")
    return "\n".join(lines)


def skill_main(argv) -> int:
    text = skill_markdown()
    if argv and argv[0] in ("-h", "--help"):
        print("sdexe skill            print a Claude Code skill (SKILL.md) describing every command\n"
              "sdexe skill --install  save it to ~/.claude/skills/sdexe/SKILL.md so Claude Code picks it up")
        return 0
    if argv and argv[0] == "--install":
        dest = Path.home() / ".claude" / "skills" / "sdexe" / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        print(dest)
        return 0
    sys.stdout.write(text)
    return 0
