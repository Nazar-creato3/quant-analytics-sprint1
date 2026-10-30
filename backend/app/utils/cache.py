"""
Redis-backed cache utility.
Provides typed get/set, JSON serialization, TTL, and an async decorator.

Process-local memory is a last-resort fallback when Redis is unreachable so
auth/2FA and overview singleflight do not hard-fail on a brief outage.
"""
from __future__ import annotations

import functools
import hashlib
import json
import threading
import time
from typing import Any, Callable, TypeVar

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ── Client pool ───────────────────────────────────────────────────────────────

_redis_pool: aioredis.Redis | None = None

# Process-local fallback: key -> (expires_at_monotonic, value)
_local_store: dict[str, tuple[float, Any]] = {}
_local_lock = threading.Lock()


def _local_get(key: str) -> Any | None:
    now = time.monotonic()
    with _local_lock:
        item = _local_store.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < now:
            _local_store.pop(key, None)
            return None
        return value


def _local_set(key: str, value: Any, ttl: int) -> None:
    with _local_lock:
        _local_store[key] = (time.monotonic() + max(1, int(ttl)), value)


def _local_delete(key: str) -> None:
    with _local_lock:
        _local_store.pop(key, None)


def _get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
            health_check_interval=30,
        )
    return _redis_pool


async def close_redis_client() -> None:
    """Close the module-level Redis client (required between Celery async runs)."""
    global _redis_pool
    if _redis_pool is None:
        return
    try:
        await _redis_pool.aclose()
    except Exception as exc:
        logger.debug("Redis client close failed", error=str(exc))
    finally:
        _redis_pool = None


# ── Low-level helpers ─────────────────────────────────────────────────────────

async def cache_get(key: str) -> Any | None:
    """Get a value from cache. Returns None on miss or error."""
    try:
        r = _get_redis()
        raw = await r.get(key)
        if raw is None:
            return _local_get(key)
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Cache GET failed, trying local", key=key, error=str(exc))
        return _local_get(key)


async def cache_set(
    key: str,
    value: Any,
    ttl: int | None = None,
) -> bool:
    """Set a value in cache with optional TTL (seconds). Returns True on success."""
    expire = ttl or settings.CACHE_TTL_SECONDS
    _local_set(key, value, expire)
    try:
        r = _get_redis()
        serialized = json.dumps(value, default=str)
        await r.setex(key, expire, serialized)
        return True
    except Exception as exc:
        logger.warning("Cache SET failed, local only", key=key, error=str(exc))
        return True  # local write succeeded


async def cache_lock_acquire(key: str, ttl: int = 20) -> bool:
    """SET NX lock. True = this caller fetches; False = wait for the winner."""
    try:
        r = _get_redis()
        return bool(await r.set(key, "1", nx=True, ex=ttl))
    except Exception as exc:
        existing = _local_get(key)
        if existing is not None:
            logger.debug("Cache lock acquire failed, local held", error=str(exc))
            return False
        _local_set(key, "1", ttl)
        return True


async def cache_lock_release(key: str) -> None:
    await cache_delete(key)


async def cache_delete(key: str) -> None:
    """Delete a key from cache."""
    _local_delete(key)
    try:
        r = _get_redis()
        await r.delete(key)
    except Exception as exc:
        logger.warning("Cache DELETE failed", key=key, error=str(exc))


