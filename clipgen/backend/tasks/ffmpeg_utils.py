"""
backend/tasks/ffmpeg_utils.py
-----------------------------
Helper to locate and run the ffmpeg executable across platforms.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from backend.config import get_settings

logger = logging.getLogger(__name__)

_CACHED_FFMPEG: Optional[str] = None


def find_ffmpeg() -> str:
    """
    Find the ffmpeg executable path.
    Checks:
      1. Configured `ffmpeg_path` in settings / env
      2. System PATH (shutil.which)
      3. imageio_ffmpeg package if installed
      4. Common Windows installation directories
    """
    global _CACHED_FFMPEG
    if _CACHED_FFMPEG and os.path.exists(_CACHED_FFMPEG):
        return _CACHED_FFMPEG

    settings = get_settings()

    # 1. Custom settings / env
    if settings.ffmpeg_path and os.path.exists(settings.ffmpeg_path):
        _CACHED_FFMPEG = settings.ffmpeg_path
        return _CACHED_FFMPEG

    # 2. System PATH
    which_path = shutil.which("ffmpeg")
    if which_path:
        _CACHED_FFMPEG = which_path
        return _CACHED_FFMPEG

    # 3. imageio_ffmpeg
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            _CACHED_FFMPEG = exe
            logger.info("Found ffmpeg via imageio_ffmpeg: %s", exe)
            return _CACHED_FFMPEG
    except ImportError:
        pass

    # 4. Standard Windows locations
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg\bin\ffmpeg.exe"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims\ffmpeg.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\ffmpeg\bin\ffmpeg.exe"),
    ]
    for p in common_paths:
        if os.path.exists(p):
            _CACHED_FFMPEG = p
            logger.info("Found ffmpeg in common directory: %s", p)
            return _CACHED_FFMPEG

    raise RuntimeError(
        "FFmpeg not found. Install it system-wide, set FFMPEG_PATH in .env, "
        "or install the imageio-ffmpeg package."
    )


def run_ffmpeg(args: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """
    Execute ffmpeg with the provided arguments.
    """
    ffmpeg_bin = find_ffmpeg()
    cmd = [ffmpeg_bin] + args
    cmd_str = " ".join(cmd)
    logger.debug("Executing ffmpeg: %s", cmd_str)

    # On Windows, hide command window if needed
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    if check and res.returncode != 0:
        logger.error("FFmpeg command failed [%d]: %s\nStderr: %s", res.returncode, cmd_str, res.stderr[-500:])
        raise RuntimeError(f"FFmpeg failed with exit code {res.returncode}: {res.stderr[-500:]}")

    return res
