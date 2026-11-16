"""ffmpeg-based video assembly: render captioned scenes and concat them."""

import subprocess
import sys
from pathlib import Path

from ..config import CAPTION_MAX_LINES, CAPTION_MAX_WIDTH_RATIO, VIDEO_HEIGHT, VIDEO_WIDTH
from ..models import Scene
from ..utils.media import get_media_duration
from ..utils.text import wrap_caption_lines


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"ffmpeg command failed (exit {result.returncode}): {' '.join(cmd)}")


def _drawtext_filters(lines: list[str], font_path: str, font_size: float, width: int, height: int, work_dir: Path, scene_index: int) -> list[str]:
    filters: list[str] = []
    max_width = width * CAPTION_MAX_WIDTH_RATIO
    line_height = font_size * 1.35
    block_height = max(1, len(lines)) * line_height
    top = (height - block_height) / 2

    for i, line in enumerate(lines):
        if not line.strip():
            continue
        text_file = work_dir / f"caption_{scene_index}_{i}.txt"
        text_file.write_text(line)
        y = top + i * line_height
        filters.append(
            "drawtext=fontfile={font}:fontcolor=white@0.92:borderw=2:bordercolor=black@0.55:"
            "shadowx=1:shadowy=1:shadowcolor=black@0.45:fontsize={fs}:x=(w-text_w)/2:y={y}:textfile={path}".format(
                font=font_path,
                fs=font_size,
                y=round(y, 2),
                path=text_file,
            )
        )
    return filters


def render_scene_video(
    scene: Scene,
    *,
    image_path: str | None,
    work_dir: Path,
    font_path: str,
    caption_fontsize: float,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
    duration: float | None = None,
) -> Path:
    """Render a single scene (image or fallback color slide + captions) to an mp4."""
    work_dir.mkdir(parents=True, exist_ok=True)
    out_path = work_dir / f"scene_{scene.index:03d}.mp4"
    scene_duration = scene.duration if duration is None else duration

    max_width = width * CAPTION_MAX_WIDTH_RATIO
    lines = wrap_caption_lines(
        scene.narration,
        font_path,
        caption_fontsize,
        max_width,
        max_lines=CAPTION_MAX_LINES,
    )
    filters = _drawtext_filters(lines, font_path, caption_fontsize, width, height, work_dir, scene.index)
    base = (
        f"scale={width}:{height}:force_original_aspect_ratio=1,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    vf = f"{base},{','.join(filters)}" if filters else base

    if image_path:
        src = str(image_path)
        if src.lower().endswith(".gif"):
            # ffmpeg's -loop input option does not accept animated-GIF inputs here;
            # convert to a static PNG first.
            converted = work_dir / f"scene_{scene.index:03d}_gif.png"
            _run(["ffmpeg", "-y", "-i", src, "-update", "1", str(converted)])
            image_path = str(converted)
        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-t", f"{scene_duration:.2f}",
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "veryfast",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s={width}x{height}:d={scene_duration:.2f}",
            "-vf", vf,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            "-preset", "veryfast",
            str(out_path),
        ]

    _run(cmd)
    return out_path


def assemble_videos(scene_videos: list[tuple[Path, float]], output: str) -> str:
    """Concatenate rendered scene videos into the final output file."""
    work_dir = scene_videos[0][0].parent if scene_videos else Path(".")
    list_path = work_dir / "concat.txt"
    lines = []
    for i, (scene_path, duration) in enumerate(scene_videos):
        lines.append(f"file '{scene_path.resolve()}'")
        if i < len(scene_videos) - 1:
            lines.append(f"duration {duration:.2f}")
    list_path.write_text("\n".join(lines) + "\n")

    _run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "23",
            str(output),
        ]
    )
    return output


