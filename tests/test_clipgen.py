"""Tests for the ClipGenerator adapter used by Kathya jobs."""

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from clipgen.kathya_cli import build_parser, pack


class ClipgenAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kathya_clipgen_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_parser_accepts_the_registry_flags(self):
        args = build_parser().parse_args(
            ["--video", "a.mp4", "--work", "work", "--output", "clips.zip"]
        )

        self.assertEqual(args.video, Path("a.mp4"))
        self.assertEqual(args.work, Path("work"))
        self.assertEqual(args.output, Path("clips.zip"))

    def test_pack_flattens_the_clip_folder_into_a_zip(self):
        folder = self.tmp / "work" / "clips"
        (folder / "nested").mkdir(parents=True)
        (folder / "01_hook_landscape.mp4").write_bytes(b"a" * 2048)
        (folder / "nested" / "clips.json").write_text('{"clips": []}', encoding="utf-8")
        destination = self.tmp / "output" / "clips.zip"

        count = pack(folder, destination)

        self.assertEqual(count, 2)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(sorted(archive.namelist()), ["01_hook_landscape.mp4", "nested/clips.json"])
            self.assertEqual(archive.read("nested/clips.json"), b'{"clips": []}')
