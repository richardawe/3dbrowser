import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from routers import extract, images, news, search, videos
from services.cache import close_redis

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
API_KEYS: set[str] = set(
    k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()
)
RATE_LIMIT = os.getenv("RATE_LIMIT", "60/minute")
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080")

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# API key security (optional — skip if no keys configured)
# ---------------------------------------------------------------------------
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    if not API_KEYS:
        return  # no keys configured → open access
    if api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(
    title="Self-Hosted Search API",
    description="Drop-in replacement for Serper.dev / SerpAPI powered by SearXNG",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers (all search routes require API key)
# ---------------------------------------------------------------------------
_auth = [Depends(verify_api_key)]
app.include_router(search.router, dependencies=_auth)
app.include_router(news.router, dependencies=_auth)
app.include_router(images.router, dependencies=_auth)
app.include_router(videos.router, dependencies=_auth)
app.include_router(extract.router, dependencies=_auth)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health", include_in_schema=False)
@limiter.exempt
async def health():
    searxng_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{SEARXNG_URL}/search", params={"q": "ping", "format": "json"})
            searxng_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "searxng": "up" if searxng_ok else "unreachable",
        "version": "1.0.0",
    }


# ---------------------------------------------------------------------------
# Rate-limited root
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Search API running. POST /search, /news, /images, /videos"}
