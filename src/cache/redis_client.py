"""
Redis caching layer for MCP tool calls.
Falls back gracefully if Redis is unavailable — tools still work, just uncached.
"""

import os
import hashlib
import json
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

_client = None


def get_redis():
    global _client
    if _client is None:
        try:
            _client = redis.from_url(REDIS_URL, decode_responses=True)
            _client.ping()
        except Exception:
            _client = None
    return _client


def cache_key(tool_name: str, **params) -> str:
    param_str = json.dumps(params, sort_keys=True, default=str)
    h = hashlib.md5(param_str.encode()).hexdigest()[:12]
    return f"sportsbrain:{tool_name}:{h}"


def get_cached(tool_name: str, **params) -> str | None:
    r = get_redis()
    if r is None:
        return None
    try:
        return r.get(cache_key(tool_name, **params))
    except Exception:
        return None


def set_cached(tool_name: str, value: str, ttl: int = 3600, **params) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.setex(cache_key(tool_name, **params), ttl, value)
    except Exception:
        pass


def get_cache_stats() -> dict:
    """Get basic cache stats for monitoring."""
    r = get_redis()
    if r is None:
        return {"status": "disconnected"}
    try:
        info = r.info("stats")
        keys = r.dbsize()
        return {
            "status": "connected",
            "keys": keys,
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
        }
    except Exception as e:
        return {"status": f"error: {e}"}
