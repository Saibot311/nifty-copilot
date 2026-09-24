"""Tiny in-process TTL cache for expensive computations (research runs,
pattern proximity, the recommendation).

One lock per key, held while that key's value is computed: ten concurrent
dashboard loads asking for the same thing trigger one computation, not ten.
It used to be a single global lock, which (a) made every cached endpoint
wait on every other one, and (b) deadlocked as soon as one cached producer
called cached() for a different key — the recommendation caching the
proximity result — because the thread was waiting on a lock it already held.

`stale_ok` exists because of a live one. The tick endpoint caches for two
seconds and is polled every two seconds by every open dashboard. When NSE
began throttling us, its producer stopped returning; the key's lock was
held across that call, so every later poll queued behind it and the tick
endpoint hung for good while the rest of the API answered normally. A
dashboard asking "what is the price now" must never wait in a queue: with
`stale_ok`, one thread refreshes and everyone else is handed the last value
immediately. A value two seconds old is the right answer to that question.
A value that arrives ninety seconds late is not an answer at all.
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


def cached(key: str, ttl_seconds: int, producer: Callable[[], Any],
           stale_ok: bool = False, wait_s: float | None = None) -> Any:
    """The cached value, producing it if it is missing or past its TTL.

    stale_ok: rather than wait for another thread's refresh, return the last
    value at once. Only the first caller of a cold key ever blocks. Use it
    for anything on a polling path, where being late is worse than being a
    little behind.

    wait_s: give up waiting for the lock after this long and fall back to
    the stale value. A producer that never returns then costs one thread
    instead of every thread that follows it.
    """
    hit = _CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < ttl_seconds:
        return hit[1]

    lock = _lock_for(key)
    have_stale = hit is not None
    if stale_ok and have_stale:
        if not lock.acquire(blocking=False):
            return hit[1]  # someone is already refreshing; the last value will do
    elif wait_s is not None and have_stale:
        if not lock.acquire(timeout=wait_s):
            return hit[1]
    else:
        lock.acquire()
    try:
        # Re-check: the thread we may have queued behind has just filled it.
        hit = _CACHE.get(key)
        if hit and (time.monotonic() - hit[0]) < ttl_seconds:
            return hit[1]
        value = producer()
        _CACHE[key] = (time.monotonic(), value)
        return value
    finally:
        lock.release()


def invalidate(key: str | None = None) -> None:
    with _REGISTRY_LOCK:
        if key is None:
            _CACHE.clear()
        else:
            _CACHE.pop(key, None)
