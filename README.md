# Kathya

One local app for storytelling tools. Run it, open the page, pick a tool, and use
it from the browser. Nothing else needs to be started: a tool runs only while it
is producing a result.

```bash
python3 app.py            # http://127.0.0.1:8000
python3 app.py --port 8080 --no-browser
```

The front page is a shelf of square tiles, one per tool. Clicking a tile opens
that tool's own page (`voiceover2video.html`), where the work happens. Both the
shelf and the tool pages are listed from [`registry.py`](./registry.py), so
adding a tool adds a tile.

## Deploying to Render

[`render.yaml`](./render.yaml) is a Blueprint for one Render web service. Push the
repo, choose **New > Blueprint** in Render, pick the repo, and supply
`GROQ_API_KEY` when prompted. Render's native Python runtime already includes
ffmpeg, so the build is just `pip install -r requirements.txt`.

A few limits are worth knowing before you use it:

- Keep the service at **one instance**; jobs are queued inside the process.
- `data/jobs/` is **ephemeral**: results vanish on deploy, restart, and free-tier
  spin-down. Download them when they finish.
- The free plan is 512 MB, and uploads are buffered in memory. Use the `1c-2g`
  plan (or lower `MAX_UPLOAD_BYTES` in `app.py`) for large files.
- There is no authentication, so a public URL lets anyone spend your Groq quota.
- If caption rendering fails with `No suitable TTF font found`, pass a font with
  `--caption-font` in the registry command or deploy via Docker with
  `fonts-dejavu-core`.

### Health endpoint and uptime monitors

`GET /api/health` returns a small JSON body and never touches the disk, so it is
cheap enough for frequent probes:

```json
{"status": "ok", "service": "kathya", "uptime": 128.4, "tools": 1,
 "jobs": {"running": 0, "queued": 0}}
```

Render's own health checks are internal probes: they gate deploys, but they do
**not** count as inbound traffic and will not stop a free instance from spinning
down after 15 idle minutes. An external monitor fixes that. With UptimeRobot:

1. **Add New Monitor** → monitor type **HTTP(s)**.
2. URL: `https://<your-service>.onrender.com/api/health`.
3. Interval: **5 minutes** (anything under 15 works).
4. Expect HTTP 200.

UptimeRobot sends a `HEAD` request by default, so `/api/health` answers `HEAD`
as well as `GET` (headers only, same status and `Content-Length`). If you want
the body checked too, switch the monitor type to **Keyword** and look for
`"status": "ok"`; that sends a real `GET`.

Either request wakes the service if it has already spun down — something the app
cannot do for itself — and resets the idle timer while it is up. A monitor every
10 minutes is enough; 5 just gives more slack.

Two things to keep in mind: keeping the service awake around the clock uses
roughly a month of the 750 free instance hours, and Render may still restart a
free instance at any time (which wipes `data/jobs/`). `healthCheckPath` in
`render.yaml` is set to `/api/health`, but that only gates deploys — it is the
monitor that keeps the instance warm.

## Voiceover to video

Upload a narration — audio or video — and get back an MP4 slideshow with your own
words as captions.

1. The narration is split into equal-length chunks, one slide per chunk (~1 slide
   per 6 seconds, clamped to 3–40 slides).
2. Each chunk is transcribed with **Groq Whisper**. The transcript is used
   verbatim as that slide's caption, so captions are the words actually spoken.
3. The transcript also goes to **Groq**, which returns a single image keyword for
   that slide.
4. Each slide is rendered with a **Wikimedia Commons** image (landscape only) or a
   fallback colour slide, concatenated, and the full voiceover is muxed over the
   result.

The finished file can be previewed and downloaded from the page. It lives in
`data/jobs/<id>/output/` until the last 20 jobs are pruned, or Kathya restarts.

## Setup

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env        # then set GROQ_API_KEY in .env
```

Kathya loads `.env` from the repository root automatically, and the tools inherit
it; real environment variables win if both are set. There is no manual export and
nothing platform-specific, so the same commands work on Windows.

**Requires**: Python 3.10+, [ffmpeg](https://ffmpeg.org) + `ffprobe` (libx264,
libfreetype, fontconfig for drawtext), a system TTF font (auto-detected, or
`--caption-font`), a [Groq API key](https://console.groq.com), and network access
to `api.groq.com` and `commons.wikimedia.org`.

## Adding a tool

Tools stay headless: a library plus a command that writes one output file. Kathya
never imports them. To add one:

1. Put the tool in its own folder (for example `tools/my_tool/`).
2. Copy an existing page under `web/` (say `web/voiceover2video.html`) and change
   `<body data-tool="...">` to your tool's id. That page renders its own form from
   the catalogue, so no markup changes are needed.
3. Describe it in `registry.py` — id, name, tagline, `page`, inputs, `command`
   placeholders (`{python}`, `{root}`, `{output}`, `{work}`, and one per input),
   and the output name/type.

That is the whole integration. The index gets the new tile automatically. Kathya
fills the placeholders, runs the command in a background job, streams its output
into the progress bar, and serves the file when it lands in `{output}`.

## Layout

```
app.py                 # Kathya: job runner, upload handling, HTTP server
registry.py            # the tool catalogue (add tools here)
web/                   # everything the browser sees
  index.html           # the shelf of tool tiles
  voiceover2video.html # one page per tool
  site.css             # shared styles
  site.js              # shelf + tool page behaviour
voiceover2video/       # the first tool, also usable on its own (see below)
data/jobs/             # per-job input / work / output (gitignored)
tests/                 # stdlib unittest
```

## Using a tool directly

Every tool is still a normal command line program; Kathya just wraps it. The
voiceover tool, for example:

```bash
# Voiceover (audio or video)
python3 -m voiceover2video --voiceover narration.mp3 -o story_video.mp4

# Story text instead of a recording
python3 -m voiceover2video story.txt -o story_video.mp4
python3 -m voiceover2video "Once upon a time, a lion woke up..." -o story_video.mp4
cat story.txt | python3 -m voiceover2video -o story_video.mp4

# Install as a console script instead
pip install -e . && voiceover2video --voiceover narration.mp3 -o story_video.mp4
```

| Flag | Description |
| --- | --- |
| `-o, --output` | Output video path (default `story_video.mp4`) |
| `--api-key` | Groq API key (falls back to `GROQ_API_KEY` env var) |
| `--groq-model` | Groq model (default `openai/gpt-oss-120b`) |
| `--whisper-model` | Groq Whisper model (default `whisper-large-v3-turbo`) |
| `--voiceover` | Narration audio or video to transcribe and add |
| `--work-dir` | Working dir for intermediate scene files (default `voiceover2video_work`) |
| `--caption-fontsize` | Caption font size in px (default `40`) |
| `--caption-font` | Path to TTF font for captions (default: auto-detect) |
| `--width` / `--height` | Output resolution (default `1280x720`) |

## Tests

```bash
python3 -m unittest discover -s tests
```

The ffmpeg-backed tests need `/tmp/opencode/v2v_test/scene_000.png` and
`/tmp/opencode/v2v_dbg/test_voiceover.wav` to exist.
