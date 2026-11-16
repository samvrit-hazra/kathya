import unittest

from voiceover2video.utils.text import wrap_caption_lines


class TestText(unittest.TestCase):
    def test_short_text_single_line(self):
        lines = wrap_caption_lines("Hello world", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40, 1000, max_lines=3)
        self.assertEqual(lines, ["Hello world"])

    def test_long_text_wraps(self):
        long_line = "a very long caption that should definitely need to be wrapped into multiple lines for the video"
        lines = wrap_caption_lines(long_line, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40, 400, max_lines=3)
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()
