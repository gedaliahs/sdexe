# sdexe — Product Overview for Video Production

**Full name:** sdexe — Suite for Downloading, Editing & eXporting Everything
**Website:** https://github.com/gedaliahs/sdexe
**Install:** https://pypi.org/project/sdexe/
**License:** MIT (100% free, 100% open source, forever)

---

## What is sdexe?

sdexe is a local-first, privacy-focused toolkit that gives you 74 tools for working with media, PDFs, images, audio, video, text, and file conversion — all running entirely on your own computer. There are no servers, no cloud processing, no uploads, and no accounts. You install it with a single terminal command (`pipx install sdexe`), run it with `sdexe`, and a clean web interface opens in your browser at `localhost:5001`.

The entire application runs as a local Python server on your machine. When you drop a file into sdexe, that file never leaves your computer. When you process it, the processing happens on your CPU, using your RAM. The result is saved to your local file system. No data is transmitted anywhere. This is fundamentally different from every online tool like iLovePDF, Canva, CloudConvert, or any other web-based tool that requires you to upload your files to a third-party server.

sdexe requires Python 3.10+ and ffmpeg (for audio/video operations). It works on macOS, Linux, and Windows. Once installed, it works fully offline — the only feature that requires internet is the media downloader (because it needs to reach the source site to download from).

---

## The Problem sdexe Solves

Every day, millions of people need to do simple file operations: merge two PDFs, compress an image, trim a video, convert a CSV to JSON. The current solutions all have the same problems:

- **Privacy risk** — You're uploading personal documents, photos, and videos to servers you don't control. There's no guarantee your files are deleted after processing. Many services explicitly state they retain your data.
- **Paywalls and limits** — Most "free" tools limit you to a handful of operations per day, cap file sizes, or watermark your output unless you pay.
- **Account requirements** — You often need to create an account and hand over your email just to compress a PDF.
- **Ads and tracking** — Online tools are covered in ads, pop-ups, and tracking scripts. Some inject affiliate links or redirect you.
- **Speed** — Uploading a 200 MB video, waiting for server-side processing, then downloading the result is slow. Processing locally takes a fraction of the time.
- **Reliability** — Online tools go down, change their pricing, or shut down entirely. sdexe runs on your machine and doesn't depend on anyone else's servers.

sdexe eliminates all of these problems by running everything locally.

---

## Tool Categories — Full Breakdown

### Media Downloader (1 tool)

sdexe includes a full media downloader powered by yt-dlp. It supports downloading video and audio from over 1,000 websites including YouTube, Vimeo, Twitter/X, Reddit, TikTok, Instagram, SoundCloud, Bandcamp, Twitch, and hundreds more.

The interface lets you:
- Paste a URL and instantly see available formats (title, thumbnail, duration)
- Choose between video formats (MP4, WEBM, MKV) or audio-only (MP3, M4A, WAV, FLAC, OGG, OPUS)
- Select quality levels (best, 1080p, 720p, 480p, audio-only)
- Download multiple URLs at once with batch mode (up to 3 concurrent downloads)
- View real-time progress with percentage, speed, ETA, and file size
- Access download history to re-download or re-fetch previous files
- Configure a custom download folder

The download system uses server-sent events (SSE) for real-time progress updates, so you see exactly what's happening at every moment — no guessing, no stale progress bars.

### PDF Tools (14 tools)

A complete PDF toolkit comparable to what you'd find on iLovePDF, but entirely local:

- **Merge PDF** — Combine multiple PDF files into one. Drag and drop multiple files, reorder them, and merge. Handles any number of files.
- **Split PDF** — Extract specific pages from a PDF. Enter page ranges like "1-3, 5, 8-10" to create a new PDF with just those pages.
- **Compress PDF** — Reduce PDF file size by compressing internal streams. Shows before/after file size comparison.
- **Images to PDF** — Convert one or more images (JPEG, PNG, etc.) into a single PDF document. Maintains aspect ratios and arranges images as full pages.
- **Extract Text** — Pull all text content from a PDF as plain text. Useful for copying text from scanned or complex layouts.
- **Extract Images** — Extract all embedded images from a PDF as individual files, packaged in a ZIP.
- **Number Pages** — Add page numbers to every page of a PDF. Customize position (top/bottom, left/center/right), font size, starting number, and margin.
- **Password Protect** — Encrypt a PDF with a password. Recipients will need the password to open the file.
- **Unlock PDF** — Remove password protection from a PDF (requires you to know the current password).
- **Rotate Pages** — Rotate specific pages or all pages by 90, 180, or 270 degrees.
- **Watermark** — Add a text watermark across every page of a PDF. Configure the watermark text, font size, color, opacity, and rotation angle.
- **Reorder Pages** — Rearrange the page order of a PDF. Specify the new order as a list of page numbers.
- **Delete Pages** — Remove specific pages from a PDF.
- **Edit Metadata** — View and edit PDF metadata fields: title, author, subject, keywords, and creator.

