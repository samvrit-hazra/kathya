"""Command-line interface for the story-to-video tool."""

import argparse
import os
import sys
import tempfile
from pathlib import Path

from .config import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_OUTPUT,
    DEFAULT_WORK_DIR,
    GROQ_API_KEY_ENV,
    GROQ_BASE_URL,
    GROQ_MODEL_ENV,
    VIDEO_HEIGHT,
    VIDEO_WIDTH,
    WHISPER_MODEL,
    WORDS_PER_SECOND,
)
from .pipeline.builder import build_video
from .services.groq_service import generate_scenes, generate_scenes_from_chunks, get_groq_client, target_scene_count, transcribe_audio
from .services import wikimedia_service
from .utils.fonts import find_caption_font
from .utils.media import get_media_duration, normalise_voiceover
from .utils.env import load_env


def read_story(source: str | None) -> str:
    """Read the story from a file path, stdin ('-' for stdin), or use the raw argument as text."""
    if source is None:
        return sys.stdin.read()

    source = source.strip()
    if source == "-" or source == "":
        return sys.stdin.read()

    path = Path(source)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()

    # Treat the argument as raw story text.
    return source


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voiceover2video",
        description=(
            "Turn a text story into a narrated slideshow video: Groq AI breaks the story "
            "into scenes with image keywords, images are fetched from Wikimedia Commons, "
            "and ffmpeg renders captions-timed scenes into a final MP4."
        ),
    )
    parser.add_argument(
        "story",
        nargs="?",
        default=None,
        help="Path to a story text file, '-' for stdin, or the story text itself.",
    )
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, help="Output video file path (default: voiceover2video/outputs/story_video.mp4).")
    parser.add_argument("--api-key", default=os.environ.get(GROQ_API_KEY_ENV), help=f"Groq API key (or set {GROQ_API_KEY_ENV}).")
    parser.add_argument("--groq-model", default=os.environ.get(GROQ_MODEL_ENV) or DEFAULT_GROQ_MODEL, help="Groq model to use (default: %(default)s).")
    parser.add_argument("--work-dir", default=DEFAULT_WORK_DIR, help="Working directory for intermediate scene files (default: voiceover2video/work).")
    parser.add_argument("--caption-fontsize", type=float, default=40, help="Caption font size in pixels (default: 40).")
    parser.add_argument("--caption-font", default=None, help="Path to TTF font for captions (default: auto-detect DejaVu Sans Bold).")
    parser.add_argument("--voiceover", default=None, help="Optional path to a voiceover audio file (e.g. narration.mp3) to transcribe and add to the video.")
    parser.add_argument("--whisper-model", default=WHISPER_MODEL, help="Groq Whisper model to use for transcription (default: %(default)s).")
    parser.add_argument("--base-url", default=os.environ.get("GROQ_BASE_URL") or GROQ_BASE_URL, help="Groq-compatible API base URL (default: %(default)s). Use http://localhost:11434/v1 for local Ollama.")
    parser.add_argument("--width", type=int, default=VIDEO_WIDTH, help="Video width in pixels (default: 1280).")
    parser.add_argument("--height", type=int, default=VIDEO_HEIGHT, help="Video height in pixels (default: 720).")
    return parser


def _voiceover_duration(audio_path: str, transcript: dict | None) -> float:
    """Narration length in seconds: prefer Whisper segments, fall back to ffprobe."""
    segments = (transcript or {}).get("segments") or []
    if segments:
        return float(segments[-1]["end"])
    return get_media_duration(audio_path)


def run(args: argparse.Namespace) -> str:
    api_key = args.api_key
    if not api_key:
        raise ValueError(f"Missing Groq API key. Pass --api-key or set the {GROQ_API_KEY_ENV} environment variable.")

    client = get_groq_client(api_key, base_url=args.base_url)

    if args.voiceover:
        # Chunk splitting stream-copies into MP3, and Whisper is happiest with plain
        # audio, so normalise any audio/video upload once before doing anything else.
        with tempfile.TemporaryDirectory(prefix="voiceover2video_audio_") as tmp_dir:
            voiceover = normalise_voiceover(args.voiceover, Path(tmp_dir) / "voiceover.mp3")
            return _render(args, client, voiceover)
    return _render(args, client, None)


def _render(args: argparse.Namespace, client, voiceover: str | None) -> str:
    transcript = None
    if voiceover:
        transcript = transcribe_audio(client=client, audio_path=voiceover, model=args.whisper_model)
        print(f"[voiceover2video] Whisper transcribed the voiceover to {len(transcript['text'])} characters of text.", file=sys.stderr)
        audio_seconds = _voiceover_duration(voiceover, transcript)
        scene_count = target_scene_count(audio_seconds)
        print(f"[voiceover2video] Audio is {audio_seconds:.1f}s; targeting {scene_count} slide(s).", file=sys.stderr)
        scenes = generate_scenes_from_chunks(client=client, audio_path=voiceover, model=args.whisper_model, chunk_seconds=audio_seconds / scene_count, scene_count=scene_count, chat_model=args.groq_model)
    else:
        story = read_story(args.story)
        if not story:
            raise ValueError("No story text provided. Pass a story file/path, --voiceover, or pipe text via stdin.")
        estimated_seconds = len(story.split()) / WORDS_PER_SECOND
        scene_count = target_scene_count(estimated_seconds)
        print(f"[voiceover2video] Estimated narration ~{estimated_seconds:.1f}s; targeting {scene_count} slide(s).", file=sys.stderr)
        scenes = generate_scenes(client=client, story=story, model=args.groq_model, scene_count=scene_count)
    print(f"[voiceover2video] Storyboarded into {len(scenes)} scene(s).", file=sys.stderr)

    output_path = args.output
    work_dir = args.work_dir or DEFAULT_WORK_DIR
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    def image_provider(scene) -> str | None:
        keyword = scene.keywords[0] if scene.keywords else scene.search_keyword
        return wikimedia_service.find_and_download_image(
            keywords=scene.keywords or [keyword],
            work_dir=work_dir,
            dest_stem=f"scene_{scene.index:03d}",
        )

    final_path = build_video(
        scenes=scenes,
        output=output_path,
        work_dir=work_dir,
        font_path=find_caption_font(args.caption_font),
        caption_fontsize=args.caption_fontsize,
        image_provider=image_provider,
        voiceover=voiceover,
        transcript=None if voiceover else transcript,
    )
    return final_path


def main(argv: list[str] | None = None) -> int:
    load_env()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        final_path = run(args)
    except Exception as exc:  # pragma: no cover - CLI boundary
        import traceback

        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(final_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
