"""
backend/tasks/clip.py
---------------------
Video cutting and formatting module for ClipGenerator.
Cuts high-quality sub-clips and generates 9:16 vertical formats for Instagram Reels & YouTube Shorts.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.tasks.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)


def cut_clip(video_path: str, start: float, end: float, output_path: str) -> None:
    """
    Cut a video segment from `start` to `end` seconds.
    Uses accurate seeking and fast encoding for clean, glitch-free cuts.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    duration = max(1.0, end - start)

    args = [
        "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", str(video_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        str(out),
    ]

    logger.info("Cutting clip from %.2fs to %.2fs (duration: %.2fs) -> %s", start, end, duration, out.name)
    run_ffmpeg(args, check=True)


def generate_portrait_crop(landscape_path: str, portrait_path: str) -> None:
    """
    Convert a landscape video into 9:16 (1080x1920) vertical format.

    Uses the studio-grade blurred background technique:
    1. Background: original video zoomed to fill 9:16 canvas and blurred.
    2. Foreground: original video scaled to 1080 width and centered vertically.
    Falls back to center crop if complex filter is unsupported.
    """
    out = Path(portrait_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Method 1: Blurred background aesthetic
    filter_complex = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
        "[0:v]scale=1080:-2:flags=lanczos[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
    )

    args_blur = [
        "-y",
        "-i", str(landscape_path),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(out),
    ]

    try:
        logger.info("Generating portrait 9:16 video (blurred background) -> %s", out.name)
        run_ffmpeg(args_blur, check=True)
        return
    except Exception as e:
        logger.warning("Blurred background filter failed (%s). Falling back to center-crop...", e)

    # Method 2: Fallback center crop
    filter_crop = "crop=min(iw\\,ih*9/16):ih,scale=1080:1920"
    args_crop = [
        "-y",
        "-i", str(landscape_path),
        "-vf", filter_crop,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out),
    ]
    run_ffmpeg(args_crop, check=True)
