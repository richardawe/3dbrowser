"""
Research agent: glm-4.7-flash with streaming tool calls → self-hosted search API.

Uses Ollama streaming so tokens arrive immediately — the large model never causes a
ReadTimeout because each individual read completes quickly even when total generation
takes several minutes.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, AsyncGenerator

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
RESEARCH_MODEL = "glm-4.7-flash:latest"
MAX_ROUNDS = 5

# No read timeout — the 29.9B model is slow; connect must succeed within 10s
_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information. Returns titles, URLs, and snippets.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_search",
            "description": "Search for recent news articles on a topic.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The news search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_url",
            "description": "Read and extract the full content of a specific webpage URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Full URL to extract"}},
                "required": ["url"],
            },
        },
    },
]


def _strip_think(text: str) -> str:
    """Remove GLM's <think>…</think> reasoning blocks from the final text."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def _call_tool(name: str, args: dict, search_url: str, api_key: str) -> str:
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as http:
        if name == "web_search":
            r = await http.post(
                f"{search_url}/search", headers=headers,
                json={"q": args.get("query", ""), "num": 8, "response_format": "text"},
            )
            return r.text[:4000]
        if name == "news_search":
            r = await http.post(
                f"{search_url}/news", headers=headers,
                json={"q": args.get("query", ""), "num": 8, "response_format": "text"},
            )
            return r.text[:4000]
        if name == "extract_url":
            r = await http.post(
                f"{search_url}/extract", headers=headers,
                json={"url": args.get("url", ""), "mode": "auto"},
            )
            d = r.json()
            rows = d.get("rows", [])[:20]
            return f"Title: {d.get('title', '')}\nData: {json.dumps(rows)[:2000]}"
    return "Unknown tool"


async def research(
    question: str,
    search_url: str,
    api_key: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Agentic research loop with streaming.
    Yields:
      answer_chunk  — token during streaming (for live display)
      clear_answer  — discard streamed tokens (model just called tools)
      tool_call     — model invoked a tool
      tool_result   — tool completed
      answer        — complete final answer text (for server to save)
      sources       — list of queries that were searched
      images        — related images
      error         — something went wrong
    """
    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are a research assistant with web search tools. "
                "Use tools to find current, accurate information before answering. "
                "Search multiple times if needed. Write a detailed, well-structured answer. "
                "Cite each source inline as [1], [2], etc."
            ),
        },
        {"role": "user", "content": question},
    ]
    sources: list[dict] = []

    for _ in range(MAX_ROUNDS):
        raw_buffer = ""          # everything the model streams (including think tags)
        visible_buffer = ""      # tokens we actually sent to the frontend
        final_tool_calls: list = []
        in_think = False

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                async with http.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": RESEARCH_MODEL,
                        "messages": messages,
                        "tools": TOOLS,
                        "stream": True,
                        "options": {"temperature": 0.3},
                    },
                ) as resp:
                    async for raw_line in resp.aiter_lines():
                        if not raw_line:
                            continue
                        try:
                            chunk = json.loads(raw_line)
                        except json.JSONDecodeError:
                            continue

                        msg = chunk.get("message", {})
                        token = msg.get("content", "")
                        done = chunk.get("done", False)

                        if done:
                            final_tool_calls = msg.get("tool_calls") or []
                            break

                        if token:
                            raw_buffer += token

                            # Track think-block state (simple substring check)
                            if "<think>" in token:
                                in_think = True
                            if "</think>" in token:
                                in_think = False
                                continue  # skip the closing tag token

                            if not in_think:
                                visible_buffer += token
                                yield {"type": "answer_chunk", "token": token}

        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            yield {"type": "error", "message": f"Ollama timeout: {exc}"}
            return
        except httpx.ConnectError:
            yield {"type": "error", "message": "Cannot reach Ollama. Is it running on port 11434?"}
            return
        except Exception as exc:
            yield {"type": "error", "message": f"Ollama error: {exc}"}
            return

        if final_tool_calls:
            # Model called tools — discard anything streamed so far (was preamble/thinking)
            yield {"type": "clear_answer"}
            visible_buffer = ""

            messages.append({
                "role": "assistant",
                "content": _strip_think(raw_buffer),
                "tool_calls": final_tool_calls,
            })

            for tc in final_tool_calls:
                fn = tc["function"]["name"]
                raw = tc["function"].get("arguments", {})
                args = raw if isinstance(raw, dict) else json.loads(raw or "{}")
                label = args.get("query") or args.get("url", "")

                yield {"type": "tool_call", "name": fn, "query": label}
                result = await _call_tool(fn, args, search_url, api_key)

                if fn in ("web_search", "news_search"):
                    sources.append({"query": args.get("query", ""), "type": fn})

                yield {"type": "tool_result", "name": fn}
                messages.append({"role": "tool", "content": result})

        else:
            # No tool calls — answer is done (already streamed as chunks)
            final_content = _strip_think(raw_buffer)
            yield {"type": "answer", "content": final_content}
            break

    yield {"type": "sources", "items": sources}

    # Fetch related images
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as http:
            r = await http.post(
                f"{search_url}/images",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={"q": question, "num": 6},
            )
            imgs = r.json().get("images", [])[:6]
            yield {
                "type": "images",
                "items": [
                    {
                        "url": i.get("thumbnailUrl") or i.get("imageUrl", ""),
                        "link": i.get("link", ""),
                        "title": i.get("title", ""),
                    }
                    for i in imgs
                    if i.get("thumbnailUrl") or i.get("imageUrl")
                ],
            }
    except Exception:
        pass
