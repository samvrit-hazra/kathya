"""Media helpers built on ffprobe."""

import json
import subprocess
from pathlib import Path


def get_media_duration(path) -> float:
    """Return the duration of a media file in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def normalise_voiceover(path: str, destination) -> str:
    """Return an MP3 copy of `path` (mono, 16 kHz), transcoding only if needed.

    Whisper and the chunk splitter both expect plain audio, and the splitter
    stream-copies into an MP3 container, so video or non-MP3 uploads are
    converted once up front.
    """
    if Path(path).suffix.lower() == ".mp3":
        return str(path)

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(path),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-codec:a", "libmp3lame",
            "-b:a", "64k",
            str(destination),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not Path(destination).exists():
        raise RuntimeError(f"Could not read {path} as audio.\n{result.stderr.strip()}")
    return str(destination)


def split_audio(path: str, parts: int, out_dir, prefix: str = "chunk") -> list[str]:
    """Split an audio file into `parts` roughly equal-duration chunks (MP3)."""
    out_path = Path(str(out_dir).rstrip("/"))
    out_path.mkdir(parents=True, exist_ok=True)
    total = get_media_duration(path)
    chunks: list[str] = []
    for i in range(parts):
        duration = total / parts if parts > 0 else total
        chunk_file = out_path / f"{prefix}_{i:03d}.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ss", f"{i * duration:.3f}", "-t", f"{duration:.3f}", "-c", "copy", str(chunk_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        chunks.append(str(chunk_file))
    return chunks
