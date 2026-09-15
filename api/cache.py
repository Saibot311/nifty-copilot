"""Tiny TTL cache for expensive research endpoints.

The options strike sweep runs a full backtest per grid cell against the
SQLite archive — far too slow to recompute on every dashboard page load,
but it's historical analysis that doesn't change minute to minute. Cache
it briefly rather than making every page view pay for it.

Deliberately short TTLs: the options archive is still being backfilled, so
results legitimately change as more history lands. A long cache would
quietly serve stale conclusions.
"""

import threading
import time
from typing import Any, Callable

_CACHE: dict[str, tuple[float, Any]] = {}
_LOCK = threading.Lock()


def cached(key: str, ttl_seconds: int, producer: Callable[[], Any]) -> Any:
    """Returns a cached value or computes it. The lock is held across the
    computation so ten concurrent dashboard loads trigger one run, not ten
    — the same cache-stampede problem the market-data provider hit."""
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < ttl_seconds:
            return hit[1]
        value = producer()
        _CACHE[key] = (time.monotonic(), value)
        return value


def invalidate(key: str | None = None) -> None:
    with _LOCK:
        if key is None:
            _CACHE.clear()
        else:
            _CACHE.pop(key, None)
