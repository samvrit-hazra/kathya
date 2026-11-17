"""
backend/config.py
-----------------
Pydantic-settings configuration for the ClipGenerator CLI.

Values are loaded from environment variables and the one shared ``.env`` at
the Kathya repository root (regardless of the directory the CLI is run from).
When clipgen is used on its own outside Kathya, its own ``.env`` is used.
Real environment variables always take precedence over either file.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SHARED_ENV = PROJECT_ROOT.parent / ".env"
LOCAL_ENV = PROJECT_ROOT / ".env"
ENV_FILE = SHARED_ENV if SHARED_ENV.is_file() else LOCAL_ENV


class Settings(BaseSettings):
    """Application-wide settings loaded from .env at startup."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Groq API configuration
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_whisper_model: str = "whisper-large-v3"

    # Local Whisper fallback settings
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Custom FFmpeg path (if not in system PATH)
    ffmpeg_path: Optional[str] = None

    # Where generated clip folders are written by default
    outputs_dir: Path = PROJECT_ROOT / "outputs"

    @field_validator("outputs_dir", mode="before")
    @classmethod
    def _make_path(cls, v: str | Path) -> Path:
        path = Path(v)
        # Keep relative .env paths anchored to the project root so the CLI
        # behaves the same no matter which directory it is launched from.
        return path if path.is_absolute() else PROJECT_ROOT / path

    def ensure_dirs(self) -> None:
        self.outputs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()
