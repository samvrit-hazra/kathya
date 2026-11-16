"""AI integration: turn a story script into per-scene narration + image keywords."""

import json
import tempfile
from pathlib import Path
from typing import Any

from openai import OpenAI

from ..config import (
    DEFAULT_GROQ_MODEL,
    GROQ_API_KEY_ENV,
    GROQ_BASE_URL,
    GROQ_MODEL_ENV,
    MAX_SCENES,
    MIN_SCENES,
    SECONDS_PER_SCENE,
    WHISPER_MODEL,
)
from ..models import Scene
from ..utils.media import split_audio

SYSTEM_PROMPT = (
    "You are a precise, JSON-only assistant that breaks short stories into "
    "cinematic scenes for an automated narrated video tool."
)

USER_PROMPT_TEMPLATE = """Break the following story into scenes for a narrated video.

Return ONLY a JSON object with this exact shape:
{"scenes": [{"narration": "<short caption-friendly narration for the scene>", "keywords": ["<image keyword>", ...]}, ...]}

Rules:
- {scene_instruction}
- "narration" must be a concise, caption-friendly sentence (or two) that could be displayed on screen during that scene. Keep it faithful to the story.
- {keywords_instruction}
- Return valid JSON only, with no markdown fences and no extra text.

Story:
{story}"""


DEFAULT_MAX_TOKENS = 2048
MAX_OUTPUT_TOKENS = 8192


def target_scene_count(duration_seconds: float) -> int:
    """Number of slides to aim for given the narration length in seconds.

    Longer narration yields more slides (roughly one per ``SECONDS_PER_SCENE``
    seconds), clamped to ``MIN_SCENES``/``MAX_SCENES`` so short clips still get
    a few slides and very long recordings stay within model output limits.
    """
    if duration_seconds <= 0:
        return MIN_SCENES
    count = round(duration_seconds / SECONDS_PER_SCENE)
    return max(MIN_SCENES, min(MAX_SCENES, count))


def _max_tokens_for(scene_count: int | None) -> int:
    """Give the model enough output budget to return the requested scenes."""
    if scene_count is None:
        return DEFAULT_MAX_TOKENS
    # ~80 tokens per scene (narration + keywords + JSON punctuation).
    return min(MAX_OUTPUT_TOKENS, max(DEFAULT_MAX_TOKENS, scene_count * 80))


def get_groq_client(api_key: str, base_url: str | None = None) -> OpenAI:
    return OpenAI(base_url=base_url or GROQ_BASE_URL, api_key=api_key)


def generate_scenes(
    client: OpenAI,
    story: str,
    model: str,
    scene_count: int | None = None,
) -> list[Scene]:
    """Ask the LLM to storyboard the story into scenes and return normalized scenes.

    ``scene_count`` pins the breakdown to that many scenes; when omitted the
    model falls back to its default 3-8 scene range. A single-scene breakdown
    asks for a single image keyword; multi-scene breakdowns ask for 2-4 each.
    """
    if scene_count is None:
        scene_instruction = "Split the story into 3 to 8 consecutive scenes."
        keywords_instruction = (
            '- "keywords" must contain 2 to 4 short lowercase English keywords or short phrases suitable for searching Wikimedia Commons for a relevant image (e.g. "lion", "spaceship", "ancient rome").'
        )
    elif scene_count > 1:
        scene_instruction = (
            f"Split the story into exactly {scene_count} consecutive scenes, "
            "in order, covering the whole story."
        )
        keywords_instruction = (
            '- "keywords" must contain 2 to 4 short lowercase English keywords or short phrases suitable for searching Wikimedia Commons for a relevant image (e.g. "lion", "spaceship", "ancient rome").'
        )
    else:
        scene_instruction = f"Split the story into exactly {scene_count} consecutive scenes, in order, covering the whole story."
        keywords_instruction = (
            '- "keywords" must contain a single short lowercase English keyword or short phrase suitable for searching Wikimedia Commons for a relevant image (e.g. "lion").'
        )

    prompt = (
        USER_PROMPT_TEMPLATE
        .replace("{scene_instruction}", scene_instruction)
        .replace("{keywords_instruction}", keywords_instruction)
        .replace("{story}", story.strip())
    )

    completion = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_max_tokens_for(scene_count),
        timeout=60,
    )

    raw_content = completion.choices[0].message.content or "{}"
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError:
        # Be forgiving: try to locate a JSON array/object inside the response.
        start = raw_content.find("{")
        end = raw_content.rfind("}")
        data = json.loads(raw_content[start : end + 1]) if start != -1 and end != -1 else {}

    scenes_payload: Any = data.get("scenes", data) if isinstance(data, dict) else data
    if isinstance(scenes_payload, dict):
        scenes_payload = scenes_payload.get("scenes", [])

    scenes: list[Scene] = []
    for i, item in enumerate(scenes_payload or []):
        if not isinstance(item, dict):
            continue
        narration = str(item.get("narration") or item.get("text") or "")
        keywords = [str(k) for k in (item.get("keywords") or []) if str(k).strip()]
        scene = Scene.from_parts(index=len(scenes), narration=narration, keywords=keywords)
        scenes.append(scene)

    if not scenes:
        raise ValueError("Groq returned an empty scene breakdown. Please try a longer story.")

    return scenes


def generate_scenes_from_chunks(client: OpenAI, audio_path: str, model: str, chunk_seconds: float, scene_count: int, chat_model: str | None = None) -> list[Scene]:
    """Transcribe the voiceover in fixed-length chunks and build one scene per chunk.

    Each chunk is transcribed and then turned into a single scene/slide by the
    LLM (caption-friendly narration + image keywords), with the slide duration
    set to the chunk length so slides stay aligned with the spoken audio.
    """
    scenes: list[Scene] = []
    with tempfile.TemporaryDirectory(prefix="voiceover2video_chunks_") as tmp_dir:
        chunks = split_audio(audio_path, scene_count, Path(tmp_dir))
        for chunk_path in chunks:
            chunk_transcript = transcribe_audio(client=client, audio_path=chunk_path, model=model)
            chunk_text = str(chunk_transcript.get("text") or "").strip()
            keywords: list[str] = []
            if chunk_text:
                chunk_scenes = generate_scenes(client=client, story=chunk_text, model=chat_model or model, scene_count=1)
                keywords = chunk_scenes[0].keywords
            scenes.append(Scene(index=len(scenes), narration=chunk_text, keywords=keywords, duration=chunk_seconds))
    return scenes


def transcribe_audio(client: OpenAI, audio_path: str, model: str) -> dict:
    """Transcribe an uploaded narration audio file via Groq Whisper.

    Returns a dict like ``{"text": str, "segments": [{"start": float, "end": float, "text": str}, ...]}``.
    Segments carry speech timestamps, used to keep slides/captions in sync with audio.
    """
    with open(audio_path, "rb") as audio_file:
        result = client.audio.transcriptions.create(model=model, file=audio_file, response_format="verbose_json")
    text = str(getattr(result, "text", "") or "")
    segments: list[dict] = []
    for seg in getattr(result, "segments", None) or []:
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", start) or start)
        segments.append({"start": start, "end": end, "text": str(getattr(seg, "text", "") or "")})
    return {"text": text.strip(), "segments": segments}


def get_groq_api_key() -> str | None:
    import os

    return os.environ.get(GROQ_API_KEY_ENV) or None


def get_groq_model() -> str:
    import os

    return os.environ.get(GROQ_MODEL_ENV) or DEFAULT_GROQ_MODEL
