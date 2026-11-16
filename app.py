"""Kathya — one local app for the story tools in this repository.

Run it, open the page, pick a tool, and use it from the browser. Kathya starts
nothing in the background: a tool runs only while it is producing a result.

    python3 app.py            # http://127.0.0.1:8000
    python3 app.py --port 8080 --no-browser
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from registry import TOOLS, get_tool, public_catalogue

ROOT = Path(__file__).resolve().parent
WEB_DIR = (ROOT / "web").resolve()
JOBS_DIR = ROOT / "data" / "jobs"

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
KEEP_JOBS = 20
ERROR_LINES = 12
WORKERS = 1

KEEPALIVE_INTERVAL = 600
KEEPALIVE_MIN_INTERVAL = 60
APP_STARTED = time.time()

RUNNER: "JobRunner | None" = None


class ToolError(Exception):
    """A request that cannot be turned into a job."""


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


def parse_multipart(headers, body: bytes) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """Split a multipart body into text fields and uploaded files."""
    content_type = headers.get("Content-Type") or ""
    if not content_type.lower().startswith("multipart/form-data"):
        raise ToolError("Send the form as multipart/form-data.")

    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    if not message.is_multipart():
        raise ToolError("Malformed upload.")

    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files[name] = (filename, payload)
        else:
            fields[name] = payload.decode("utf-8", "replace")
    return fields, files


def _safe_filename(name: str) -> str:
    base = Path(name).name
    safe = "".join(ch for ch in base if ch.isalnum() or ch in "._- ").strip()
    return safe or "upload"


def static_asset(url_path: str) -> Path | None:
    """Map a URL path to a page asset inside web/, or None if it is not one.

    Only files under web/ with a known type are served: the pages, their styles
    and scripts. Anything else (the source tree, data/, .env) stays unreachable.
    """
    relative = "index.html" if url_path in ("", "/") else unquote(url_path).lstrip("/")
    candidate = (WEB_DIR / relative).resolve()
    if WEB_DIR not in candidate.parents:
        return None
    if candidate.suffix.lower() not in STATIC_TYPES or not candidate.is_file():
        return None
    return candidate


def health_report() -> dict:
    """A cheap payload for Render health checks and uptime monitors.

    It only reads in-memory state: no disk scan, no network, no job work. The
    endpoint stays fast even while a render is running.
    """
    running = queued = 0
    if RUNNER is not None:
        with RUNNER.lock:
            statuses = [job["status"] for job in RUNNER.jobs.values()]
        running = statuses.count("running")
        queued = statuses.count("queued")

    return {
        "status": "ok",
        "service": "kathya",
        "uptime": round(time.time() - APP_STARTED, 1),
        "tools": len(TOOLS),
        "jobs": {"running": running, "queued": queued},
    }


def keepalive_enabled() -> bool:
    return os.environ.get("KATHYA_KEEPALIVE", "").strip().lower() in {"1", "true", "yes", "on"}


def keepalive_interval() -> float:
    raw = os.environ.get("KATHYA_KEEPALIVE_SECONDS", "").strip()
    try:
        return max(KEEPALIVE_MIN_INTERVAL, float(raw)) if raw else float(KEEPALIVE_INTERVAL)
    except ValueError:
        return float(KEEPALIVE_INTERVAL)


def keepalive_target() -> str | None:
    """The public URL to ping, or None when this deployment has no public URL.

    Render sets RENDER_EXTERNAL_URL. Other hosts can set KATHYA_KEEPALIVE_URL,
    which takes precedence.
    """
    base = os.environ.get("KATHYA_KEEPALIVE_URL", "").strip() or os.environ.get(
        "RENDER_EXTERNAL_URL", ""
    ).strip()
    return f"{base.rstrip('/')}/api/health" if base else None


def ping_health(target: str, timeout: float = 30.0) -> None:
    with urllib.request.urlopen(target, timeout=timeout) as response:
        response.read()


def start_keepalive(target: str, interval: float) -> threading.Thread:
    """Ping our own public URL, keeping a free instance from spinning down.

    Render's own health checks are internal probes and do not count as inbound
    traffic, so this has to go out over the public URL and back through the
    proxy. Any error is logged and retried on the next tick.
    """

    def loop() -> None:
        print(
            f"Kathya keepalive → {target} every {interval:.0f}s",
            file=sys.stderr,
        )
        while True:
            try:
                ping_health(target)
            except Exception as exc:  # noqa: BLE001 - keep pinging through hiccups
                print(f"Kathya keepalive failed: {exc}", file=sys.stderr)
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="kathya-keepalive", daemon=True)
    thread.start()
    return thread


def _clean_activity(line: str) -> str:
    text = line.strip()
    match = re.match(r"^\[[^\]]+\]\s*(.*)$", text)
    return match.group(1) if match else text


def _update_progress(job: dict, line: str) -> None:
    """Turn the tool's human-readable output into a status line and progress."""
    text = _clean_activity(line)
    if not text:
        return

    total = re.search(r"(?:targeting|into) (\d+) (?:slide|scene)", text)
    if total:
        job["scene_total"] = int(total.group(1))
        job["progress"] = max(job["progress"] or 0.0, 0.1)
        job["activity"] = f"Working on {job['scene_total']} slides"
        return

    scene = re.search(r"Scene (\d+):", text)
    if scene and job.get("scene_total"):
        index = int(scene.group(1))
        job["scene_index"] = index
        job["progress"] = round(0.1 + 0.85 * min((index + 1) / job["scene_total"], 1.0), 2)
        job["activity"] = f"Rendering slide {index + 1} of {job['scene_total']}"
        return

    if "Whisper transcribed" in text:
        job["progress"] = max(job["progress"] or 0.0, 0.05)
        job["activity"] = "Transcribed the voiceover"
        return

    job["activity"] = text[:160]


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


