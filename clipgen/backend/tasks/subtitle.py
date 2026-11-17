"""
backend/tasks/subtitle.py
=========================
Subtitle burning pipeline for ClipGenerator.

Features:
  - Takes word-level timestamps from Whisper.
  - Groups words into high-retention, stylish caption cards (3-6 words per card).
  - Formats into an SRT or ASS subtitle file.
  - Burns subtitles into video with bold white text, vibrant outline, and subtle shadow.
  - Handles Windows path escaping for FFmpeg filters.
  - Gracefully falls back if libass is unavailable.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Sequence

from backend.tasks.ffmpeg_utils import find_ffmpeg, run_ffmpeg

logger = logging.getLogger(__name__)


def _seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert fractional seconds -> HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _escape_filter_path(path: Path) -> str:
    """
    Escape filesystem path for FFmpeg filter on Windows.
    FFmpeg requires colons escaped (C\\:/) and forward slashes.
    """
    p_str = str(path.resolve()).replace("\\", "/")
    # Escape colon for ffmpeg filter syntax (e.g., C:/ -> C\\:/)
    p_str = p_str.replace(":", "\\:")
    p_str = p_str.replace("'", "\\'")
    return p_str


def build_srt(
    words: Sequence[dict],
    clip_start_offset: float,
    clip_duration: float | None = None,
) -> str:
    """
    Build an SRT document with natural, punchy word grouping (3 to 6 words per subtitle block).
    Grouping words together makes captions far more readable and engaging than 1-word flashes.
    """
    if not words:
        return ""

    # Re-time words relative to clip start
    retimed: list[dict] = []
    for w in words:
        rel_start = float(w.get("start", 0)) - clip_start_offset
        rel_end = float(w.get("end", rel_start + 0.3)) - clip_start_offset

        if rel_end < 0:
            continue
        if clip_duration is not None and rel_start >= clip_duration:
            continue

        rel_start = max(0.0, rel_start)
        if clip_duration is not None:
            rel_end = min(rel_end, clip_duration)

        word_text = str(w.get("word", "")).strip()
        if word_text:
            retimed.append({"word": word_text, "start": rel_start, "end": rel_end})

    if not retimed:
        return ""

    # Group into phrases of 3 to 5 words
    blocks: list[str] = []
    chunk_size = 4
    idx = 1

    for i in range(0, len(retimed), chunk_size):
        chunk = retimed[i:i + chunk_size]
        start_ts = _seconds_to_srt_timestamp(chunk[0]["start"])
        end_ts = _seconds_to_srt_timestamp(chunk[-1]["end"])
        phrase = " ".join(c["word"] for c in chunk)
        # Clean text
        phrase = re.sub(r"[{}]", "", phrase)

        blocks.append(f"{idx}\n{start_ts} --> {end_ts}\n{phrase}\n")
        idx += 1

    return "\n".join(blocks)


def burn_subtitles(
    clip_path: str,
    words: list[dict],
    clip_start_offset: float,
    output_path: str,
) -> str:
    """
    Burn auto-generated subtitles into the video.
    """
    clip = Path(clip_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    srt_path = out.parent / f"{out.stem}_temp.srt"
    srt_content = build_srt(words, clip_start_offset)

    if not srt_content.strip():
        logger.info("No subtitle words for clip %s. Copying raw video.", clip.name)
        shutil.copy2(clip, out)
        return str(out)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    escaped_srt = _escape_filter_path(srt_path)

    # Stylish TikTok / Reels style subtitle formatting:
    # Yellow/White bold text, heavy black outline, centered near bottom
    style_opts = (
        "FontName=Arial,"
        "FontSize=22,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"  # White
        "OutlineColour=&H00000000,"  # Black
        "BackColour=&H80000000,"     # Translucent shadow
        "Outline=3,"
        "Shadow=1,"
        "Alignment=2,"               # Bottom-center
        "MarginV=50"
    )

    sub_filter = f"subtitles='{escaped_srt}':force_style='{style_opts}'"

    args = [
        "-y",
        "-i", str(clip),
        "-vf", sub_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out),
    ]

    try:
        logger.info("Burning subtitles into %s...", out.name)
        run_ffmpeg(args, check=True)
    except Exception as e:
        logger.warning("Subtitle burning failed (%s). Copying clean clip without subtitles.", e)
        shutil.copy2(clip, out)
    finally:
        if srt_path.exists():
            try:
                srt_path.unlink()
            except OSError:
                pass

    return str(out)
