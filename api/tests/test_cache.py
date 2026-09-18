"""The cache must allow one cached computation to use another (the
recommendation caches pattern proximity) without deadlocking, while still
running a key's producer only once under concurrent requests."""

import threading
import time

from cache import cached, invalidate


def _in_thread(fn, timeout=5):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("v", fn()), daemon=True)
    t.start()
    t.join(timeout)
    return t.is_alive(), out.get("v")


def test_nested_cached_calls_with_different_keys_do_not_deadlock():
    invalidate()
    hung, value = _in_thread(lambda: cached("outer", 60, lambda: cached("inner", 60, lambda: 42) + 1))
    assert not hung, "nested cached() deadlocked"
    assert value == 43


def test_concurrent_requests_for_one_key_compute_once():
    invalidate()
    calls = []

    def slow():
        calls.append(1)
        time.sleep(0.2)
        return "done"

    threads = [threading.Thread(target=lambda: cached("same", 60, slow)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


def test_different_keys_compute_in_parallel():
    invalidate()
    start = time.monotonic()
    threads = [threading.Thread(target=lambda k=k: cached(k, 60, lambda: time.sleep(0.3))) for k in "abcd"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.monotonic() - start < 0.9  # serialized would take ~1.2s
