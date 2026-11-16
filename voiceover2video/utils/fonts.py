"""Helpers to locate a TTF font file for ffmpeg's drawtext filter."""

from pathlib import Path

DEFAULT_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    # Windows (Arial Bold / Regular — present on stock Windows installs)
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def find_caption_font(explicit_path: str | None = None) -> str:
    """Return a font file usable by ffmpeg drawtext.

    Prefers ``explicit_path`` (e.g. from CLI), then well-known system font
    candidates, then a filesystem-wide search for a bold TTF font.
    """
    if explicit_path:
        if Path(explicit_path).is_file():
            return explicit_path
        raise FileNotFoundError(f"Caption font not found: {explicit_path}")

    for candidate in DEFAULT_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate

    # Fallback: search common font directories for any bold TTF.
    roots = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path("C:/Windows/Fonts"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in ("**/*Bold.ttf", "**/*Bold.otf", "**/*BoldItalic.ttf"):
            for path in sorted(root.glob(pattern)):
                return str(path)
    raise FileNotFoundError(
        "No suitable TTF font found for video captions. Install fonts-dejavu-core "
        "or pass --caption-font / --caption-fontsize to configure."
    )