def assemble_with_audio(scene_videos: list[tuple[Path, float]], voiceover_path: str, output: str) -> str:
    """Concatenate rendered scenes with the voiceover audio into the final video."""
    work_dir = scene_videos[0][0].parent if scene_videos else Path(".")
    list_path = work_dir / "concat.txt"
    lines = []
    for i, (scene_path, duration) in enumerate(scene_videos):
        lines.append(f"file '{scene_path.resolve()}'")
        if i < len(scene_videos) - 1:
            lines.append(f"duration {duration:.2f}")
    list_path.write_text("\n".join(lines) + "\n")

    _run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-i", str(voiceover_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            str(output),
        ]
    )
    return output


def _transcript_word_times(segments: list[dict]) -> list[float]:
    """Approximate speech timestamp (seconds) for each transcript word, in order."""
    word_times: list[float] = []
    for segment in segments:
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or start)
        words = str(segment.get("text") or "").split()
        if not words:
            continue
        step = (end - start) / len(words) if end > start else 0.0
        for i in range(len(words)):
            word_times.append(start + step * i)
    return word_times


def _scene_durations_from_transcript(scenes: list[Scene], transcript: dict, audio_duration: float) -> list[float]:
    """Split the spoken narration into per-scene windows for proper slide sync.

    Maps the transcript words onto the Whisper speech timeline and divides the
    speech into one window per scene, so rendered slides stay aligned with the
    actual voiceover instead of relying on a word-count estimate. Falls back to
    each scene's estimated duration when timing information is unavailable.
    """
    if not scenes:
        return []
    text = str((transcript or {}).get("text") or "")
    segments = (transcript or {}).get("segments") or []
    word_times = _transcript_word_times(segments)
    total_words = len(text.split())
    if not segments or not text.strip() or not word_times or total_words == 0:
        return [scene.duration for scene in scenes]

    scene_count = len(scenes)
    bounds = [total_words * i / scene_count for i in range(scene_count + 1)]

    def time_at(word_index: float) -> float:
        if word_index >= len(word_times):
            return audio_duration
        idx = min(int(word_index), max(len(word_times) - 1, 0))
        frac = word_index - idx
        if idx + 1 < len(word_times):
            return word_times[idx] + (word_times[idx + 1] - word_times[idx]) * frac
        return word_times[idx] + (audio_duration - word_times[idx]) * frac

    durations: list[float] = []
    for i in range(scene_count):
        start_t = time_at(bounds[i])
        end_t = time_at(bounds[i + 1])
        durations.append(round(max(end_t - start_t, 0.5), 2))
    return durations


def build_video(
    scenes: list[Scene],
    *,
    output: str,
    work_dir: str,
    font_path: str,
    caption_fontsize: float,
    image_provider,
    voiceover: str | None = None,
    transcript: dict | None = None,
) -> str:
    """Render all scenes (with captions) and assemble the final video."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    durations = [scene.duration for scene in scenes]
    if voiceover:
        # Derive scene durations from Whisper speech segments for proper sync,
        # falling back to the audio duration when no segments are available.
        segments = (transcript or {}).get("segments") or []
        audio_duration = float(segments[-1]["end"]) if segments else get_media_duration(voiceover)
        if segments:
            durations = _scene_durations_from_transcript(scenes, transcript, audio_duration)
        covered = sum(durations)
        if covered < audio_duration and durations:
            durations[-1] = max(durations[-1], round(audio_duration - (covered - durations[-1]), 2))

    scene_videos: list[tuple[Path, float]] = []
    for scene, duration in zip(scenes, durations):
        image_path = image_provider(scene) if scene.keywords else None
        status = image_path if image_path else "FALLBACK (no image found - using black slide)"
        print(f"[voiceover2video] Scene {scene.index}: narration={scene.narration!r} keywords={scene.keywords} -> {status}", flush=True)
        scene_file = render_scene_video(
            scene,
            image_path=image_path,
            work_dir=work,
            font_path=font_path,
            caption_fontsize=caption_fontsize,
            duration=duration,
        )
        scene_videos.append((scene_file, duration))

    if voiceover:
        return assemble_with_audio(scene_videos, voiceover, output)

    return assemble_videos(scene_videos, output)
