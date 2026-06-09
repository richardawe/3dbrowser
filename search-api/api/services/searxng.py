import os
from typing import Any, Optional

import httpx

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")

# Language code → SearXNG language mapping
_LANG_MAP = {
    "en": "en-US",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "pt": "pt-BR",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "zh-CN",
}

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


async def query(
    q: str,
    category: str = "general",
    pageno: int = 1,
    num: int = 10,
    language: Optional[str] = None,
    time_range: Optional[str] = None,
    safesearch: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "q": q,
        "categories": category,
        "format": "json",
        "pageno": pageno,
        "safesearch": safesearch,
    }
    if language:
        params["language"] = _LANG_MAP.get(language, language)
    if time_range:
        params["time_range"] = time_range

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{SEARXNG_URL}/search", params=params)
        resp.raise_for_status()
        return resp.json()
