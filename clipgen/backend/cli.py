"""
backend/cli.py
--------------
Command-line interface for ClipGenerator.

Usage:
    python run.py VIDEO [options]

Processes one video per invocation and writes the generated MP4 files plus a
``clips.json`` manifest into an output folder.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_settings
from backend.tasks.ffmpeg_utils import find_ffmpeg
from backend.tasks.pipeline_runner import PipelineResult, execute_pipeline, safe_filename

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description=(
            "Turn one long-form video into short, subtitle-burned clips with "
            "landscape (16:9) and portrait (9:16) versions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python run.py podcast.mp4\n"
            "  python run.py talk.mkv -o ./clips --max-clips 3 --no-portrait\n"
            "  python run.py interview.mp4 --local-whisper -v\n"
        ),
    )
    parser.add_argument("video", type=Path, help="path to the source video file")
    parser.add_argument(
        "-o", "--output-dir", type=Path,
        help="directory for generated clips (default: outputs/<video name>)",
    )
    parser.add_argument("--model", help="override the Groq LLM model from .env")
    parser.add_argument("--whisper-model", help="override the Groq Whisper model from .env")
    parser.add_argument(
        "--local-whisper", action="store_true",
        help="use local faster-whisper instead of the Groq Whisper API",
    )
    parser.add_argument(
        "--no-portrait", action="store_true",
        help="skip generating the 9:16 portrait versions",
    )
    parser.add_argument(
        "--no-subtitles", action="store_true",
        help="skip burning subtitles into the landscape clips",
    )
    parser.add_argument(
        "--max-clips", type=int, metavar="N",
        help="maximum number of clips to generate",
    )
    parser.add_argument(
        "--min-seconds", type=float, default=15.0, metavar="SEC",
        help="minimum clip duration (default: 15)",
    )
    parser.add_argument(
        "--max-seconds", type=float, default=90.0, metavar="SEC",
        help="maximum clip duration (default: 90)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite an existing output directory",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    return parser


def _write_manifest(result: PipelineResult, *, args: argparse.Namespace) -> Path:
    settings = get_settings()
    manifest_path = result.output_dir / "clips.json"
    payload = {
        "source": str(result.source),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "output_dir": str(result.output_dir),
        "settings": {
            "llm_model": args.model or settings.groq_model,
            "whisper_model": args.whisper_model or settings.groq_whisper_model,
            "transcription": "local" if args.local_whisper else "groq",
            "subtitles": not args.no_subtitles,
            "portrait": not args.no_portrait,
        },
        "word_count": result.word_count,
        "clips": [
            {
                "index": clip.index,
                "title": clip.title,
                "reason": clip.reason,
                "start_seconds": clip.start_seconds,
                "end_seconds": clip.end_seconds,
                "duration_seconds": clip.duration_seconds,
                "landscape": clip.landscape_path.name if clip.landscape_path else None,
                "portrait": clip.portrait_path.name if clip.portrait_path else None,
            }
            for clip in result.clips
        ],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    if args.max_clips is not None and args.max_clips < 1:
        parser.error("--max-clips must be at least 1")
    if args.min_seconds <= 0 or args.max_seconds <= args.min_seconds:
        parser.error("--max-seconds must be greater than --min-seconds (both positive)")

    settings = get_settings()
    settings.ensure_dirs()

    video = args.video.expanduser()
    if not video.is_file():
        print(f"error: video file not found: {video}", file=sys.stderr)
        return 2
    if video.suffix.lower() not in VIDEO_EXTENSIONS:
        print(
            f"error: unsupported video extension '{video.suffix}'. "
            f"Supported: {', '.join(sorted(VIDEO_EXTENSIONS))}",
            file=sys.stderr,
        )
        return 2

    output_dir = (args.output_dir or settings.outputs_dir / safe_filename(video.stem)).expanduser().resolve()
    if (output_dir / "clips.json").exists() and not args.force:
        print(
            f"error: {output_dir} already contains clips.json. "
            "Use --force to overwrite, or choose another --output-dir.",
            file=sys.stderr,
        )
        return 2

    # Fail early with a clear message if FFmpeg is unavailable.
    try:
        find_ffmpeg()
    except Exception as exc:
        print(f"error: FFmpeg not found: {exc}", file=sys.stderr)
        return 2

    print(f"Source:  {video.resolve()}")
    print(f"Output:  {output_dir}")
    print(f"Model:   {args.model or settings.groq_model}")
    print("-" * 60, flush=True)

    try:
        result = execute_pipeline(
            video,
            settings=settings,
            output_dir=output_dir,
            model=args.model,
            whisper_model=args.whisper_model,
            local_whisper=args.local_whisper,
            no_portrait=args.no_portrait,
            no_subtitles=args.no_subtitles,
            max_clips=args.max_clips,
            min_seconds=args.min_seconds,
            max_seconds=args.max_seconds,
            on_stage=lambda message: print(message, flush=True),
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        logger.debug("Pipeline failure details", exc_info=True)
        print(f"error: {exc}", file=sys.stderr)
        return 1

    manifest_path = _write_manifest(result, args=args)

    print("-" * 60)
    if not result.clips:
        print("No clips were generated.")
    else:
        print(f"{len(result.clips)} clip(s) generated:")
        for clip in result.clips:
            files = [str(p.name) for p in (clip.landscape_path, clip.portrait_path) if p]
            print(f"  {clip.index:02d}. {clip.title} [{clip.start_seconds:.1f}s - {clip.end_seconds:.1f}s]")
            print(f"      {', '.join(files)}")
    print(f"Manifest: {manifest_path}")
    return 0
