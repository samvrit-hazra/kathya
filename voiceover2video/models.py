"""Core data types for the story-to-video pipeline."""

from dataclasses import dataclass

from .config import MAX_SCENE_SECONDS, MIN_SCENE_SECONDS, WORDS_PER_SECOND


@dataclass
class Scene:
    """One scene of the video: a chunk of the story with an image and a caption."""

    index: int
    narration: str
    keywords: list[str]
    duration: float = 0.0

    @classmethod
    def from_parts(cls, index: int, narration: str, keywords: list[str]) -> "Scene":
        clean_narration = " ".join((narration or "").split())
        clean_keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        words = len(clean_narration.split()) if clean_narration else 1
        duration = words / WORDS_PER_SECOND
        duration = max(MIN_SCENE_SECONDS, min(MAX_SCENE_SECONDS, duration))
        return cls(
            index=index,
            narration=clean_narration,
            keywords=clean_keywords,
            duration=round(duration, 2),
        )

    @property
    def search_keyword(self) -> str:
        """Primary image-search keyword for this scene (first keyword wins)."""
        return self.keywords[0] if self.keywords else "story"
