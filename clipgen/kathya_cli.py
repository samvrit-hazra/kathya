"""Kathya adapter for ClipGenerator.

ClipGenerator writes a folder of clips plus a ``clips.json`` manifest, while a
Kathya job hands a tool one output path. This runs the ordinary ClipGenerator
CLI into a scratch folder and packs the result into that single ZIP file.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

CLIPGEN_DIR = Path(__file__).resolve().parent
if str(CLIPGEN_DIR) not in sys.path:
    sys.path.insert(0, str(CLIPGEN_DIR))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clipgen-kathya")
    parser.add_argument("--video", type=Path, required=True, help="uploaded source video")
    parser.add_argument("--output", type=Path, required=True, help="destination ZIP")
    parser.add_argument("--work", type=Path, required=True, help="scratch directory for this job")
    return parser


def pack(folder: Path, destination: Path) -> int:
    """Zip every file in ``folder`` into ``destination``; return the file count."""
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(folder).as_posix())
    return len(files)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        from backend.cli import main as clipgen_main
    except ModuleNotFoundError as exc:
        print(
            f"Clip generator needs its Python packages (missing {exc.name}). "
            "Install them with: python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    clips_dir = args.work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    code = clipgen_main([str(args.video), "-o", str(clips_dir), "--force"])
    if code != 0:
        return code

    count = pack(clips_dir, args.output)
    print(f"Packaged {count} file(s) into {args.output.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