### Image Tools (13 tools)

A comprehensive image processing suite powered by Pillow:

- **Resize** — Resize images by specifying exact width/height in pixels or by percentage. Option to maintain aspect ratio. Supports batch processing of multiple images at once.
- **Compress** — Reduce image file size with adjustable quality (0–100). Supports JPEG, PNG, and WebP output. Shows before/after size comparison with percentage saved.
- **Convert Format** — Convert between PNG, JPEG, and WebP formats. Handles all input image modes including palette, CMYK, RGBA, and grayscale.
- **Crop** — Crop images by specifying exact pixel coordinates (left, top, right, bottom). Interactive interface for defining the crop region.
- **Rotate** — Rotate images by any angle (90, 180, 270, or custom degrees).
- **Strip EXIF** — Remove all EXIF metadata from images. This removes GPS location data, camera info, timestamps, and other embedded metadata — important for privacy when sharing photos.
- **To ICO** — Convert any image to ICO format for use as favicons or application icons. Supports multiple sizes (16, 32, 48, 64, 128, 256 pixels).
- **Flip** — Mirror images horizontally or vertically.
- **Grayscale** — Convert any image to grayscale (black and white).
- **Blur** — Apply Gaussian blur with an adjustable radius.
- **QR Code** — Generate QR codes from any text or URL. Download as PNG.
- **Watermark** — Add text watermarks to images with configurable text, font size, opacity, and position.
- **Placeholder Image** — Generate placeholder images of any dimension with custom background color and text. Useful for design mockups and development.

All image tools handle exotic image modes gracefully — palette images (GIF), CMYK images (print files), RGBA (transparent), grayscale, and more. Files are automatically converted to the correct mode for the output format.

### Audio & Video (22 tools)

A full AV processing suite powered by ffmpeg:

**Audio tools (10):**
- **Convert Audio** — Convert between audio formats: MP3, WAV, OGG, FLAC, AAC, M4A, OPUS, WMA.
- **Trim Audio** — Cut audio to a specific time range with start and end timestamps.
- **Change Speed** — Speed up or slow down audio (0.25x to 4x) without changing pitch (using the atempo filter).
- **Extract Audio** — Extract the audio track from a video file as a separate audio file.
- **Merge Audio** — Concatenate multiple audio files into one.
- **Normalize Volume** — Automatically adjust audio volume to a consistent level using loudnorm normalization.
- **Reverse Audio** — Reverse an audio file so it plays backwards.
- **Change Pitch** — Shift audio pitch up or down by semitones while maintaining duration.
- **Audio Equalizer** — Apply bass, mid, and treble adjustments with a 3-band equalizer.
- **Audio Fade** — Add fade-in and/or fade-out effects with configurable duration.

**Video tools (12):**
- **Trim Video** — Cut video to a specific time range.
- **Compress Video** — Reduce video file size with adjustable CRF quality setting.
- **Convert Video** — Convert between video formats: MP4, WEBM, MOV, AVI, MKV.
- **Video to GIF** — Convert a video clip to an animated GIF with configurable FPS and dimensions.
- **Crop Video** — Crop video to a specific region by specifying width, height, X offset, and Y offset.
- **Rotate Video** — Rotate video by 90, 180, or 270 degrees.
- **Resize Video** — Scale video to new dimensions.
- **Reverse Video** — Reverse a video so it plays backwards.
- **Loop Video** — Create a looped version of a video with a configurable repeat count.
- **Mute Video** — Remove the audio track from a video.
- **Add Audio to Video** — Replace or add an audio track to a video file.
- **Burn Subtitles** — Hardcode SRT subtitles directly into a video file.

**Recording tools (2):**
- **Voice Recorder** — Record audio from your microphone directly in the browser using the MediaRecorder API. Live waveform visualization, timer, and download as WebM.
- **Screen Recorder** — Record your screen (full screen, window, or browser tab) using the Screen Capture API. Download as WebM.

### File Converter (9 tools)

Format conversion tools for data and archives:

- **Markdown to HTML** — Convert Markdown text to HTML with live preview. Supports full Markdown syntax including headers, lists, code blocks, tables, and links.
- **CSV to JSON** — Convert CSV data to JSON format. Auto-detects headers and data types.
- **JSON to CSV** — Convert JSON arrays to CSV format.
- **YAML to JSON** — Convert YAML configuration files to JSON.
- **JSON to YAML** — Convert JSON to YAML format.
- **CSV to/from TSV** — Convert between comma-separated and tab-separated values.
- **XML to JSON** — Convert XML documents to JSON format.
- **Create ZIP** — Bundle multiple files into a ZIP archive. Drag and drop files to add them.
- **Extract ZIP** — Extract all files from a ZIP archive. Downloads as individual files or as a directory listing.

