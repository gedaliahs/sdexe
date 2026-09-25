# sdexe

**Suite for Downloading, Editing & eXporting Everything**

[![PyPI version](https://img.shields.io/pypi/v/sdexe)](https://pypi.org/project/sdexe/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/sdexe)](https://pypi.org/project/sdexe/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Local tools for media downloads, PDF manipulation, image processing, and file conversion. Everything runs on your machine. No uploads, no accounts, no data leaves your device.

## Install

One command sets up everything on a fresh machine (Homebrew on macOS, Python 3.12, ffmpeg, then sdexe in its own private environment at `~/.sdexe`). Safe to re-run.

macOS / Linux:

```
curl -fsSL https://sdexe.com/install.sh | bash
```

Windows (PowerShell):

```
irm https://sdexe.com/install.ps1 | iex
```

Already have Python 3.10+? Then just:

```
pip install sdexe
```

(Or into a venv of your choice. pipx works too.)

### Update

```
sdexe update
```

Upgrades sdexe and its downloader engine in place. The Settings page has a button that does the same.

### Requirements

- Python 3.10+ (the installer handles this)
- [ffmpeg](https://ffmpeg.org/): installed by the installer; otherwise sdexe falls back to a bundled copy and offers to install the full one on first run

## Usage

```
sdexe
```

Starts the web app at `http://localhost:5001`. All processing happens locally. The first run asks a few setup questions: whether `sdexe` should open the browser each time (also a toggle in Settings; `--browser` / `--no-browser` override it for one run), whether to fix zsh's handling of `?` in links, and whether to connect Claude Code. Run `sdexe setup` to change the answers.

New to it? `sdexe tutorial` is a hands-on, 3-minute walkthrough that runs real commands.

> **zsh users:** quote links (`sdexe download "https://youtube.com/watch?v=..."`), or let `sdexe setup` add `alias sdexe='noglob sdexe'` so you don't have to. Without either, zsh stops with "no matches found" before sdexe runs.

### Download from the terminal

```
sdexe download <url> [url ...] [format] [quality] [options]
```

Saves straight to the current folder, no browser or server needed. Built to be driven by scripts and AI agents as well as by hand: saved paths go to stdout, progress and errors to stderr, and the exit code is 0 only when every link saved.

| You type | You get |
|---|---|
| `sdexe download URL` | MP4, best stream up to 1080p60 |
| `sdexe download URL -mp3` | MP3, 320 kbps |
| `sdexe download URL -a` | WAV (lossless) |
| `sdexe download URL --best` | Highest available video: 4K/8K, top fps and bitrate |
| `sdexe download URL -720p` | Up to 720p (`-1080p30`, `-4k`, `-1440p` also work) |
| `sdexe download URL1 URL2 URL3 -flac` | A batch, 3 at a time |
| `sdexe download URL --playlist` | Every video in a playlist or channel (`--limit N` for the first N) |
| `sdexe download URL --start 1:30 --end 2:00` | Only that section |
| `sdexe download URL -o ~/Music/song.mp3` | A specific folder or file name |
| `sdexe download URL --json` | One JSON document with paths, sizes, resolution, errors |

Formats: `mp4`, `webm`, `mkv` for video; `wav`, `mp3`, `flac`, `m4a`, `opus` for audio. Tags work as `-mp3`, `--mp3`, `mp3` or `-f mp3`. Run `sdexe download --help` for everything.

`sdexe info URL` shows the title, length, every available quality with sizes, chapters and subtitles without downloading. It takes the same tags, so `sdexe info URL -720p` is a dry run of `sdexe download URL -720p`.

### Every tool from the terminal

The PDF, image, audio, video and conversion tools work from the command line too, with the same conventions: outputs land in the current folder as `<name>-<action>.<ext>`, nothing is overwritten, `--json` gives one result document, and several files can be passed at once.

```
sdexe pdf merge a.pdf b.pdf -o book.pdf
sdexe pdf text report.pdf > report.txt
sdexe image resize *.jpg --width 1200
sdexe image convert IMG_0001.heic -f jpg
sdexe audio trim podcast.mp3 --start 1:00 --end 2:30
sdexe video gif clip.mp4 --width 480
sdexe convert data.csv -f json
sdexe file hash installer.dmg
```

Run `sdexe pdf`, `sdexe image`, `sdexe audio`, `sdexe video`, `sdexe convert --help` or `sdexe file` to list the commands in each group.

### Use it from AI agents

Agents can call the CLI directly. Two ways to make it discoverable:

```
claude mcp add sdexe -- sdexe mcp      # MCP server: every command becomes a tool (Claude Code, Desktop, Cursor)
sdexe skill --install                  # or a Claude Code skill describing every command
```

`sdexe mcp --help` shows the Claude Desktop config. MCP outputs go to the client's working folder (or `~/Downloads`); set `SDEXE_OUTPUT_DIR` to change it.

## Features

### Media Downloader
Download videos and audio from YouTube, Instagram, TikTok, SoundCloud, Twitch, Vimeo, X, and 1000+ other sites.
- Formats: MP3 (128/192/320 kbps), MP4, FLAC, WAV
- Quality options: Best, 1080p, 720p, 480p for video
- Playlist and batch URL support (up to 3 concurrent downloads)
- Subtitle download for MP4
- Thumbnail embedded as album art
- Set a permanent output folder to skip manual saving
- Real-time progress with speed, ETA, and cancel button
- Desktop notifications when downloads finish
- Download history with re-fetch button

### PDF Tools
- **Merge**: combine multiple PDFs, drag to reorder
- **Split**: split by page ranges (e.g. `1-3, 5, 8-10`) or every page
- **Images to PDF**: convert JPG/PNG/WebP images into a single PDF
- **Compress**: reduce file size by compressing content streams
- **Extract Text**: pull all text to a .txt file with page markers
- **Password**: add or remove PDF password protection

### Image Tools
- **Resize**: by dimensions or percentage, with aspect ratio lock
- **Compress**: batch compression at High / Medium / Low quality
- **Convert**: convert between PNG, JPG, and WebP (batch supported)

### File Converter
- **Markdown → HTML**: live preview + styled standalone HTML output
- **CSV ↔ JSON**: bidirectional, first row as headers
- **JSON ↔ YAML**: bidirectional
- **CSV ↔ TSV**: bidirectional
- **XML → JSON**

## Development

```
git clone https://github.com/gedaliahs/sdexe.git
cd sdexe
python -m venv venv
source venv/bin/activate
pip install -e .
sdexe
```
