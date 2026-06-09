# Self-Hosted Search API

A free, self-hosted search API powered by [SearXNG](https://searxng.org/), with a FastAPI wrapper, Redis caching, and a built-in frontend tester. Drop-in replacement for Serper.dev and SerpAPI.

## Stack

| Service | Role |
|---------|------|
| SearXNG | Queries 70+ search engines (Google, Bing, DuckDuckGo, Brave…) |
| FastAPI | REST API wrapper with auth, rate limiting, caching |
| Redis | Response cache (1h for web/images/video, 15m for news) |
| nginx | Serves the frontend and proxies to the API |

## Quickstart

```bash
# 1. Clone and enter the directory
cd search-api

# 2. Set your API key
echo "API_KEYS=your-secret-key" > .env

# 3. Start everything
docker compose up -d

# 4. Open the frontend
open http://localhost:3001

# 5. Test the API
curl -X POST http://localhost:8000/search \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"q": "hello world", "num": 5}'
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/search` | Web search (Serper-compatible) |
| `POST` | `/news` | News search |
| `POST` | `/images` | Image search |
| `POST` | `/videos` | Video search |
| `POST` | `/extract` | Extract tables/links/lists from any URL → CSV |
| `GET` | `/health` | Health check |

### Request body (all search endpoints)

```json
{
  "q": "your query",
  "num": 10,
  "page": 1,
  "hl": "en",
  "response_format": "json"
}
```

Set `"response_format": "text"` to get plain-text output optimised for LLM prompts.

### Extract endpoint

```json
{
  "url": "https://example.com/data-page",
  "mode": "auto",
  "table_index": 0
}
```

Modes: `auto` (default), `tables`, `links`, `list`.

## MCP Server (Claude / LLM tool use)

Install dependencies and register with Claude Desktop:

```bash
pip install mcp httpx
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "search": {
      "command": "python",
      "args": ["/path/to/search-api/mcp_server.py"],
      "env": {
        "SEARCH_API_URL": "http://localhost:8000",
        "SEARCH_API_KEY": "your-secret-key"
      }
    }
  }
}
```

Exposes 5 tools: `web_search`, `news_search`, `image_search`, `video_search`, `extract_url`.

## Environment variables (.env)

```
API_KEYS=key1,key2          # Comma-separated. Leave blank for open access.
RATE_LIMIT=60/minute        # Per-IP rate limit
CORS_ORIGINS=*              # Allowed origins
```

## Deploying to a VPS

```bash
scp -r search-api/ root@your-server:/opt/search-api
ssh root@your-server "cd /opt/search-api && docker compose up -d"
```

Set `SEARCH_API_URL` in your apps to point to `http://your-server:8000`.
