"""
Small, dependency-free utilities shared by the tools and the CMC client:

  - TTLCache: a thread/async-safe in-memory cache with per-entry expiry.
    Used to avoid re-hitting the CMC API for data that doesn't change on
    every request (the RWA map, issuer lists, global metrics, etc).

  - AsyncRateLimiter: a token-bucket limiter that throttles outbound CMC
    API calls to stay under the plan's requests-per-minute ceiling, so the
    server degrades gracefully (queues/waits) instead of hammering the API
    and burning through 429s.

Both are process-local (in-memory), which is the right scope for a single
MCP server process talking to one CMC API key.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Callable, Dict, Optional, Tuple


class TTLCache:
    """A minimal time-to-live cache safe for use from async code.

    Not distributed - this lives in the MCP server process's memory and
    resets on restart, which is exactly what we want for a hackathon-scale
    single-process server.
    """

    def __init__(self, default_ttl_seconds: float = 60.0, max_entries: int = 1000) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._default_ttl = default_ttl_seconds
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    def _is_expired(self, expires_at: float) -> bool:
        return time.monotonic() >= expires_at

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if self._is_expired(expires_at):
                self._store.pop(key, None)
                return None
            return value

    async def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        async with self._lock:
            if len(self._store) >= self._max_entries and key not in self._store:
                # Evict the entry closest to expiry to make room, rather than
                # growing unbounded. O(n) is fine at this scale (<=1000 entries).
                oldest_key = min(self._store, key=lambda k: self._store[k][0], default=None)
                if oldest_key is not None:
                    self._store.pop(oldest_key, None)
            ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
            self._store[key] = (time.monotonic() + ttl, value)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()

    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl_seconds: Optional[float] = None,
    ) -> Any:
        """Returns the cached value, or awaits `factory()` (sync or async) and caches it."""
        cached = await self.get(key)
        if cached is not None:
            return cached

        result = factory()
        if asyncio.iscoroutine(result):
            result = await result

        await self.set(key, result, ttl_seconds)
        return result


class AsyncRateLimiter:
    """A sliding-window token bucket limiter for outbound API calls.

    Guarantees no more than `max_calls` complete within any rolling
    `period_seconds` window. Callers that would exceed the limit `await`
    inside `acquire()` until a slot frees up, rather than failing - this
    is what keeps the server well-behaved against CMC's per-minute limits
    instead of just catching 429s after the fact.
    """

    def __init__(self, max_calls: int, period_seconds: float = 60.0) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        self._max_calls = max_calls
        self._period = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                # Drop timestamps that have fallen out of the window.
                while self._timestamps and now - self._timestamps[0] >= self._period:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_calls:
                    self._timestamps.append(now)
                    return

                # Window is full - figure out how long until the oldest
                # call ages out, then wait (outside the lock) and retry.
                wait_for = self._period - (now - self._timestamps[0])

            await asyncio.sleep(max(wait_for, 0.01))

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


# Shared, module-level cache instance used by tools that want simple
# response caching (e.g. issuer lists, global metrics) without wiring
# their own TTLCache.
shared_cache = TTLCache(default_ttl_seconds=60.0)
