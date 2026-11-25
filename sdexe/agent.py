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
import signal
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
    "are returned. Use search to find media by name, media_info to see qualities, then download."
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
                "audio_only": {"type": "boolean"},
                "playlist": {"type": "boolean", "description": "list every entry of a playlist"},
                "limit": {"type": "integer", "minimum": 1},
                "cookies_from_browser": {"type": "string",
                                         "description": "chrome, safari, firefox, brave or edge"},
            },
            "required": ["urls"],
        },
    }


def _search_tool():
    return {
        "name": "search",
        "title": "Search for media",
        "description": ("Find videos or songs by name on YouTube or SoundCloud. Returns titles, channels, "
                        "durations and links to pass to `download`."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what to look for"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "source": {"type": "string", "enum": ["youtube", "soundcloud"], "default": "youtube"},
            },
            "required": ["query"],
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
        if arg.min is not None:
            schema["minimum"] = arg.min
        if arg.max is not None:
            schema["maximum"] = arg.max
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
    return [_search_tool(), _download_tool(), _info_tool()] + [_cmd_tool(c) for c in COMMANDS]


_CMD_BY_TOOL = {c.tool_name: c for c in COMMANDS}


# ── Turning a tool call into CLI arguments ──

def _abs(p: str, base: Path) -> str:
    path = Path(os.path.expanduser(p))
    return str(path if path.is_absolute() else base / path)


class ToolInputError(ValueError):
    """A tool call's arguments don't fit the tool's schema."""


def _as_list(value, field: str) -> list:
    """Arrays of strings. A lone string is one item, not a list of characters."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
        return [str(v) for v in value]
    raise ToolInputError(f"{field} must be a list of strings")


def _opt(flag: str, value) -> str:
    """--flag=value, so a value starting with "-" (watermark text "-DRAFT-", a
    search for "-ve") isn't read as another option."""
    # JSON has one number type: 100.0 is a valid integer there, but "100.0"
    # is not one to the command line.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{flag}={value}"


def tool_argv(name: str, a: dict, base: Path) -> list:
    if not isinstance(a, dict):
        raise ToolInputError("arguments must be an object")
    if name == "search":
        query = str(a.get("query") or "").strip()
        if not query:
            raise ToolInputError("query is required")
        return ["search", _opt("--limit", int(a.get("limit") or 10)),
                _opt("--source", a.get("source") or "youtube"), "--", query]
    if name in ("download", "media_info"):
        urls = _as_list(a.get("urls"), "urls")
        if not urls:
            raise ToolInputError("urls is required")
        argv = ["download" if name == "download" else "info"]
        if a.get("format"):
            argv.append(_opt("--format", a["format"]))
        if a.get("quality"):
            argv.append(_opt("--quality", a["quality"]))
        if a.get("audio_only"):
            argv.append("--audio")
        if a.get("playlist"):
            argv.append("--playlist")
        if a.get("limit"):
            argv.append(_opt("--limit", int(a["limit"])))
        if a.get("cookies_from_browser"):
            argv.append(_opt("--cookies-from-browser", a["cookies_from_browser"]))
        if name == "download":
            for key in ("start", "end"):
                if a.get(key):
                    argv.append(_opt(f"--{key}", a[key]))
            if a.get("output"):
                argv.append(_opt("--output", _abs(str(a["output"]), base)))
        # After "--", so a link can never be read as an option (-i FILE, -o PATH).
        return argv + ["--", *urls]

    cmd = _CMD_BY_TOOL.get(name)
    if not cmd:
        raise KeyError(name)
    argv = cmd.full.split()
    if cmd.inputs != "none":
        files = _as_list(a.get("files"), "files")
        if not files:
            raise ToolInputError("files is required")
        argv += [_abs(f, base) for f in files]
    for arg in cmd.args:
        if arg.dest not in a or a[arg.dest] is None:
            continue
        if arg.type is bool:
            if a[arg.dest]:
                argv.append(arg.flag)
        else:
            argv.append(_opt(arg.flag, a[arg.dest]))
    if a.get("output"):
        argv.append(_opt("--output", _abs(str(a["output"]), base)))
    if cmd.inputs == "none":
        text = a.get(cmd.text_arg)
        if text is None or str(text) == "":
            raise ToolInputError(f"{cmd.text_arg} is required")
        argv += ["--", str(text)]  # text may start with "-"
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

def _signal_tree(proc, force: bool = False):
    """Stop a tool call and everything it started (ffmpeg, a JS runtime):
    SIGTERM, or SIGKILL with force."""
    try:
        if os.name == "posix":
            # Each call runs in its own process group.
            os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
        elif force:
            proc.kill()
        else:
            proc.terminate()
    except OSError:
        pass  # already gone


class Server:
    def __init__(self):
        self.out_lock = threading.Lock()
        self.lock = threading.Lock()
        self.procs = {}         # request id -> running tool process
        self.running = set()    # ids of tools/call requests not answered yet
        self.cancelled = set()  # of those, the ones the client cancelled
        self.base = _default_dir()

    def send(self, msg: dict):
        line = json.dumps(msg, ensure_ascii=False)
        with self.out_lock:
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass  # the client closed its end; stdin closes next and ends the loop

    def reply(self, id_, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": id_}
        if error:
            msg["error"] = error
        else:
            msg["result"] = result
        self.send(msg)

    def handle(self, msg: dict):
        method, id_ = msg.get("method"), msg.get("id")
        if not isinstance(method, str):
            # A response (to a request this server never makes) needs no answer.
            if "result" not in msg and "error" not in msg:
                self.reply(id_, error={"code": -32600, "message": "Invalid Request"})
            return
        params = msg.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            if id_ is not None:
                self.reply(id_, error={"code": -32602, "message": "params must be an object"})
            return
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
            with self.lock:
                self.running.add(id_)
            threading.Thread(target=self.call, args=(id_, params), daemon=True).start()
        elif method == "notifications/cancelled":
            self.cancel(params.get("requestId"))
        elif id_ is not None and not method.startswith("notifications/"):
            self.reply(id_, error={"code": -32601, "message": f"Method not found: {method}"})

    def cancel(self, id_):
        with self.lock:
            if id_ not in self.running:
                return
            # Remembered, because the process may not have started yet.
            self.cancelled.add(id_)
            proc = self.procs.get(id_)
        if proc:
            self._stop(proc)

    def _stop(self, proc, grace: float = 3.0):
        """SIGTERM first: sdexe treats it like Ctrl+C and removes its temp
        files. SIGKILL for whatever is still there after the grace period."""
        _signal_tree(proc)

        def finish():
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                _signal_tree(proc, force=True)

        threading.Thread(target=finish, daemon=True).start()

    def call(self, id_, params):
        # Every request gets an answer: an exception here used to end the
        # thread silently and leave the client waiting forever.
        try:
            self._call(id_, params)
        except Exception as e:  # noqa: BLE001
            self.reply(id_, {"content": [{"type": "text", "text": f"sdexe failed: {e}"}], "isError": True})
        finally:
            with self.lock:
                self.running.discard(id_)
                self.cancelled.discard(id_)

    def _call(self, id_, params):
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            argv = tool_argv(name, args, self.base)
        except KeyError:
            self.reply(id_, error={"code": -32602, "message": f"Unknown tool: {name}"})
            return
        except (ToolInputError, ValueError, TypeError) as e:
            self.reply(id_, {"content": [{"type": "text", "text": f"Invalid arguments: {e}"}], "isError": True})
            return
        self.base.mkdir(parents=True, exist_ok=True)
        # --json must come before a "--" that ends the options.
        cut = argv.index("--") if "--" in argv else len(argv)
        # The file tools start through sdexe.cli_tools, which skips loading the
        # web app: about 0.1 s a call instead of 0.25.
        module = "sdexe.cli_tools" if name in _CMD_BY_TOOL else "sdexe"
        cmd = [sys.executable, "-m", module, *argv[:cut], "--json", *argv[cut:]]
        try:
            # Its own process group, so a cancel reaches the ffmpeg it started
            # too. UTF-8 both ways: file names and titles in the JSON.
            proc = subprocess.Popen(cmd, cwd=self.base, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                    start_new_session=os.name == "posix")
            with self.lock:
                self.procs[id_] = proc
                cancelled = id_ in self.cancelled
            if cancelled:
                self._stop(proc)
            out, err = proc.communicate()
        finally:
            with self.lock:
                self.procs.pop(id_, None)
                cancelled = id_ in self.cancelled
        if cancelled:
            return  # the client stopped waiting; a cancelled request gets no response

        try:
            doc = json.loads(out)
        except json.JSONDecodeError:
            doc = None
        if not isinstance(doc, dict):
            lines = (err or out).strip().splitlines()
            text = lines[-1] if lines else "sdexe produced no output"
            self.reply(id_, {"content": [{"type": "text", "text": text}], "isError": True})
            return
        self.reply(id_, {
            "content": [{"type": "text", "text": json.dumps(doc, indent=2, ensure_ascii=False)}],
            "structuredContent": doc,
            "isError": not doc.get("ok", False),
        })

    def serve(self):
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    self.send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
                    continue
                for m in (msg if isinstance(msg, list) and msg else [msg]):
                    if not isinstance(m, dict):
                        self.send({"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32600, "message": "Invalid Request"}})
                        continue
                    try:
                        self.handle(m)
                    except Exception as e:  # noqa: BLE001 - one bad message must not end the server
                        if m.get("id") is not None:
                            self.reply(m["id"], error={"code": -32603, "message": f"Internal error: {e}"})
        finally:
            self.shutdown()

    def shutdown(self, grace: float = 3.0):
        """The client went away: stop every tool still running, ffmpeg included."""
        with self.lock:
            procs = list(self.procs.values())
        for proc in procs:
            _signal_tree(proc)
        for proc in procs:
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                _signal_tree(proc, force=True)


MCP_HELP = """\
  [title]sdexe mcp[/title] [muted]· sdexe as an MCP server (stdio), so AI apps can call every tool[/muted]

  [brand]◆[/brand] [title]Add it to[/title]
    [brand2]Claude Code[/brand2]      [brand]claude mcp add -s user sdexe -- sdexe mcp[/brand]   [muted]or: sdexe settings[/muted]
    [brand2]Claude Desktop[/brand2]   [muted]claude_desktop_config.json:[/muted]
                     [faint]{{"mcpServers": {{"sdexe": {{"command": "{exe}", "args": ["mcp"]}}}}}}[/faint]
    [brand2]Cursor & others[/brand2]  [muted]command[/muted] [brand]{exe}[/brand][muted], args[/muted] [brand]mcp[/brand]

  [brand]◆[/brand] [title]{count} tools[/title]
    [muted]search, download, media_info, and every pdf / image / audio / video / convert / file command.
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
    # MCP is UTF-8 whatever the locale says (Windows defaults to cp1252, where
    # a title in Japanese ended the reply with a UnicodeEncodeError).
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    from sdexe.cli import _interrupt_on_sigterm
    _interrupt_on_sigterm()  # so `kill` runs shutdown() below, like stdin closing does
    try:
        Server().serve()
    except KeyboardInterrupt:
        return 130
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
        "Every command writes outputs to the current folder (or `-o PATH`) and picks a new name "
        "rather than overwrite an existing file; only an exact `-o FILE` name is written as given, "
        "and never over an input. Add `--json` for one machine-readable result document on stdout; "
        "otherwise stdout carries only saved paths (or the text, for text commands). Exit code 0 = "
        "all inputs succeeded, 1 = some failed, 2 = bad usage, 130 = interrupted. Every command has "
        "`--help`.",
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
        "sdexe search \"WORDS\" --json           # find links by name (YouTube; -s soundcloud)",
        "sdexe download \"ytsearch:WORDS\" -mp3  # download the top search hit in one step",
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
