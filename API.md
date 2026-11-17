# Kathya HTTP API

Kathya is a single-process web app. The browser UI and external clients use the
same HTTP API.

- Local base URL: `http://127.0.0.1:8000`
- Render base URL: `https://<service>.onrender.com`

JSON responses use `application/json; charset=utf-8`; error bodies are plain
text. Every response includes `Cache-Control: no-store`.

## Routes at a glance

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Shelf page (`web/index.html`). |
| `GET` | `/<page>.html`, `/site.css`, `/site.js`, `/site.svg`, `/*.png`, `/*.ico` | Static assets from `web/` only. |
| `GET` | `/favicon.ico` | Empty `204` response. |
| `GET` | `/api/tools` | Live tools plus planned/upcoming tools. |
| `GET`, `HEAD` | `/api/health` | Cheap health payload for Render and uptime monitors. |
| `POST` | `/api/jobs` | Submit a tool job. |
| `GET` | `/api/jobs/<id>` | Poll job state and progress. |
| `GET` | `/api/jobs/<id>/output` | Download the finished result; supports byte ranges. |

Static files are limited to `.html`, `.css`, `.js`, `.svg`, `.png` and `.ico`.
Source files, `.env`, `data/` and everything outside `web/` return `404`.

## `GET /api/tools`

Returns the catalogue used to build the shelf and tool pages. The example below
is abbreviated.

```json
{
  "tools": [
    {
      "id": "voiceover2video",
      "name": "Voiceover to video",
      "tagline": "Turn a recorded narration into a slideshow with your own words as captions.",
      "page": "voiceover2video.html",
      "action": "Generate video",
      "inputs": [
        {
          "name": "voiceover",
          "kind": "file",
          "label": "Voiceover",
          "accept": "audio/*,video/*",
          "suffixes": [".mp3", ".wav", ".m4a", ".mp4"]
        }
      ],
      "output_type": "video/mp4"
    }
  ],
  "upcoming": [
    {
      "id": "smart_audio_recorder",
      "name": "Smart Audio Recorder",
      "tagline": "Clean up recordings and get a transcript in one pass.",
      "features": [
        "Background noise reduction",
        "Silent part removal",
        "Transcript generation"
      ],
      "status": "Under development · not live yet"
    }
  ]
}
```

`tools` entries are runnable: each has a `page`, `inputs` and an output MIME
type. `upcoming` entries are display-only: they have no `page`, `inputs` or
command and cannot be submitted as jobs.

## `GET /api/health` and `HEAD /api/health`

Reads only in-memory state, so it stays fast while a job is running.

```json
{
  "status": "ok",
  "service": "kathya",
  "uptime": 123.4,
  "tools": 2,
  "jobs": {"running": 0, "queued": 0}
}
```

`HEAD` returns `200` with the same `Content-Type` and `Content-Length` but no
body; other `HEAD` paths return `404`. This is intentional for HTTP uptime
monitors such as UptimeRobot, which default to `HEAD`.

## `POST /api/jobs`

Submit a multipart form with:

- `tool`: the tool id from `/api/tools` (`voiceover2video` or `clipgen`).
- one field per input declared by that tool:
  - `voiceover2video` → `voiceover` (audio or video file);
  - `clipgen` → `video` (video file).

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -F "tool=voiceover2video" \
  -F "voiceover=@narration.mp3"
```

Success:

```json
{"id": "cd30593bc8f9"}
```

The id is 12 hex characters. Use it to poll status and fetch the output.

### Limits and validation

- Request body must be non-empty and at most 101 MB.
- Each uploaded file is limited to 100 MB.
- File extensions are checked against the tool's `suffixes` list.
- Filenames are reduced to a safe basename before storage.
- An unknown tool id, missing required field or unsupported file type returns
  `400` with a plain-text explanation.

Accepted jobs are queued. There is one worker (`WORKERS = 1`), so a second job
waits until the first finishes.

## `GET /api/jobs/<id>`

Poll the job. Example response for a completed video job:

```json
{
  "id": "cd30593bc8f9",
  "tool": "voiceover2video",
  "tool_name": "Voiceover to video",
  "status": "done",
  "progress": 1.0,
  "activity": "Finished",
  "error": null,
  "elapsed": 48.2,
  "output_url": "/api/jobs/cd30593bc8f9/output",
  "output_type": "video/mp4",
  "scene_index": null,
  "scene_total": 6
}
```

Status values:

| Status | Meaning |
| --- | --- |
| `queued` | Waiting for the single worker. |
| `running` | Tool subprocess is active. |
| `done` | Output file exists and `output_url` is available. |
| `failed` | Tool exited non-zero or did not produce the expected file; `error` contains the last stderr lines. |

`progress` is a number from `0.0` to `1.0`. `activity` is a human-readable
status line inferred from the tool's stdout/stderr. `scene_total` and
`scene_index` are optional counters for slides or clips. Unknown ids return
`404`.

A minimal polling loop:

```bash
curl -s http://127.0.0.1:8000/api/jobs/cd30593bc8f9 | jq -r '.status'
```

## `GET /api/jobs/<id>/output`

Downloads the finished file. The `Content-Type` comes from the tool:

- `voiceover2video` → `video/mp4`
- `clipgen` → `application/zip`

```bash
curl -o story_video.mp4 http://127.0.0.1:8000/api/jobs/cd30593bc8f9/output
```

Range requests are supported for video seeking:

```bash
curl -H "Range: bytes=0-1023" \
  http://127.0.0.1:8000/api/jobs/cd30593bc8f9/output
```

| Code | Meaning |
| --- | --- |
| `200` | Full file. |
| `206` | Requested byte range; includes `Content-Range`. |
| `404` | Unknown job or no output yet. |
| `410` | Job is known but its output file has been cleaned up. |
| `416` | Invalid range; includes `Content-Range: bytes */<size>`. |

Responses include `Accept-Ranges: bytes` and `Cache-Control: no-store`.

## Job storage and retention

Each job gets an isolated directory:

```
data/jobs/<id>/
├── input/   # uploaded file
├── work/    # per-job scratch, deleted when the job finishes
└── output/  # the single finished file served by /output
```

Only the newest 20 job directories are kept; older ones are pruned when a job
finishes or the app starts. Job state itself is in memory, so a server restart
clears all job ids. On Render free tier this directory is also ephemeral: a
redeploy, restart or idle spin-down removes it. Download results while the
instance is alive.

## Progress contract

There is no JSONL progress protocol. Progress is inferred from human-readable
tool output, including lines such as `Scene 1:`, `[2/4]`, `Transcribed N words`,
`Analyzing transcript`, `Generating N clip(s)` and `Packaged N file(s)`. Keep
CLI output readable when adding or updating tools.

## Security

The service is public and unauthenticated. Anyone with the URL can submit jobs
and spend the configured Groq quota and CPU. Run it locally or place it behind
authentication before exposing it to untrusted users.
