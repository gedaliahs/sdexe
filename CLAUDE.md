# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development

```bash
python -m venv venv && source venv/bin/activate
pip install -e .
sdexe                    # starts at http://localhost:5001, opens browser
sdexe -p 8080            # custom port
sdexe --no-browser       # skip browser open
sdexe --no-tray          # skip system tray, Flask on main thread
```

Requires Python 3.10+ and ffmpeg (for AV operations/media downloads).

**Build & publish:**
```bash
python3 -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD=<token> python3 -m twine upload dist/*
```

No test suite, no linter config, no CI/CD.

## Architecture

Single Flask app serving a local-only web UI for media downloads, PDF tools, image processing, AV processing, file conversion, and text utilities.

**`sdexe/app.py`** — All Flask routes (page routes + `/api/*` endpoints), CLI entry point (`main()`), SSE progress streaming, system tray setup. This is a large single file (~1800 lines).

**`sdexe/tools.py`** — Pure functions for all tool operations (PDF, image, AV, convert, archive). No Flask imports. Called by `app.py` route handlers.

**`sdexe/__init__.py`** — Only contains `__version__`. Version must be kept in sync with `pyproject.toml`.

### Frontend

Vanilla JS, no bundler. One JS file per tool page: `app.js` (media), `pdf.js`, `images.js`, `convert.js`, `av.js`, `text.js`. Single `style.css`.

**Shared patterns across all tool pages:**
- **Hash routing** — `showTab()` function toggles `.pdf-section` visibility by `id="tab-{name}"`. Nav links use fragment URLs (e.g. `/images#resize`).
- **Drop zones** — `setupDropZone(zoneId, inputId, handler)` wires drag-and-drop + file input.
- These are copy-pasted identically in each JS file (not shared via import).

**Media page specifics:**
- Format/quality pill groups (`.pill-group` with `.pill[data-value]`) mirror hidden `<select>` elements
- SSE progress: `POST /api/download` → `{id}` → `EventSource(/api/progress/{id})` streams `{progress, status, detail}`
- Batch downloads run up to 3 concurrent workers via `Promise.all()`

### Templates

`base.html` provides nav (with dropdown menus linking to hash routes), footer, toast container, and version injection. Tool pages extend it via Jinja2 blocks. Version cache-busting: `style.css?v={{ version }}`.

### API Pattern

Routes follow: receive files/JSON → call `tools.py` function → return `send_file()` or JSON. Error handling wraps in try/except returning `jsonify({"error": str(e)}), 400`.

### Runtime

- Config/history stored in `~/.config/sdexe/`
- Downloads go to a temp directory (auto-cleaned on exit + hourly pruning)
- Rate limit on `/api/download`: 12 requests per 10-second sliding window
- Update mechanism: settings page calls `/api/update` which runs `pipx upgrade sdexe`
