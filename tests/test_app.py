"""Tests for the Kathya job runner and request parsing."""

import json
import shutil
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import registry
from app import (
    JobRunner,
    ToolError,
    _update_progress,
    health_report,
    parse_multipart,
    static_asset,
)


def _multipart(field: str, filename: str | None, payload: bytes) -> tuple[dict, bytes]:
    boundary = "----kathyatest"
    disposition = f'form-data; name="{field}"' + (f'; filename="{filename}"' if filename else "")
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: {disposition}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return {"Content-Type": f"multipart/form-data; boundary={boundary}"}, body


def _fake_tool(script: Path, suffixes: list[str] | None = None) -> dict:
    return {
        "id": "fake",
        "name": "Fake tool",
        "tagline": "",
        "action": "Run",
        "inputs": [
            {
                "name": "source",
                "kind": "file",
                "label": "Source",
                "suffixes": suffixes if suffixes is not None else [".mp3"],
            }
        ],
        "command": ["{python}", str(script), "{source}", "{output}"],
        "output_name": "result.mp4",
        "output_type": "video/mp4",
    }


class MultipartTests(unittest.TestCase):
    def test_reads_text_fields_and_files(self):
        headers, body = _multipart("voiceover", "narration.mp3", b"audio")

        fields, files = parse_multipart(headers, body)

        self.assertEqual(files["voiceover"], ("narration.mp3", b"audio"))

    def test_reads_plain_fields(self):
        boundary = "----kathyafields"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="tool"\r\n\r\n'
            "voiceover2video\r\n"
            f"--{boundary}--\r\n"
        ).encode()

        fields, files = parse_multipart(
            {"Content-Type": f"multipart/form-data; boundary={boundary}"}, body
        )

        self.assertEqual(fields["tool"], "voiceover2video")
        self.assertEqual(files, {})

    def test_rejects_other_content_types(self):
        with self.assertRaises(ToolError):
            parse_multipart({"Content-Type": "application/json"}, b"{}")


class CatalogueTests(unittest.TestCase):
    def test_tool_ids_are_unique(self):
        ids = [tool["id"] for tool in registry.TOOLS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_placeholder_in_a_command_is_provided(self):
        for tool in registry.TOOLS:
            known = {"python", "root", "output", "work"} | {field["name"] for field in tool["inputs"]}
            for token in tool["command"]:
                for placeholder in _placeholders(token):
                    self.assertIn(placeholder, known, f"{tool['id']} uses unknown {placeholder}")

    def test_public_catalogue_hides_local_paths_and_commands(self):
        public = registry.public_catalogue()

        self.assertTrue(public)
        for tool in public:
            self.assertNotIn("command", tool)
            self.assertNotIn("output_name", tool)
            self.assertTrue(tool["page"].endswith(".html"))


class PageTests(unittest.TestCase):
    def test_every_tool_has_a_page(self):
        for tool in registry.public_catalogue():
            self.assertTrue((registry_path() / "web" / tool["page"]).is_file(), tool["page"])

    def test_serves_the_index_at_the_root(self):
        self.assertEqual(static_asset("/").name, "index.html")
        self.assertEqual(static_asset("/index.html").name, "index.html")

    def test_serves_pages_styles_and_scripts(self):
        for path in ("/voiceover2video.html", "/site.css", "/site.js"):
            self.assertIsNotNone(static_asset(path), path)

    def test_never_serves_anything_outside_web(self):
        for path in ("/../app.py", "/../.env", "/%2e%2e/app.py", "/data/jobs", "/registry.py"):
            self.assertIsNone(static_asset(path), path)


def registry_path():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent


class HealthTests(unittest.TestCase):
    def _serve(self) -> str:
        from app import Handler

        class QuietHandler(Handler):
            def log_message(self, format: str, *args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_report_is_small_and_starts_at_zero_jobs(self):
        report = health_report()

        self.assertEqual(set(report), {"status", "service", "uptime", "tools", "jobs"})
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["jobs"], {"running": 0, "queued": 0})
        self.assertGreaterEqual(report["uptime"], 0)

    def test_endpoint_returns_json(self):
        base = self._serve()

        with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            payload = json.loads(response.read())

        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "kathya")

    def test_endpoint_answers_head_for_uptime_monitors(self):
        base = self._serve()

        request = urllib.request.Request(base + "/api/health", method="HEAD")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/json; charset=utf-8")
            self.assertGreater(int(response.headers["Content-Length"]), 0)
            self.assertEqual(response.read(), b"")


