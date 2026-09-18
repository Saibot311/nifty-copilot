"""Tiny in-process TTL cache for expensive computations (research runs,
pattern proximity, the recommendation).

One lock per key, held while that key's value is computed: ten concurrent
dashboard loads asking for the same thing trigger one computation, not ten.
It used to be a single global lock, which (a) made every cached endpoint
wait on every other one, and (b) deadlocked as soon as one cached producer
called cached() for a different key — the recommendation caching the
proximity result — because the thread was waiting on a lock it already held.
"""

import threading
import time
from typing import Any, Callable

_CACHE: dict[str, tuple[float, Any]] = {}
_KEY_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _REGISTRY_LOCK:
        return _KEY_LOCKS.setdefault(key, threading.Lock())


def cached(key: str, ttl_seconds: int, producer: Callable[[], Any]) -> Any:
    with _lock_for(key):
        hit = _CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < ttl_seconds:
            return hit[1]
        value = producer()
        _CACHE[key] = (time.monotonic(), value)
        return value


def invalidate(key: str | None = None) -> None:
    with _REGISTRY_LOCK:
        if key is None:
            _CACHE.clear()
        else:
            _CACHE.pop(key, None)