class JobRunner:
    """Runs tool commands in the background, one at a time."""

    def __init__(self, tools: list[dict], jobs_dir: Path = JOBS_DIR, root: Path = ROOT, autostart: bool = True):
        self.tools = {tool["id"]: tool for tool in tools}
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.root = Path(root)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.pending: "queue.Queue[str]" = queue.Queue()
        self._prune()
        if autostart:
            for index in range(WORKERS):
                threading.Thread(target=self._work, name=f"kathya-worker-{index}", daemon=True).start()

    # -- public API --------------------------------------------------------- #

    def submit(self, tool_id: str, fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> str:
        tool = self.tools.get(tool_id)
        if tool is None:
            raise ToolError("Unknown tool.")

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.jobs_dir / job_id
        values = {
            "python": sys.executable,
            "root": str(self.root),
            "output": str(job_dir / "output" / tool["output_name"]),
            "work": str(job_dir / "work"),
        }

        (job_dir / "input").mkdir(parents=True)
        (job_dir / "output").mkdir()
        (job_dir / "work").mkdir()

        try:
            for field in tool["inputs"]:
                name = field["name"]
                if field["kind"] == "file":
                    values[name] = self._save_file(job_dir, field, files.get(name))
                else:
                    value = (fields.get(name) or "").strip()
                    if field.get("required", True) and not value:
                        raise ToolError(f"{field['label']} is required.")
                    values[name] = value
        except ToolError:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        job = {
            "id": job_id,
            "tool": tool_id,
            "tool_name": tool["name"],
            "status": "queued",
            "progress": 0.0,
            "activity": "Waiting for a free slot",
            "error": None,
            "scene_index": None,
            "scene_total": None,
            "created": time.time(),
            "started": None,
            "finished": None,
            "output_path": None,
            "expected_output": Path(values["output"]),
            "output_type": tool["output_type"],
            "argv": [str(token).format_map(values) for token in tool["command"]],
            "dir": job_dir,
        }

        with self.lock:
            self.jobs[job_id] = job
        self.pending.put(job_id)
        return job_id

    def describe(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ToolError("Unknown job.")
            return self._public(job)

    # -- internals ---------------------------------------------------------- #

    def _save_file(self, job_dir: Path, field: dict, upload: tuple[str, bytes] | None) -> str:
        if not upload or not upload[1]:
            raise ToolError(f"{field['label']} is required.")
        filename, data = upload
        if len(data) > MAX_UPLOAD_BYTES:
            raise ToolError(f"{field['label']} is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
        suffix = Path(filename).suffix.lower()
        allowed = field.get("suffixes")
        if allowed and suffix not in allowed:
            raise ToolError(
                f"{field['label']}: {suffix or 'that file type'} is not supported. "
                f"Use {', '.join(allowed)}."
            )
        destination = job_dir / "input" / _safe_filename(filename)
        destination.write_bytes(data)
        return str(destination)

    def _public(self, job: dict) -> dict:
        now = job["finished"] or time.time()
        elapsed = round(now - job["started"], 1) if job["started"] else 0
        return {
            "id": job["id"],
            "tool": job["tool"],
            "tool_name": job["tool_name"],
            "status": job["status"],
            "progress": job["progress"],
            "activity": job["activity"],
            "error": job["error"],
            "elapsed": elapsed,
            "output_url": f"/api/jobs/{job['id']}/output" if job["output_path"] else None,
            "output_type": job["output_type"],
            "scene_index": job["scene_index"],
            "scene_total": job["scene_total"],
        }

    def _work(self) -> None:
        while True:
            job_id = self.pending.get()
            try:
                self.run_job(job_id)
            except Exception as exc:  # pragma: no cover - defensive boundary
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job is not None:
                        job["status"] = "failed"
                        job["error"] = f"Unexpected error: {exc}"
                        job["finished"] = time.time()
            finally:
                self.pending.task_done()
                self._prune()

    def run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["status"] = "running"
            job["started"] = time.time()
            job["activity"] = "Starting"
            argv = list(job["argv"])
            expected_output = Path(job["expected_output"])

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(self.root), env.get("PYTHONPATH")]))

        stderr_tail: list[str] = []
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            with self.lock:
                job["status"] = "failed"
                job["error"] = f"Could not start the tool: {exc}"
                job["finished"] = time.time()
            return

        assert process.stdout is not None
        for line in process.stdout:
            with self.lock:
                _update_progress(job, line)
            if line.strip():
                stderr_tail.append(line.rstrip())
                del stderr_tail[:-ERROR_LINES]
        returncode = process.wait()

        with self.lock:
            job["finished"] = time.time()
            if returncode == 0 and expected_output.exists():
                job["status"] = "done"
                job["progress"] = 1.0
                job["activity"] = "Finished"
                job["output_path"] = expected_output
            else:
                job["status"] = "failed"
                job["error"] = "\n".join(stderr_tail) or f"The tool exited with code {returncode}."
                job["activity"] = "Failed"

        if (job["dir"] / "work").exists():
            shutil.rmtree(job["dir"] / "work", ignore_errors=True)

    def _prune(self) -> None:
        directories = sorted(
            (path for path in self.jobs_dir.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old in directories[KEEP_JOBS:]:
            shutil.rmtree(old, ignore_errors=True)
        if self.jobs:
            with self.lock:
                self.jobs = {key: value for key, value in self.jobs.items() if value["dir"].exists()}


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class Handler(BaseHTTPRequestHandler):
    server_version = "kathya"

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        path = urlparse(self.path).path

        if path == "/favicon.ico":
            self._respond(204, b"", "image/x-icon")
            return

        if path == "/api/tools":
            self._json(200, {"tools": public_catalogue()})
            return

        if path == "/api/health":
            self._json(200, health_report())
            return

        job_id = self._job_id(path, suffix="")
        if job_id:
            try:
                self._json(200, RUNNER.describe(job_id))
            except ToolError as exc:
                self._error(404, str(exc))
            return

        job_id = self._job_id(path, suffix="/output")
        if job_id:
            self._job_output(job_id)
            return

        asset = static_asset(path)
        if asset is not None:
            self._respond(200, asset.read_bytes(), STATIC_TYPES[asset.suffix.lower()])
            return

        self._error(404, "Not found.")

    def do_POST(self) -> None:  # noqa: N802 - http.server naming
        if urlparse(self.path).path != "/api/jobs":
            self._error(404, "Not found.")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                raise ToolError("The upload was empty.")
            if length > MAX_UPLOAD_BYTES + 1024 * 1024:
                raise ToolError(f"Uploads are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")

            fields, files = parse_multipart(self.headers, self.rfile.read(length))
            tool_id = fields.get("tool") or ""
            job_id = RUNNER.submit(tool_id, fields, files)
        except ToolError as exc:
            self._error(400, str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive boundary
            self._error(500, f"Unexpected error: {exc}")
            return

        self._json(202, {"id": job_id})

    # -- responses ---------------------------------------------------------- #

    def _job_id(self, path: str, suffix: str) -> str:
        prefix = "/api/jobs/"
        if not path.startswith(prefix) or not path.endswith(suffix):
            return ""
        job_id = path[len(prefix) : len(path) - len(suffix) if suffix else None]
        return job_id if re.fullmatch(r"[0-9a-f]{6,32}", job_id) else ""

    def _job_output(self, job_id: str) -> None:
        with RUNNER.lock:
            job = RUNNER.jobs.get(job_id)
            if job is None or not job["output_path"]:
                self._error(404, "That result is not ready.")
                return
            output_path = Path(job["output_path"])
            output_type = job["output_type"]

        if not output_path.exists():
            self._error(410, "That result has been cleaned up.")
            return

        total = output_path.stat().st_size
        content_type = output_type
        start, end = 0, total - 1
        partial = False

        header = self.headers.get("Range")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
        if match and total:
            if match.group(1):
                start = int(match.group(1))
            if match.group(2):
                end = int(match.group(2))
            if start > end or start >= total:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            end = min(end, total - 1)
            partial = True

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.end_headers()

        # Stream the slice so seeking through a long video never loads the whole file.
        try:
            with output_path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # The player seeked or navigated away mid-response.
            pass

    def _json(self, status: int, payload: dict) -> None:
        self._respond(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._respond(status, message.encode(), "text/plain; charset=utf-8")

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write(f"[kathya] {format % args}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kathya", description="Run the Kathya story tools from one web page.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the page automatically.")
    args = parser.parse_args(argv)

    global RUNNER
    RUNNER = JobRunner(TOOLS)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    url = f"http://{args.host}:{args.port}"

    print(f"Kathya → {url}", file=sys.stderr)
    if keepalive_enabled():
        target = keepalive_target()
        if target is None:
            print(
                "Kathya keepalive: set KATHYA_KEEPALIVE_URL (or RENDER_EXTERNAL_URL) to enable it.",
                file=sys.stderr,
            )
        else:
            start_keepalive(target, keepalive_interval())
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
