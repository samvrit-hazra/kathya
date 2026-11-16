"""The Kathya tool catalogue.

Each entry is a tool that already works from the command line. Kathya does not
import it: it runs the command in a background job, the way you would run it in
a terminal. That keeps tools independent and lets you add one by dropping its
folder next to the others and describing it here.

Each tool also has its own page under web/, named by `page`. The index lists the
tools as tiles and links to those pages.

Placeholders filled for every run:
    {python}   interpreter running Kathya
    {root}     this repository
    {output}   where the tool must write its finished file
    {work}     a scratch directory for the job
    {<input>}  one placeholder per input field name
"""

TOOLS = [
    {
        "id": "voiceover2video",
        "name": "Voiceover to video",
        "tagline": "Turn a recorded narration into a slideshow with your own words as captions.",
        "page": "voiceover2video.html",
        "action": "Generate video",
        "inputs": [
            {
                "name": "voiceover",
                "kind": "file",
                "label": "Voiceover",
                "hint": "mp3, wav, m4a, mp4 · up to 100 MB",
                "accept": "audio/*,video/*",
                "suffixes": [
                    ".mp3", ".wav", ".m4a", ".mp4", ".mpeg", ".mpga", ".ogg",
                    ".oga", ".flac", ".webm", ".aac", ".mov", ".mkv",
                ],
            }
        ],
        "command": [
            "{python}", "-m", "voiceover2video",
            "--voiceover", "{voiceover}",
            "-o", "{output}",
            "--work-dir", "{work}",
        ],
        "output_name": "video.mp4",
        "output_type": "video/mp4",
    },
]

PUBLIC_FIELDS = ("id", "name", "tagline", "page", "action", "inputs", "output_type")


def get_tool(tool_id: str) -> dict | None:
    for tool in TOOLS:
        if tool["id"] == tool_id:
            return tool
    return None


def public_catalogue() -> list[dict]:
    """The catalogue without local paths or commands (safe for the browser)."""
    return [{key: tool[key] for key in PUBLIC_FIELDS} for tool in TOOLS]