### Text & Developer Tools (15 tools)

Utilities for text processing, encoding, and generation — all running client-side in the browser (no server calls needed):

- **Word Count** — Instant character, word, line, sentence, and paragraph count with reading time estimate.
- **Find & Replace** — Search and replace text with support for case sensitivity and whole-word matching.
- **Regex Tester** — Test regular expressions against sample text with live match highlighting. Shows all matches, capture groups, and match indices.
- **Text Diff** — Compare two blocks of text and see additions, deletions, and modifications highlighted inline.
- **Case Converter** — Convert text between UPPERCASE, lowercase, Title Case, Sentence case, camelCase, snake_case, and kebab-case.
- **Base64** — Encode text to Base64 or decode Base64 back to text.
- **Hash Generator** — Generate MD5, SHA-1, SHA-256, and SHA-512 hashes of any text.
- **URL Encode/Decode** — Percent-encode text for use in URLs, or decode percent-encoded strings.
- **JSON Formatter** — Beautify (pretty-print) or minify JSON with validation and error reporting.
- **JWT Decoder** — Decode JSON Web Tokens to see the header, payload, and signature. Shows expiration time and all claims.
- **UUID Generator** — Generate random UUIDs (v4) with one click. Bulk generate multiple UUIDs.
- **Timestamp Converter** — Convert between Unix timestamps and human-readable dates. Shows current time, supports milliseconds.
- **Lorem Ipsum** — Generate placeholder text with configurable paragraph and word count.
- **Color Converter** — Convert colors between HEX, RGB, and HSL formats with a live color preview and picker.
- **Password Generator** — Generate cryptographically random passwords with configurable length, character sets (uppercase, lowercase, numbers, symbols), and strength indicator.

---

## Technical Architecture

sdexe is a single-file Flask application with a clean separation between the web layer (`app.py`) and the processing layer (`tools.py`). The frontend is vanilla HTML/CSS/JavaScript with no build step, no frameworks, and no npm dependencies.

- **Backend:** Python 3.10+, Flask, Pillow (images), pypdf (PDFs), yt-dlp (media downloads), ffmpeg (audio/video)
- **Frontend:** Vanilla JavaScript, single CSS file, Jinja2 templates
- **UI pattern:** Drop zone for file input → process → download result
- **Progress:** Real-time SSE (server-sent events) for media downloads
- **Storage:** Temp directory with automatic cleanup (hourly pruning + cleanup on exit)
- **Config:** Stored in `~/.config/sdexe/` (download folder, settings, history)

---

## Key Selling Points

1. **100% local** — No servers, no cloud, no uploads. Your files never leave your machine.
2. **100% free** — No pricing tiers, no usage limits, no "premium" features locked behind a paywall. Everything is available to everyone.
3. **100% open source** — MIT licensed. Anyone can read the code, audit it, modify it, or contribute.
4. **No accounts** — No sign-up, no email, no login. Install and use.
5. **No ads, no tracking** — Zero analytics, zero telemetry, zero third-party scripts.
6. **Works offline** — Everything except the media downloader works without internet.
7. **No file size limits** — Process files of any size. The only limit is your computer's memory.
8. **74 tools in one** — Replaces iLovePDF, TinyPNG, CloudConvert, 4K Video Downloader, online regex testers, JSON formatters, and dozens of other tools.
9. **One command install** — `pipx install sdexe` and you're done. Auto-updates via the settings page.
10. **Cross-platform** — macOS, Linux, and Windows.

---

## Branding

- **Name:** sdexe (all lowercase, pronounced "sd-exe")
- **Tagline:** Suite for Downloading, Editing & eXporting Everything
- **Logo:** "sd" in white + "exe" in accent blue (#4285f4), displayed in the nav bar
- **Font:** Rubik (Google Fonts), weights 300–700
- **Primary color:** #4285f4 (blue)
- **Nav/dark areas:** #101114
- **Body:** #ffffff

**Category accent colors:**
| Category | Color | Hex |
|----------|-------|-----|
| Media | Orange | #ff5b29 |
| PDF | Red | #e65156 |
| Images | Cyan | #00a7f5 |
| Convert | Yellow | #ffd000 |
| AV | Purple | #8b5cf6 |
| Text | Green | #10b981 |

---

## Links

- **GitHub:** https://github.com/gedaliahs/sdexe
- **PyPI:** https://pypi.org/project/sdexe/
- **Install:** `pipx install sdexe`
- **Run:** `sdexe`
