"""
News briefing generator.
For each topic: fetches news → lfm2.5-thinking summarises to 5 bullets → fetches image.
Yields SSE-ready event dicts.
"""
from __future__ import annotations

import os
from typing import Any, AsyncGenerator

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
BRIEFING_MODEL = "lfm2.5-thinking:latest"


async def run_briefing(
    topics: list[str],
    search_url: str,
    api_key: str,
) -> AsyncGenerator[dict[str, Any], None]:
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    for topic in topics:
        yield {"type": "briefing_topic_start", "topic": topic}

        # ── Fetch news ────────────────────────────────────────────────────────
        news_text = ""
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.post(
                    f"{search_url}/news",
                    headers=headers,
                    json={"q": topic, "num": 10, "response_format": "text"},
                )
                news_text = r.text
        except Exception as exc:
            yield {"type": "briefing_topic_error", "topic": topic, "error": str(exc)}
            continue

        # ── Summarise ─────────────────────────────────────────────────────────
        summary = "Summary unavailable."
        try:
            prompt = (
                f"Summarise the latest news about '{topic}' into exactly 5 bullet points.\n\n"
                f"News results:\n{news_text[:3000]}\n\n"
                "Write 5 concise, factual bullets. Each must start with '•'. "
                "No intro text, no conclusion — just the 5 bullets."
            )
            async with httpx.AsyncClient(timeout=60) as http:
                r = await http.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": BRIEFING_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.2},
                    },
                )
            raw = r.json().get("response", "")
            # Strip any <think>…</think> block the model emits
            import re
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            summary = raw or "Summary unavailable."
        except Exception:
            pass

        # ── Fetch images ──────────────────────────────────────────────────────
        images: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(
                    f"{search_url}/images",
                    headers=headers,
                    json={"q": topic + " news", "num": 4},
                )
                for img in r.json().get("images", [])[:4]:
                    url = img.get("thumbnailUrl") or img.get("imageUrl", "")
                    if url:
                        images.append(
                            {
                                "url": url,
                                "link": img.get("link", ""),
                                "title": img.get("title", ""),
                            }
                        )
        except Exception:
            pass

        yield {
            "type": "briefing_topic_done",
            "topic": topic,
            "summary": summary,
            "images": images,
        }
