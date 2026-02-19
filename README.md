# sdexe

**Suite for Downloading, Editing & eXporting Everything**

[![PyPI version](https://img.shields.io/pypi/v/sdexe)](https://pypi.org/project/sdexe/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/sdexe)](https://pypi.org/project/sdexe/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Local tools for media downloads, PDF manipulation, image processing, and file conversion. Everything runs on your machine — no uploads, no accounts, no data leaves your device.

## Install

```
pipx install sdexe
```

Or with pip:

```
pip install sdexe
```

### Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) — sdexe will offer to install it automatically on first run

## Usage

```
sdexe
```

Opens `http://localhost:5001` in your browser. All processing happens locally.

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
- **Merge** — combine multiple PDFs, drag to reorder
- **Split** — split by page ranges (e.g. `1-3, 5, 8-10`) or every page
- **Images to PDF** — convert JPG/PNG/WebP images into a single PDF
- **Compress** — reduce file size by compressing content streams
- **Extract Text** — pull all text to a .txt file with page markers
- **Password** — add or remove PDF password protection

### Image Tools
- **Resize** — by dimensions or percentage, with aspect ratio lock
- **Compress** — batch compression at High / Medium / Low quality
- **Convert** — convert between PNG, JPG, and WebP (batch supported)

### File Converter
- **Markdown → HTML** — live preview + styled standalone HTML output
- **CSV ↔ JSON** — bidirectional, first row as headers
- **JSON ↔ YAML** — bidirectional
- **CSV ↔ TSV** — bidirectional
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
