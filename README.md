# Kathya

Empowers storytellers, podcasters and authors with AI-native production tools that run locally.

## Installation and Setup

Requires Python 3.10+ and `ffmpeg`/`ffprobe` on your PATH.

```bash
git clone https://github.com/samvrit-hazra/kathya.git
cd kathya/
cp .env.example .env                  # Windows: copy .env.example .env
# set GROQ_API_KEY in .env
python3 -m venv .venv                 # Windows: py -3 -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python app.py                         # http://127.0.0.1:8000
```

## Tools

| Tool | Status | What it does |
| --- | --- | --- |
| **Voiceover to video** (`voiceover2video`) | Live | Turns a recording (or story text) into a narrated slideshow. The transcript becomes the captions verbatim; a language model supplies one image keyword per slide, and landscape images come from Wikimedia Commons. Output: a single MP4. |
| **Clip generator** (`clipgen`) | Live | Finds the most interesting moments in a long video and cuts them into highlighted, subtitled short clips. The CLI produces a folder, and Kathya's adapter packs it into one `clips.zip` download. |
| **Smart Audio Recorder** | Under development — not live | Planned recorder that reduces background noise, removes silent sections, and generates a transcript. It appears on the shelf as a non-clickable box. |
| **Podcast Generator** | Under development — not live | Planned tool for generating an RSS feed for your podcast episodes that can be subscribed to from podcast apps and platforms. It appears on the shelf as a non-clickable box. |

## Layout

```
app.py                 # Kathya: job runner, upload handling, HTTP server
registry.py            # catalogue: TOOLS + UPCOMING_TOOLS (add tools here)
API.md                 # HTTP API reference
render.yaml            # Render Blueprint (free tier, health check, env var)
requirements.txt       # shared deps for the app and both tools
pyproject.toml         # Python 3.10+ and the voiceover2video console script
.env.example           # copy to .env and set GROQ_API_KEY
web/                   # everything the browser sees
  index.html           # shelf of tool tiles + coming-soon boxes
  voiceover2video.html # one page per live tool
  clipgen.html         # one page per live tool
  site.css             # shared styles
  site.js              # shelf + tool page behaviour
voiceover2video/       # tool 1, also usable on its own
  work/                # scene mp4s, caption textfiles (gitignored)
  outputs/             # finished videos (gitignored)
clipgen/               # tool 2: imported CLI + Kathya adapter
  kathya_cli.py        # packs the clip folder into one clips.zip
  backend/             # the imported ClipGenerator CLI
  outputs/             # generated clips and clips.json (gitignored)
data/jobs/             # platform-owned per-job input / work / output (gitignored)
tests/                 # stdlib unittest
```
