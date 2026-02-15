# sdexe

Local tools for media downloads, PDF manipulation, image processing, and file conversion. Everything runs on your machine -- no uploads, no accounts.

## Install

```
pip install sdexe
```

Or with [pipx](https://pipx.pypa.io/):

```
pipx install sdexe
```

### Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) (for media downloads)

## Usage

```
sdexe
```

This starts the server on `http://localhost:5001` and opens it in your browser.

## Features

- **Media Downloader** -- YouTube, Instagram, TikTok, SoundCloud, and 1000+ sites. Formats: MP3, MP4, FLAC, WAV. Playlist and batch support.
- **PDF Tools** -- Merge, split, and images-to-PDF.
- **Image Tools** -- Resize, compress, and convert between PNG/JPG/WebP.
- **File Converter** -- Markdown to HTML, CSV to JSON, JSON to CSV.

## Development

```
git clone https://github.com/gedaliahs/sdexe.git
cd sdexe
python -m venv venv
source venv/bin/activate
pip install -e .
sdexe
```
