import hashlib
import json
import os
from typing import Any, Optional

import redis.asyncio as aioredis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_redis: Optional[aioredis.Redis] = None

TTL = {
    "web": 3600,      # 1 hour
    "news": 900,      # 15 minutes
    "images": 3600,
    "videos": 3600,
}


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _make_key(category: str, query: str, params: dict) -> str:
    raw = json.dumps({"category": category, "q": query, **params}, sort_keys=True)
    return "search:" + hashlib.sha256(raw.encode()).hexdigest()


async def get_cached(category: str, query: str, params: dict) -> Optional[Any]:
    r = await get_redis()
    key = _make_key(category, query, params)
    value = await r.get(key)
    if value:
        return json.loads(value)
    return None


async def set_cached(category: str, query: str, params: dict, data: Any) -> None:
    r = await get_redis()
    key = _make_key(category, query, params)
    ttl = TTL.get(category, 3600)
    await r.setex(key, ttl, json.dumps(data))


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
