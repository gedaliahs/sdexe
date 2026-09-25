"""sdexe's terminal look: palette, wordmark, and the few building blocks every
screen is made from. Everything that prints for a person goes through here, so
the accent setting recolours all of it at once.

The look is mostly black, white and grays, with one accent colour used
sparingly: selection, the main action, progress, key hints.

Markup styles every sdexe console understands:
  brand           the accent (use little of it)
  brand2          light gray: arguments, flags, placeholders
  muted, faint    secondary and tertiary text
  ok, warn, err   outcomes
  cmd             something to type
  key             a keyboard key, in hints
"""

import sys

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich import box

# One colour each. Everything else is grayscale.
ACCENTS = {
    "orange": "#f0883e",
    "white": "#f2f2f2",
    "green": "#5fcf8a",
    "violet": "#a38bf0",
    "blue": "#6aa5f0",
    "pink": "#f07aaa",
}
DEFAULT_ACCENT = "orange"

# The grays.
TEXT = "#e6e6e6"
LIGHT = "#bdbdbd"
MUTED = "#8c8c8c"
FAINT = "#5a5a5a"
LINE = "#2c2c2c"

OK, WARN, ERR = "✓", "!", "✗"
BULLET = "◆"

# SDEXE in a two-row block face.
_WORDMARK = (
    "█▀▀ █▀▄ █▀▀ ▀▄▀ █▀▀",
    "▄▄█ █▄▀ ██▄ █ █ ██▄",
)

_accent_cache = None


def accent_name() -> str:
    global _accent_cache
    if _accent_cache is None:
        try:
            from sdexe.app import load_config
            name = load_config().get("accent", DEFAULT_ACCENT)
        except Exception:
            name = DEFAULT_ACCENT
        _accent_cache = name if name in ACCENTS else DEFAULT_ACCENT
    return _accent_cache


def set_accent(name: str):
    global _accent_cache
    _accent_cache = name if name in ACCENTS else DEFAULT_ACCENT


def accent() -> str:
    return ACCENTS[accent_name()]


def colors() -> tuple:
    """(accent, light gray): the two colours sdexe draws with."""
    return accent(), LIGHT


def theme() -> Theme:
    a = accent()
    return Theme({
        "brand": a,
        "brand2": LIGHT,
        "brand.bold": f"bold {a}",
        "link": f"underline {TEXT}",
        "ok.bold": "bold #6fcf8f",
        "muted": MUTED,
        "faint": FAINT,
        "ok": "#6fcf8f",
        "warn": "#e8b04a",
        "err": "#ef6f6f",
        "cmd": TEXT,
        "key": f"bold {a}",
        "title": "bold",
    })


def console(stderr: bool = False, **kwargs) -> Console:
    c = Console(stderr=stderr, theme=theme(), highlight=False, **kwargs)
    if not c.is_terminal and "width" not in kwargs:
        c.width = 200  # piped: don't hard-wrap messages at 80 columns for scripts and agents
    return c


# ── Pieces ──

def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def gradient(text: str, start: str | None = None, end: str | None = None, bold: bool = False) -> Text:
    """Colour text along the accent gradient, left to right."""
    a, b = (start, end) if start else colors()
    (r1, g1, b1), (r2, g2, b2) = _hex(a), _hex(b)
    out = Text()
    n = max(len(text) - 1, 1)
    for i, ch in enumerate(text):
        t = i / n
        col = f"#{int(r1 + (r2 - r1) * t):02x}{int(g1 + (g2 - g1) * t):02x}{int(b1 + (b2 - b1) * t):02x}"
        out.append(ch, style=f"{'bold ' if bold else ''}{col}")
    return out


def wordmark(tagline: str | None = None, version: str | None = None, indent: int = 2) -> Text:
    """The two-row SDEXE mark, in plain white, with the version and a tagline beside it."""
    lines = []
    for row, right in zip(_WORDMARK, (version or "", tagline or "")):
        line = Text(" " * indent)
        line.append(row, style=TEXT)
        if right:
            line.append("   ")
            line.append(right, style="muted" if row is _WORDMARK[1] else "faint")
        lines.append(line)
    return Text("\n").join(lines)


def header(c: Console, subtitle: str | None = None):
    """Wordmark on a terminal; a plain one-line title when piped, so logs and
    agents don't get block characters."""
    from sdexe import __version__
    if c.is_terminal:
        c.print()
        c.print(wordmark(subtitle or "local tools for media, PDF, images & files", f"v{__version__}"))
    else:
        c.print(f"sdexe v{__version__}" + (f" · {subtitle}" if subtitle else ""))


def section(title: str) -> Text:
    return Text.assemble(("  ", ""), (title, "title"))


def cmd(line: str) -> Text:
    """A command as sdexe prints it: `sdexe` faint, the command in white,
    placeholders and flags in light gray."""
    t = Text()
    for i, tok in enumerate(line.split(" ")):
        if i:
            t.append(" ")
        if tok == "sdexe":
            style = "cmd" if line.strip() == "sdexe" else "faint"
        elif tok.startswith(("<", "[", '"', "-", "…")) or tok in ("|", "...") or (tok.isupper() and len(tok) > 1):
            style = "brand2"
        else:
            style = "cmd"
        t.append(tok, style=style)
    return t


def rows(items: list, key_width: int | None = None, indent: int = 4, commands: bool = True) -> Table:
    """Two-column (thing, description) rows, the shape of every list sdexe
    prints. Pass the same key_width to line up several lists on one screen."""
    t = Table.grid(padding=(0, 3))
    t.add_column(no_wrap=True, min_width=key_width)
    t.add_column(style="muted")
    for k, v in items:
        t.add_row(cmd(k) if commands and isinstance(k, str) else k, v)
    return _indent(t, indent)


def _indent(renderable, n: int):
    from rich.padding import Padding
    return Padding(renderable, (0, 0, 0, n))


def keys(*pairs) -> Text:
    """Keyboard hints: keys(("↑↓", "move"), ("enter", "change"))."""
    t = Text("  ")
    for i, (k, what) in enumerate(pairs):
        if i:
            t.append("   ")
        t.append(k, style="key")
        t.append(f" {what}", style="muted")
    return t


def card(body, title: str | None = None, style: str = "faint", padding=(1, 2), expand: bool = False) -> Panel:
    return Panel(body, title=Text(f" {title} ", style="brand.bold") if title else None, title_align="left",
                 border_style=style, box=box.ROUNDED, padding=padding, expand=expand)


def status(ok: bool | None) -> Text:
    if ok is None:
        return Text(WARN, style="warn")
    return Text(OK, style="ok") if ok else Text(ERR, style="err")


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
