# sdexe

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
- Formats: MP3 (320kbps), MP4, FLAC, WAV
- Quality options: Best, 1080p, 720p, 480p
- Playlist and batch URL support
- Subtitle download for MP4
- Thumbnail embedded as album art
- Set a permanent output folder to skip manual saving
- Real-time progress with speed and ETA

### PDF Tools
- **Merge** — combine multiple PDFs, drag to reorder
- **Split** — split by page ranges or every page individually
- **Images to PDF** — convert JPG/PNG/WebP images into a single PDF

### Image Tools
- **Resize** — by dimensions or percentage, with aspect ratio lock
- **Compress** — batch compression at High / Medium / Low quality
- **Convert** — convert between PNG, JPG, and WebP (batch supported)

### File Converter
- **Markdown → HTML** — converts to a styled standalone HTML file
- **CSV → JSON** — first row as headers
- **JSON → CSV** — expects an array of objects

## Development

```
git clone https://github.com/gedaliahs/sdexe.git
cd sdexe
python -m venv venv
source venv/bin/activate
pip install -e .
sdexe
```
