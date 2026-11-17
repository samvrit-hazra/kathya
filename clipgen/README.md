# 🎬 ClipGenerator — AI-Powered Video Clip Generator (CLI)

> Transform long-form videos (podcasts, documentaries, educational lectures, interviews) into high-retention social clips with word-synchronized subtitles for YouTube Shorts, Instagram Reels, and TikTok.

100% Free • Open Source • Python CLI • Powered by Groq Cloud AI

---

## 🌟 Features

- **⚡ AI Highlight Discovery & Scoring** — analyzes the full transcript with Groq's fast LLM to find hooks, revelations and memorable moments.
- **💡 AI Editorial Rationale** — each clip comes with a detailed "why this moment" explanation in the output manifest.
- **🎙️ Word-Level Timestamps** — Groq Whisper (`whisper-large-v3`) with a local `faster-whisper` fallback.
- **🔥 Burned Captions** — groups words into readable 4-word caption cards and burns them into the video with high-contrast styling.
- **📱 Dual Aspect Ratios** — 16:9 landscape plus 9:16 portrait with a blurred-background canvas for Reels/Shorts/TikTok.
- **🧾 JSON Manifest** — titles, reasons, timestamps and output file names written to `clips.json` next to the MP4s.
- **🚀 No External Services** — no web server, Redis or Celery required.

> The `frontend/` folder is kept for reference but is not used by the CLI.

> **In this Kathya checkout:** settings come from the repo-root `.env`, shared by
> every tool. `clipgen/.env` was removed; its keys were merged into the root
> file. Kathya calls `kathya_cli.py`, which runs this CLI and packs the
> generated folder into a ZIP for download.

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| CLI | Python `argparse` (`python run.py VIDEO`) |
| LLM Inference | Groq API (`openai/gpt-oss-120b`, LLaMA fallbacks) |
| Speech-to-Text | Groq Whisper + local `faster-whisper` fallback |
| Video Editing | FFmpeg (system binary or `imageio-ffmpeg`) |
| Configuration | `.env` via `pydantic-settings` |

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.10–3.13
- A free Groq API key from [console.groq.com](https://console.groq.com)
- FFmpeg (system install or `imageio-ffmpeg`)

### 2. Install dependencies
```bash
python -m pip install -r requirements.txt
```
*(Windows: double-click `install.bat`)*

### 3. Configure credentials
```bash
cp .env.example .env
```
Set your key in `.env`:
```ini
GROQ_API_KEY=gsk_your_api_key_here
```

### 4. Run the CLI
```bash
python run.py podcast.mp4
```

This clean copy reuses the virtual environment in the parent project folder. From this directory, run it with `../.venv/bin/python run.py ...`, or activate it first with `source ../.venv/bin/activate` (Windows: `..\.venv\Scripts\activate`) and then use plain `python run.py ...`.

---

## 💻 Usage

```
python run.py VIDEO [options]
```

One video per command. Examples:

```bash
# Basic run — writes to outputs/podcast/
python run.py podcast.mp4

# Custom output folder, at most 3 clips, skip portrait versions
python run.py talk.mkv -o ./clips --max-clips 3 --no-portrait

# Force local transcription (no Groq API needed for Whisper)
python run.py interview.mp4 --local-whisper

# Re-run into an existing output folder and show debug logs
python run.py podcast.mp4 --force -v
```

### Options

| Option | Description |
|---|---|
| `VIDEO` | Path to the source video (`.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.flv`, `.wmv`) |
| `-o`, `--output-dir DIR` | Output folder (default: `outputs/<video name>`) |
| `--model MODEL` | Override `GROQ_MODEL` from `.env` |
| `--whisper-model MODEL` | Override `GROQ_WHISPER_MODEL` from `.env` |
| `--local-whisper` | Transcribe with local `faster-whisper` instead of Groq |
| `--no-portrait` | Skip the 9:16 portrait versions |
| `--no-subtitles` | Skip burning subtitles |
| `--max-clips N` | Limit the number of generated clips |
| `--min-seconds SEC` | Minimum clip duration (default: 15) |
| `--max-seconds SEC` | Maximum clip duration (default: 90) |
| `--force` | Overwrite an existing output folder |
| `-v`, `--verbose` | Enable debug logging |

---

## 📁 Output

For `python run.py podcast.mp4`:

```
outputs/podcast/
├── 01_The_Hook_landscape.mp4
├── 01_The_Hook_portrait.mp4
├── 02_Core_Insight_landscape.mp4
├── 02_Core_Insight_portrait.mp4
└── clips.json
```

`clips.json` contains the source path, settings used, word count and one entry per clip:

```json
{
  "source": "/path/to/podcast.mp4",
  "created_at": "2026-11-17T19:35:00+00:00",
  "output_dir": "/path/to/outputs/podcast",
  "settings": {
    "llm_model": "openai/gpt-oss-120b",
    "whisper_model": "whisper-large-v3",
    "transcription": "groq",
    "subtitles": true,
    "portrait": true
  },
  "word_count": 4821,
  "clips": [
    {
      "index": 1,
      "title": "The Hook",
      "reason": "The speaker opens with a counterintuitive claim...",
      "start_seconds": 12.5,
      "end_seconds": 48.0,
      "duration_seconds": 35.5,
      "landscape": "01_The_Hook_landscape.mp4",
      "portrait": "01_The_Hook_portrait.mp4"
    }
  ]
}
```

---

## ⚙️ Configuration Reference

Settings live in the shared repo-root `.env` (this tool's own `.env` is ignored
here) and can be overridden per run with CLI flags:

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | `""` | Groq Cloud API key (required for cloud transcription/analysis) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | LLM used for clip selection |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3` | Whisper model used for transcription |
| `OUTPUTS_DIR` | `outputs` | Parent directory for per-video output folders |
| `WHISPER_MODEL_SIZE` | `base` | Local Whisper model size |
| `WHISPER_DEVICE` | `cpu` | Local Whisper device |
| `WHISPER_COMPUTE_TYPE` | `int8` | Local Whisper compute type |
| `FFMPEG_PATH` | unset | Custom FFmpeg binary path |

Without a valid `GROQ_API_KEY`, transcription uses local `faster-whisper` and clip selection uses a heuristic fallback (opening/midpoint segments).

---

## 📁 Repository Structure

```
ClipGenerator/
├── backend/
│   ├── cli.py                 # Argument parsing, manifest writing, user output
│   ├── config.py              # Pydantic settings loaded from .env
│   └── tasks/
│       ├── analyze.py         # AI transcript analysis & segment selection
│       ├── clip.py            # FFmpeg trimming & 9:16 portrait generation
│       ├── ffmpeg_utils.py    # FFmpeg locator/runner
│       ├── pipeline_runner.py # End-to-end processing pipeline
│       ├── subtitle.py        # Subtitle grouping & burning
│       └── transcribe.py      # Groq Whisper & local Whisper
├── frontend/                  # Legacy web UI (kept, unused by the CLI)
├── outputs/                   # Generated clips and manifests
├── .env.example               # Environment template
├── requirements.txt           # CLI dependencies
├── run.py                     # CLI entry point
├── run.bat                    # Windows launcher
└── install.bat                # Windows dependency installer
```

---

## 💡 Tips for Better Clips

1. Clear audio produces the most accurate word timestamps and hook selection.
2. Podcasts, interviews and explainers have rich material for AI clip discovery.
3. Use the portrait version for Reels/Shorts/TikTok, landscape for desktop YouTube.

---

## 📄 License

MIT
