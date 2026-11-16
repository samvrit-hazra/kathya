import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voiceover2video import cli


class TestCli(unittest.TestCase):
    def test_main_builds_video_end_to_end(self):
        story = "The brave knight rode out at dawn and found the dragon sleeping."
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "out.mp4")
            work_dir = str(Path(tmp) / "work")
            argv = [
                story,
                "-o",
                output,
                "--api-key",
                "test-key",
                "--work-dir",
                work_dir,
                "--caption-fontsize",
                "40",
            ]
            fake_scenes = [
                type("S", (), {"index": 0, "narration": "The brave knight rode out at dawn.", "keywords": ["knight", "castle"], "duration": 4.0, "search_keyword": "knight"})(),
                type("S", (), {"index": 1, "narration": "The dragon slept under the mountain.", "keywords": ["dragon", "mountain"], "duration": 4.0, "search_keyword": "dragon"})(),
            ]
            with mock.patch.object(cli, "generate_scenes", return_value=fake_scenes) as generate_mock, mock.patch.object(
                cli.wikimedia_service, "find_and_download_image", return_value="/tmp/opencode/v2v_test/scene_000.png"
            ):
                exit_code = cli.main(argv)

            self.assertEqual(exit_code, 0)
            self.assertTrue(Path(output).exists())
            self.assertEqual(generate_mock.call_args.kwargs["scene_count"], 3)

            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", output],
                capture_output=True,
                text=True,
                check=True,
            )
            duration = json.loads(result.stdout)["format"]["duration"]
            self.assertGreater(float(duration), 3.0)


if __name__ == "__main__":
    unittest.main()
