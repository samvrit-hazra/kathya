"""Wikimedia Commons image discovery and download."""

from pathlib import Path

import requests

from ..config import WIKIMEDIA_API_URL, WIKIMEDIA_NAMESPACE, WIKIMEDIA_SEARCH_LIMIT, WIKIMEDIA_THUMB_WIDTH


def _search_image_urls(keywords: list[str], limit: int) -> list[tuple[str, str, str]]:
    """Return a list of (title, url, mime) horizontal image candidates from Wikimedia Commons."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": "|".join(keywords),
        "gsrnamespace": WIKIMEDIA_NAMESPACE,
        "gsrslimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": WIKIMEDIA_THUMB_WIDTH,
    }
    response = requests.get(WIKIMEDIA_API_URL, params=params, timeout=25, headers={"User-Agent": "voiceover2video/0.1 (story-to-video tool)"})
    response.raise_for_status()
    data = response.json()
    pages = data.get("query", {}).get("pages") or {}
    candidates: list[tuple[str, str, str]] = []
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url") or ""
        mime = info.get("mime") or ""
        if not url or not mime.startswith("image/"):
            continue
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if width and height and height > width:
            # Skip portrait images: slideshow slides read best in landscape.
            continue
        candidates.append((str(page.get("title") or ""), url, mime))
    return candidates


def find_and_download_image(
    keywords: list[str],
    work_dir,
    dest_stem: str,
) -> str | None:
    """Search Wikimedia Commons for an image matching the keywords and download it.

    Tries the combined keyword set first, then each individual keyword as a
    fallback (some story keywords are generic and return no Commons results).

    Returns the local file path of the downloaded image, or ``None`` if no
    suitable image could be found (caller should fall back to a colored slide).
    """
    if not keywords:
        return None

    queries: list[list[str]] = [list(keywords)]
    for keyword in keywords:
        if keyword and [keyword] not in queries:
            queries.append([keyword])

    for query in queries:
        try:
            candidates = _search_image_urls(query, WIKIMEDIA_SEARCH_LIMIT)
        except Exception:
            # Network/API hiccup -> graceful fallback to next query.
            continue
        if not candidates:
            continue
        for title, url, mime in candidates:
            try:
                response = requests.get(url, timeout=30, stream=True, headers={"User-Agent": "voiceover2video/0.1 (story-to-video tool)"})
                response.raise_for_status()
                mime_type = (mime or "").split(";")[0].strip().lower()
                subtype = mime_type.split("/")[-1] if "/" in mime_type else ""
                ext_map = {
                    "jpeg": ".jpg",
                    "jpg": ".jpg",
                    "png": ".png",
                    "gif": ".gif",
                    "webp": ".webp",
                    "tiff": ".tif",
                    "bmp": ".bmp",
                }
                ext = ext_map.get(subtype, ".jpg" if mime_type.startswith("image/jpeg") else ".png")
                dest = Path(str(work_dir).rstrip("/")) / f"{dest_stem}{ext}"
                dest.write_bytes(response.content)
                return str(dest)
            except Exception:
                continue

    return None
