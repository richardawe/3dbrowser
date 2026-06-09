#!/usr/bin/env python3
"""
MCP server — wraps the self-hosted Search API as tools for Claude and other LLMs.

Install:
  pip install mcp httpx

Run (stdio transport, for Claude Desktop):
  python mcp_server.py

Register in Claude Desktop  (~/.config/claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "search": {
        "command": "python",
        "args": ["/Users/3d7tech/3dbrowser/search-api/mcp_server.py"],
        "env": {
          "SEARCH_API_URL": "http://localhost:8000",
          "SEARCH_API_KEY": "my-secret-key-change-me"
        }
      }
    }
  }

On macOS the config file lives at:
  ~/Library/Application Support/Claude/claude_desktop_config.json
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP

SEARCH_API_URL = os.getenv("SEARCH_API_URL", "http://localhost:8000").rstrip("/")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "my-secret-key-change-me")

mcp = FastMCP(
    "Search API",
    instructions=(
        "Use these tools to search the web, find news, look up images/videos, "
        "and extract structured data from URLs. All results come from a private "
        "self-hosted search engine — no data is sent to third-party APIs."
    ),
)


def _headers() -> dict:
    return {"X-API-Key": SEARCH_API_KEY, "Content-Type": "application/json"}


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
def web_search(query: str, num: int = 10, language: str = "en") -> str:
    """
    Search the web for any topic.
    Returns numbered results with title, URL, and snippet — optimised for LLM reading.

    Args:
        query:    The search query.
        num:      Number of results to return (1–20, default 10).
        language: Two-letter language code, e.g. "en", "es", "fr" (default "en").
    """
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            f"{SEARCH_API_URL}/search",
            headers=_headers(),
            json={"q": query, "num": min(num, 20), "hl": language, "response_format": "text"},
        )
        resp.raise_for_status()
        return resp.text


@mcp.tool()
def news_search(query: str, num: int = 10) -> str:
    """
    Search for recent news articles on any topic.
    Returns numbered results with title, URL, source, and snippet.

    Args:
        query: The news search query.
        num:   Number of articles to return (1–20, default 10).
    """
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            f"{SEARCH_API_URL}/news",
            headers=_headers(),
            json={"q": query, "num": min(num, 20), "response_format": "text"},
        )
        resp.raise_for_status()
        return resp.text


@mcp.tool()
def image_search(query: str, num: int = 10) -> str:
    """
    Search for images on any topic.
    Returns image URLs, titles, and source pages.

    Args:
        query: What to search for.
        num:   Number of images to return (1–20, default 10).
    """
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            f"{SEARCH_API_URL}/images",
            headers=_headers(),
            json={"q": query, "num": min(num, 20)},
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("images", [])
    if not results:
        return f'No image results found for "{query}".'

    lines = [f'Image results for: "{query}"\n']
    for r in results:
        lines.append(f"{r['position']}. {r['title']}")
        lines.append(f"   Image URL:  {r['imageUrl']}")
        if r.get("link"):
            lines.append(f"   Source page: {r['link']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def video_search(query: str, num: int = 10) -> str:
    """
    Search for videos on any topic.
    Returns video titles, URLs, duration, and descriptions.

    Args:
        query: What to search for.
        num:   Number of videos to return (1–20, default 10).
    """
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            f"{SEARCH_API_URL}/videos",
            headers=_headers(),
            json={"q": query, "num": min(num, 20)},
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("videos", [])
    if not results:
        return f'No video results found for "{query}".'

    lines = [f'Video results for: "{query}"\n']
    for r in results:
        lines.append(f"{r['position']}. {r['title']}")
        lines.append(f"   URL: {r['link']}")
        if r.get("duration"):
            lines.append(f"   Duration: {r['duration']}")
        if r.get("source"):
            lines.append(f"   Platform: {r['source']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:200]}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def extract_url(url: str, mode: str = "auto", table_index: int = 0) -> str:
    """
    Extract structured data from any URL — tables, link directories, or lists.
    Returns data as a readable text table plus metadata.

    Args:
        url:         The URL to extract data from.
        mode:        Extraction strategy: "auto" (default), "tables", "links", or "list".
        table_index: Which table to extract when a page has multiple (0 = first).
    """
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{SEARCH_API_URL}/extract",
            headers=_headers(),
            json={"url": url, "mode": mode, "table_index": table_index},
        )
        resp.raise_for_status()
        data = resp.json()

    columns = data.get("columns", [])
    rows = data.get("rows", [])
    count = data.get("count", 0)
    title = data.get("title", "")
    mode_used = data.get("mode", mode)

    lines = [f"Extracted from: {url}"]
    if title:
        lines.append(f"Page title: {title}")
    lines.append(f"Mode: {mode_used} | {count} rows | Columns: {', '.join(columns)}\n")

    col_widths = [max(len(c), max((len(str(r[i])) for r in rows[:50] if i < len(r)), default=0)) for i, c in enumerate(columns)]
    header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
    lines.append(header)
    lines.append("-" * len(header))

    for row in rows[:50]:
        lines.append(" | ".join(str(row[i] if i < len(row) else "").ljust(col_widths[i])[:col_widths[i]] for i in range(len(columns))))

    if count > 50:
        lines.append(f"\n... {count - 50} more rows not shown. Full data available via the API.")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
