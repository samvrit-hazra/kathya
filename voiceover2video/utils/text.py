"""Caption text handling: splitting narration into display-friendly lines."""

from PIL import ImageFont


def wrap_caption_lines(
    text: str,
    font_path: str,
    font_size: float,
    max_width: float,
    max_lines: int = 3,
) -> list[str]:
    """Wrap ``text`` into at most ``max_lines`` lines that fit ``max_width`` px."""
    words = (text or "").split()
    if not words:
        return [""]

    font = ImageFont.truetype(font_path, int(font_size))
    ascent, descent = font.getmetrics()
    line_height = ascent + descent

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            if len(lines) >= max_lines:
                break
            current = word
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)

    return lines or [""]
