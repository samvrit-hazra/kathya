"""Default configuration for voiceover2video."""

from pathlib import Path

# --- Tool-local runtime paths (kept inside this folder, not the repo root) ---
TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = str(TOOL_DIR / "outputs" / "story_video.mp4")
DEFAULT_WORK_DIR = str(TOOL_DIR / "work")

# --- Groq (story understanding / image keyword generation) ---
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
LOCAL_BASE_URL = "http://localhost:11434/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_API_KEY_ENV = "GROQ_API_KEY"
GROQ_MODEL_ENV = "GROQ_MODEL"

# --- Wikimedia Commons image search ---
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
WIKIMEDIA_NAMESPACE = 6  # 6 == File:
WIKIMEDIA_THUMB_WIDTH = 1280
WIKIMEDIA_SEARCH_LIMIT = 6

# --- Video layout ---
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 24

# --- Caption (drawtext) settings ---
CAPTION_FONT_SIZE = 40
CAPTION_MAX_WIDTH_RATIO = 0.85  # caption block must fit within this fraction of frame width
CAPTION_MAX_LINES = 3

# --- Narration pacing ---
WORDS_PER_SECOND = 2.5
MIN_SCENE_SECONDS = 2.0
MAX_SCENE_SECONDS = 15.0

# --- Slide count scaling (longer narration -> more slides) ---
SECONDS_PER_SCENE = 6.0  # target ~1 slide per this many seconds of narration
MIN_SCENES = 3
MAX_SCENES = 40

WHISPER_MODEL = "whisper-large-v3-turbo"
