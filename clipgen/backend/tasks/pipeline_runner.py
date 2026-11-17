"""
backend/tasks/pipeline_runner.py
--------------------------------
Core pipeline executor for the ClipGenerator CLI.

Stages:
  1. FFmpeg extracts audio; Groq Whisper (or local faster-whisper) transcribes it.
  2. Groq LLM selects the best moments from the transcript.
  3. FFmpeg cuts each moment, burns subtitles and creates a 9:16 portrait version.

The pipeline returns plain data objects; writing the JSON manifest and
printing the summary is the CLI's responsibility.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

from backend.config import Settings, get_settings
from backend.tasks.analyze import analyze_transcript
from backend.tasks.clip import cut_clip, generate_portrait_crop
from backend.tasks.subtitle import burn_subtitles
from backend.tasks.transcribe import transcribe_video

logger = logging.getLogger(__name__)


@dataclass
class ClipResult:
    """A single generated clip and its metadata."""
    index: int
    title: str
    reason: str
    start_seconds: float
    end_seconds: float
    landscape_path: Path | None = None
    portrait_path: Path | None = None

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 2)


@dataclass
class PipelineResult:
    """Everything needed to build the output manifest."""
    source: Path
    output_dir: Path
    transcript: str
    word_count: int
    clips: List[ClipResult] = field(default_factory=list)


def safe_filename(text: str, max_len: int = 40) -> str:
    """Convert text to a safe filename slug."""
    slug = re.sub(r"[^\w\s-]", "", text)
    slug = re.sub(r"[\s]+", "_", slug).strip("_-")
    return slug[:max_len] or "clip"


def _filter_words(words: List[dict], start: float, end: float) -> List[dict]:
    """Extract words whose midpoint falls inside the [start, end] window."""
    result = []
    for w in words:
        w_start = float(w.get("start", 0))
        w_end = float(w.get("end", w_start))
        mid = (w_start + w_end) / 2.0
        if start <= mid <= end:
            result.append(w)
    return result


def execute_pipeline(
    video_path: str | Path,
    *,
    settings: Settings | None = None,
    output_dir: str | Path | None = None,
    model: str | None = None,
    whisper_model: str | None = None,
    local_whisper: bool = False,
    no_portrait: bool = False,
    no_subtitles: bool = False,
    max_clips: int | None = None,
    min_seconds: float = 15.0,
    max_seconds: float = 90.0,
    on_stage: Callable[[str], None] | None = None,
) -> PipelineResult:
    """
    Run the full clip-generation pipeline for one video.

    Raises RuntimeError/FileNotFoundError on failure so the CLI can report a
    clean error and exit with a non-zero status.
    """
    settings = settings or get_settings()
    video = Path(video_path).expanduser().resolve()

    if not video.is_file():
        raise FileNotFoundError(f"Video file not found: {video}")

    if output_dir is None:
        output_dir = settings.outputs_dir / safe_filename(video.stem)
    job_dir = Path(output_dir).expanduser().resolve()
    job_dir.mkdir(parents=True, exist_ok=True)

    # Apply command-line overrides without mutating the cached settings object.
    if model or whisper_model:
        settings = settings.model_copy(update={
            **({"groq_model": model} if model else {}),
            **({"groq_whisper_model": whisper_model} if whisper_model else {}),
        })

    def stage(message: str) -> None:
        # The CLI supplies on_stage for user-facing progress. Without a
        # callback (e.g. library use), fall back to logging.
        if on_stage:
            on_stage(message)
        else:
            logger.info(message)

    stage("Transcribing audio...")
    words, transcript = transcribe_video(video, settings=settings, local_only=local_whisper)
    if not words:
        raise RuntimeError("Transcription produced no words; cannot align subtitles.")
    stage(f"Transcribed {len(words)} words.")

    duration = float(words[-1].get("end", 0.0))
    stage("Analyzing transcript for the best moments...")
    segments = analyze_transcript(
        transcript,
        duration,
        settings=settings,
        max_clips=max_clips,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
    )

    result = PipelineResult(
        source=video,
        output_dir=job_dir,
        transcript=transcript,
        word_count=len(words),
    )

    if not segments:
        stage("No suitable clip segments identified.")
        return result

    stage(f"Generating {len(segments)} clip(s)...")
    for idx, seg in enumerate(segments, start=1):
        s_start = float(seg["start_seconds"])
        s_end = float(seg["end_seconds"])
        title = seg.get("title", f"Clip {idx}")
        reason = seg.get("reason", "")
        slug = f"{idx:02d}_{safe_filename(title)}"
        clip_result = ClipResult(
            index=idx,
            title=title,
            reason=reason,
            start_seconds=s_start,
            end_seconds=s_end,
        )

        stage(f"  [{idx}/{len(segments)}] {title} ({s_start:.1f}s - {s_end:.1f}s)")
        raw_clip = job_dir / f"{slug}_raw.mp4"
        landscape_path = job_dir / f"{slug}_landscape.mp4"

        try:
            cut_clip(str(video), s_start, s_end, str(raw_clip))
        except Exception as e:
            logger.error("Failed to cut clip %d: %s", idx, e)
            continue

        if no_subtitles:
            raw_clip.rename(landscape_path)
        else:
            clip_words = _filter_words(words, s_start, s_end)
            try:
                burn_subtitles(str(raw_clip), clip_words, s_start, str(landscape_path))
            except Exception as e:
                logger.warning("Subtitle burn failed for clip %d: %s", idx, e)
                raw_clip.rename(landscape_path)

        # The raw clip is no longer needed after cutting (and optional subtitle burn).
        if raw_clip.exists():
            try:
                raw_clip.unlink()
            except OSError:
                pass

        clip_result.landscape_path = landscape_path

        if not no_portrait:
            portrait_path = job_dir / f"{slug}_portrait.mp4"
            try:
                generate_portrait_crop(str(landscape_path), str(portrait_path))
                clip_result.portrait_path = portrait_path
            except Exception as e:
                logger.warning("Portrait conversion failed for clip %d: %s", idx, e)

        result.clips.append(clip_result)

    stage(f"Done: {len(result.clips)} clip(s) written to {job_dir}")
    return result