def _placeholders(token: str) -> list[str]:
    import re

    return re.findall(r"\{(\w+)\}", token)


class ProgressTests(unittest.TestCase):
    def test_counts_slides_from_storyboard_line(self):
        job = {"progress": 0.0, "activity": "", "scene_total": None, "scene_index": None}

        _update_progress(job, "[voiceover2video] Storyboarded into 7 scene(s).")

        self.assertEqual(job["scene_total"], 7)
        self.assertEqual(job["activity"], "Working on 7 slides")

    def test_scene_lines_advance_the_bar(self):
        job = {"progress": 0.0, "activity": "", "scene_total": 4, "scene_index": None}

        _update_progress(job, "[voiceover2video] Scene 1: narration='x' keywords=['y'] -> /tmp/x.jpg")

        self.assertEqual(job["scene_index"], 1)
        self.assertEqual(job["activity"], "Rendering slide 2 of 4")
        self.assertGreater(job["progress"], 0.4)


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kathya_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _runner(self, script_body: str) -> tuple[JobRunner, Path]:
        script = self.tmp / "fake_tool.py"
        script.write_text(script_body)
        jobs = self.tmp / "jobs"
        runner = JobRunner([_fake_tool(script)], jobs_dir=jobs, root=self.tmp, autostart=False)
        return runner, jobs

    def test_runs_a_tool_and_records_its_output(self):
        runner, jobs = self._runner(
            "import pathlib, sys\n"
            "print('[fake] Storyboarded into 2 scene(s).', file=sys.stderr)\n"
            "print('[fake] Scene 0: something', file=sys.stderr)\n"
            "pathlib.Path(sys.argv[2]).write_bytes(b'fake mp4')\n"
        )

        job_id = runner.submit("fake", {}, {"source": ("talk.mp3", b"audio")})
        runner.run_job(job_id)
        job = runner.describe(job_id)

        self.assertEqual(job["status"], "done")
        self.assertEqual(job["progress"], 1.0)
        self.assertEqual(job["elapsed"] >= 0, True)
        output = jobs / job_id / "output" / "result.mp4"
        self.assertTrue(output.exists())
        self.assertEqual(output.read_bytes(), b"fake mp4")
        self.assertEqual(job["output_url"], f"/api/jobs/{job_id}/output")

    def test_saves_the_upload_under_its_own_name(self):
        runner, jobs = self._runner("import pathlib, sys\npathlib.Path(sys.argv[2]).write_bytes(b'x')\n")

        job_id = runner.submit("fake", {}, {"source": ("my talk.mp3", b"audio")})

        self.assertEqual((jobs / job_id / "input" / "my talk.mp3").read_bytes(), b"audio")

    def test_reports_cli_failures_with_their_output(self):
        runner, _ = self._runner(
            "import sys\nprint('boom: missing GROQ_API_KEY', file=sys.stderr)\nsys.exit(3)\n"
        )

        job_id = runner.submit("fake", {}, {"source": ("talk.mp3", b"audio")})
        runner.run_job(job_id)
        job = runner.describe(job_id)

        self.assertEqual(job["status"], "failed")
        self.assertIn("missing GROQ_API_KEY", job["error"])

    def test_rejects_unknown_tools(self):
        runner, _ = self._runner("pass\n")

        with self.assertRaises(ToolError):
            runner.submit("nope", {}, {})

    def test_rejects_missing_and_mistyped_files(self):
        runner, jobs = self._runner("pass\n")

        with self.assertRaises(ToolError):
            runner.submit("fake", {}, {})
        with self.assertRaises(ToolError):
            runner.submit("fake", {}, {"source": ("notes.txt", b"x")})

        self.assertEqual(list(jobs.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
