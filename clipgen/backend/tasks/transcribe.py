"""
backend/tasks/transcribe.py
---------------------------
Transcription module for ClipGenerator.
Extracts audio from video and generates word-level timestamps using:
  1. Groq Whisper Cloud API (whisper-large-v3, fast and free)
  2. faster-whisper (local offline fallback)
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from backend.config import Settings, get_settings
from backend.tasks.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)


def extract_audio(video_path: Path, output_audio_path: Path) -> Path:
    """
    Extract mono 16 kHz MP3 audio from a video file.

    48 kbps mono speech keeps even a 2-hour video small enough for the
    transcription API while retaining high accuracy.
    """
    output_audio_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        "-i", str(video_path),
        "-vn",                    # no video
        "-ac", "1",               # mono
        "-ar", "16000",           # 16 kHz sample rate optimal for Whisper
        "-b:a", "48k",            # 48 kbps
        str(output_audio_path),
    ]
    run_ffmpeg(args, check=True)
    return output_audio_path


def _transcribe_with_groq(audio_path: Path, api_key: str, model_name: str) -> Tuple[List[Dict], str]:
    """Transcribe audio via the Groq Whisper API with word-level timestamps."""
    from groq import Groq

    client = Groq(api_key=api_key)
    logger.info("Transcribing audio with Groq Whisper API (model=%s)...", model_name)

    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            file=(audio_path.name, f),
            model=model_name,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )

    # Response is a Transcription object or dict-like
    resp_dict = response.to_dict() if hasattr(response, "to_dict") else (
        response.model_dump() if hasattr(response, "model_dump") else json.loads(response)
    )

    full_text = resp_dict.get("text", "")
    raw_words = resp_dict.get("words", [])

    words: List[Dict] = []
    if raw_words:
        for w in raw_words:
            word_str = w.get("word", "").strip()
            if word_str:
                words.append({
                    "word": word_str,
                    "start": float(w.get("start", 0.0)),
                    "end": float(w.get("end", 0.0)),
                })
    else:
        # If words weren't returned, derive timestamps from segments
        segments = resp_dict.get("segments", [])
        for seg in segments:
            seg_text = seg.get("text", "").strip()
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", s_start + 1.0))
            seg_words = seg_text.split()
            if not seg_words:
                continue
            word_dur = (s_end - s_start) / max(1, len(seg_words))
            for i, sw in enumerate(seg_words):
                w_s = s_start + i * word_dur
                words.append({"word": sw, "start": round(w_s, 2), "end": round(w_s + word_dur, 2)})

    logger.info("Groq transcription successful: %d words, %d characters.", len(words), len(full_text))
    return words, full_text


def _transcribe_with_local_whisper(audio_path: Path, settings: Settings) -> Tuple[List[Dict], str]:
    """Transcribe audio locally using faster-whisper."""
    from faster_whisper import WhisperModel

    logger.info(
        "Loading local faster-whisper model: %s on %s (%s)...",
        settings.whisper_model_size,
        settings.whisper_device,
        settings.whisper_compute_type,
    )

    model = WhisperModel(
        settings.whisper_model_size,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )

    segments_generator, _ = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        beam_size=5,
    )

    words: List[Dict] = []
    text_chunks: List[str] = []

    for seg in segments_generator:
        text_chunks.append(seg.text)
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word.strip(),
                    "start": float(w.start),
                    "end": float(w.end),
                })
        else:
            # Approximate word timestamps if the model didn't emit words
            seg_words = seg.text.strip().split()
            dur = (seg.end - seg.start) / max(1, len(seg_words))
            for i, sw in enumerate(seg_words):
                ws = seg.start + i * dur
                words.append({"word": sw, "start": round(ws, 2), "end": round(ws + dur, 2)})

    full_text = " ".join(text_chunks).strip()
    logger.info("Local transcription successful: %d words, %d characters.", len(words), len(full_text))
    return words, full_text


def transcribe_video(
    video_path: str | Path,
    *,
    settings: Settings | None = None,
    local_only: bool = False,
) -> Tuple[List[Dict], str]:
    """
    Transcribe a video:
      1. Extract audio with FFmpeg into a temporary directory.
      2. Use Groq Whisper when a valid key is available (unless local_only).
      3. Fall back to local faster-whisper on failure.
      4. Remove the temporary audio file.

    Returns (words, transcript_text).
    """
    settings = settings or get_settings()
    video = Path(video_path)

    with tempfile.TemporaryDirectory(prefix="clipgen_audio_") as tmp:
        audio_path = Path(tmp) / f"{video.stem}.mp3"
        logger.info("Extracting audio from %s...", video.name)
        extract_audio(video, audio_path)

        if not local_only and settings.groq_api_key and settings.groq_api_key.startswith("gsk_"):
            try:
                return _transcribe_with_groq(
                    audio_path,
                    settings.groq_api_key,
                    settings.groq_whisper_model,
                )
            except Exception as e:
                logger.warning("Groq Whisper API failed (%s). Falling back to local whisper...", e)

        return _transcribe_with_local_whisper(audio_path, settings)
