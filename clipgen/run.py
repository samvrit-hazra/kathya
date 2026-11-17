"""
ClipGenerator — Command-line entry point.

Usage:
    python run.py VIDEO [options]
    python run.py --help
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Modules actually required by the CLI pipeline (mapped to pip package names).
REQUIRED_MODULES = {
    "groq": "groq",
    "pydantic_settings": "pydantic-settings",
    "faster_whisper": "faster-whisper",
    "imageio_ffmpeg": "imageio-ffmpeg",
}


def ensure_env_file() -> None:
    """Create .env from credentials.txt or .env.example when missing."""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        return

    cred_file = PROJECT_ROOT / "credentials.txt"
    if cred_file.exists():
        print("Found credentials.txt, generating .env...")
        content = cred_file.read_text(encoding="utf-8").strip()
        if "GROQ_API_KEY" not in content and content.startswith("gsk_"):
            content = f"GROQ_API_KEY={content}\n"
        env_file.write_text(content + "\n", encoding="utf-8")
        return

    example = PROJECT_ROOT / ".env.example"
    if example.exists():
        print("Creating .env from .env.example...")
        env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")


def check_dependencies() -> bool:
    """Check whether essential CLI dependencies are importable."""
    missing = [
        package for module, package in REQUIRED_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        print("[!] Missing required Python packages: " + ", ".join(missing))
        print("    Please install them with:")
        print("    python -m pip install -r requirements.txt\n")
        return False
    return True


def main() -> int:
    print("=" * 60)
    print("ClipGenerator — AI Video Repurposing CLI")
    print("=" * 60)

    ensure_env_file()

    if not check_dependencies():
        return 1

    from backend.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    sys.exit(main())
