"""
QA reviewer: lfm2.5-thinking checks every research answer and news briefing.
Returns score (1-10), verdict, and a list of concerns.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
QA_MODEL = "lfm2.5-thinking:latest"


def _parse_json(text: str) -> dict:
    """Strip thinking tags and extract the first JSON object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


async def _run(prompt: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=40) as http:
            r = await http.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": QA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
        result = _parse_json(r.json().get("response", "{}"))
        return {
            "score": max(0, min(10, int(result.get("score", 0)))),
            "verdict": str(result.get("verdict", "Unknown")),
            "concerns": [str(c) for c in result.get("concerns", [])],
        }
    except Exception as exc:
        return {"score": 0, "verdict": "QA unavailable", "concerns": [str(exc)[:120]]}


async def review_research(question: str, answer: str) -> dict[str, Any]:
    prompt = (
        f"Question: {question}\n\n"
        f"Answer (excerpt): {answer[:2000]}\n\n"
        "Evaluate this answer for completeness, accuracy, and source quality.\n"
        "Reply with ONLY valid JSON — no preamble, no markdown:\n"
        '{"score": <1-10>, "verdict": "<Excellent|Good|Fair|Poor>", '
        '"concerns": ["<up to 3 brief concerns>"]}'
    )
    return await _run(prompt)


async def review_briefing(topics: list[str], results: list[dict]) -> dict[str, Any]:
    summaries = "\n".join(
        f"[{r.get('topic', '')}]: {r.get('summary', '')[:300]}" for r in results
    )
    prompt = (
        f"Topics: {', '.join(topics)}\n\n"
        f"Summaries:\n{summaries}\n\n"
        "Rate this news briefing for accuracy, coverage, and clarity.\n"
        "Reply with ONLY valid JSON — no preamble, no markdown:\n"
        '{"score": <1-10>, "verdict": "<Excellent|Good|Fair|Poor>", '
        '"concerns": ["<up to 3 brief concerns>"]}'
    )
    return await _run(prompt)