async def cache_delete_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern. Returns count deleted."""
    try:
        r = _get_redis()
        keys = await r.keys(pattern)
        if not keys:
            return 0
        count = await r.delete(*keys)
        logger.debug("Cache pattern deleted", pattern=pattern, count=count)
        return count
    except Exception as exc:
        logger.warning("Cache DELETE pattern failed", pattern=pattern, error=str(exc))
        return 0


async def cache_exists(key: str) -> bool:
    try:
        r = _get_redis()
        return bool(await r.exists(key))
    except Exception:
        return _local_get(key) is not None


# ── Rate limiter ──────────────────────────────────────────────────────────────

def _rate_limit_key(identifier: str) -> str:
    return f"rl:{identifier}"


def _local_rl_peek(key: str, max_requests: int) -> tuple[bool, int, int]:
    raw = _local_get(key)
    if not isinstance(raw, dict):
        return True, max_requests, 0
    current = int(raw.get("count") or 0)
    expires = float(raw.get("expires") or 0)
    remaining_ttl = max(0, int(expires - time.monotonic()))
    remaining = max(0, max_requests - current)
    retry_after = remaining_ttl if current > max_requests else 0
    return (current <= max_requests), remaining, retry_after


def _local_rl_incr(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int, int]:
    with _local_lock:
        now = time.monotonic()
        item = _local_store.get(key)
        if item is None or item[0] < now or not isinstance(item[1], dict):
            payload = {"count": 1, "expires": now + window_seconds}
            _local_store[key] = (now + window_seconds, payload)
            remaining = max(0, max_requests - 1)
            return True, remaining, 0
        payload = dict(item[1])
        payload["count"] = int(payload.get("count") or 0) + 1
        expires = float(payload.get("expires") or (now + window_seconds))
        payload["expires"] = expires
        _local_store[key] = (expires, payload)
        current = int(payload["count"])
        remaining = max(0, max_requests - current)
        retry_after = max(0, int(expires - now)) if current > max_requests else 0
        return (current <= max_requests), remaining, retry_after


async def rate_limit_peek(
    identifier: str,
    max_requests: int,
    *,
    fail_closed: bool = False,
) -> tuple[bool, int, int]:
    """
    Read the current counter without incrementing.

    Returns: (is_allowed, remaining_requests, retry_after_seconds)
    """
    key = _rate_limit_key(identifier)
    try:
        r = _get_redis()
        current_raw, ttl = await r.get(key), await r.ttl(key)
        current = int(current_raw or 0)
        remaining = max(0, max_requests - current)
        retry_after = max(0, ttl) if current > max_requests else 0
        if current > max_requests and ttl < 0:
            retry_after = 0
        return (current <= max_requests), remaining, retry_after
    except Exception as exc:
        # Prefer process-local counters over blanket deny (Redis blip ≠ lockout).
        logger.warning("Rate limit peek failed, using local", error=str(exc), fail_closed=fail_closed)
        return _local_rl_peek(key, max_requests)


async def rate_limit_record_failure(
    identifier: str,
    max_requests: int,
    window_seconds: int,
    *,
    fail_closed: bool = False,
) -> tuple[bool, int, int]:
    """
    Increment the failure counter (sliding window via key TTL).

    Returns: (is_allowed, remaining_requests, retry_after_seconds)
    """
    key = _rate_limit_key(identifier)
    try:
        r = _get_redis()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        pipe.ttl(key)
        results = await pipe.execute()
        current = int(results[0])
        ttl = int(results[2])
        remaining = max(0, max_requests - current)
        retry_after = max(0, ttl) if current > max_requests else 0
        return (current <= max_requests), remaining, retry_after
    except Exception as exc:
        logger.warning("Rate limit record failed, using local", error=str(exc), fail_closed=fail_closed)
        return _local_rl_incr(key, max_requests, window_seconds)


async def rate_limit_clear(identifier: str) -> bool:
    """Ops helper: delete a rate-limit key."""
    key = _rate_limit_key(identifier)
    _local_delete(key)
    try:
        r = _get_redis()
        deleted = await r.delete(key)
        return bool(deleted)
    except Exception as exc:
        logger.warning("Rate limit clear failed", key=key, error=str(exc))
        return False


async def rate_limit_check(
    identifier: str,
    max_requests: int,
    window_seconds: int,
    *,
    fail_closed: bool = False,
) -> tuple[bool, int]:
    """
    Sliding-window rate limiter.

    Returns: (is_allowed, remaining_requests)

    When Redis is unavailable, process-local counters keep auth paths
    rate-limited (fail-closed semantics without a false global lockout).
    """
    key = _rate_limit_key(identifier)
    try:
        r = _get_redis()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        current = int(results[0])
        remaining = max(0, max_requests - current)
        return (current <= max_requests), remaining
    except Exception as exc:
        logger.warning("Rate limit check failed, using local", error=str(exc), fail_closed=fail_closed)
        allowed, remaining, _ = _local_rl_incr(key, max_requests, window_seconds)
        return allowed, remaining


# ── Caching decorator ─────────────────────────────────────────────────────────

def cached(
    key_prefix: str,
    ttl: int | None = None,
    key_builder: Callable[..., str] | None = None,
) -> Callable[[F], F]:
    """
    Async function caching decorator.

    Usage:
        @cached("quotes", ttl=60)
        async def get_quote(ticker: str) -> dict: ...

    The cache key is: "{key_prefix}:{sha256(args+kwargs)[:12]}"
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                raw = f"{args!r}:{sorted(kwargs.items())!r}"
                digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
                cache_key = f"{key_prefix}:{digest}"

            hit = await cache_get(cache_key)
            if hit is not None:
                logger.debug("Cache hit", key=cache_key)
                return hit

            result = await func(*args, **kwargs)

            if result is not None:
                await cache_set(cache_key, result, ttl=ttl)

            return result

        return wrapper  # type: ignore
    return decorator


# ── Pub/Sub for real-time events ──────────────────────────────────────────────

async def publish_event(channel: str, payload: dict) -> None:
    """Single entry: typed bus (Prompt 07) plus Redis pub/sub fan-out."""
    try:
        from app.services.event_bus.bus import publish_event as bus_publish
        from app.services.event_bus.types import EVENT_NAMES

        name = channel if channel in EVENT_NAMES else None
        if name:
            bus_publish(name, payload)
    except Exception as exc:
        logger.warning("Event bus publish failed", channel=channel, error=str(exc))
    try:
        r = _get_redis()
        await r.publish(channel, json.dumps(payload, default=str))
    except Exception as exc:
        logger.warning("Event publish failed", channel=channel, error=str(exc))


async def ping() -> bool:
    """Check Redis connectivity."""
    try:
        r = _get_redis()
        return await r.ping()
    except Exception:
        return False
