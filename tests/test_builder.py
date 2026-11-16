import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voiceover2video.models import Scene
from voiceover2video.pipeline import builder
from voiceover2video.services import wikimedia_service


class TestBuilder(unittest.TestCase):
    def test_full_video_build_with_caption(self):
        scenes = [
            Scene.from_parts(0, "The lion roared across the open savanna plains.", ["lion", "savanna"]),
            Scene.from_parts(1, "A quiet river whispered past the trees far away.", ["river", "forest"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "out.mp4")
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            with mock.patch.object(wikimedia_service, "find_and_download_image", return_value="/tmp/opencode/v2v_test/scene_000.png"):
                final = builder.build_video(
                    scenes=scenes,
                    output=output,
                    work_dir=tmp,
                    font_path=font_path,
                    caption_fontsize=40,
                    image_provider=lambda scene: "/tmp/opencode/v2v_test/scene_000.png",
                )
            self.assertTrue(Path(final).exists())
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", final],
                capture_output=True,
                text=True,
                check=True,
            )
            import json as _json

            duration = _json.loads(result.stdout)["format"]["duration"]
            self.assertGreater(float(duration), 3.0)

    def test_fallback_color_slide(self):
        scenes = [Scene.from_parts(0, "Something happened.", ["thing"])]
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "out2.mp4")
            with mock.patch.object(
                wikimedia_service,
                "find_and_download_image",
                return_value=None,
            ):
                final = builder.build_video(
                    scenes=scenes,
                    output=output,
                    work_dir=tmp,
                    font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    caption_fontsize=40,
                    image_provider=lambda scene: None,
                )
            self.assertTrue(Path(final).exists())


    def test_assemble_with_audio(self):
        scenes = [Scene.from_parts(0, "Hello world.", ["hello"])]
        with tempfile.TemporaryDirectory() as tmp:
            scene_file = builder.render_scene_video(
                scenes[0],
                image_path="/tmp/opencode/v2v_test/scene_000.png",
                work_dir=Path(tmp),
                font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                caption_fontsize=40,
            )
            final = builder.assemble_with_audio(
                [(scene_file, scenes[0].duration)],
                "/tmp/opencode/v2v_dbg/test_voiceover.wav",
                str(Path(tmp) / "final_with_audio.mp4"),
            )
            self.assertTrue(Path(final).exists())


    def test_scene_durations_split_transcript_into_scene_windows(self):
        scenes = [
            Scene.from_parts(0, "The lion roared loudly.", ["lion"]),
            Scene.from_parts(1, "The sun set slowly.", ["sun"]),
        ]
        transcript = {
            "text": "the lion roared loudly the sun set slowly",
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "the lion roared loudly"},
                {"start": 3.0, "end": 6.0, "text": "the sun set slowly"},
            ],
        }
        durations = builder._scene_durations_from_transcript(scenes, transcript, 6.0)
        self.assertEqual(len(durations), 2)
        self.assertEqual(durations[0], 3.0)
        self.assertEqual(durations[1], 3.0)

    def test_scene_durations_fall_back_without_transcript(self):
        scenes = [Scene.from_parts(0, "Hello world.", ["hello"])]
        durations = builder._scene_durations_from_transcript(scenes, {"text": "", "segments": []}, 5.0)
        self.assertEqual(durations, [scenes[0].duration])


if __name__ == "__main__":
    unittest.main()
