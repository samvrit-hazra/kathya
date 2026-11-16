"""Minimal .env file loader (no external dependencies)."""

import os
from pathlib import Path

ENV_FILE_NAME = ".env"


def load_env(path: str | Path | None = None) -> dict[str, str]:
    """Load KEY=VALUE pairs from a ``.env`` file into the process environment.

    Existing environment variables always take precedence. A missing file is
    not an error. Returns the mapping of loaded variables.
    """
    env_path = Path(path) if path is not None else Path(ENV_FILE_NAME)
    if not env_path.is_file():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'").strip()
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded
