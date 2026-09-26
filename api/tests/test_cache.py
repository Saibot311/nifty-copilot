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


# --- the tick endpoint's hang, pinned -----------------------------------------

def test_a_wedged_producer_does_not_block_later_callers():
    """The live bug: NSE began throttling, a producer stopped returning, and
    because the key's lock was held across that call every later poll queued
    behind it. The tick endpoint hung for good while the rest of the API was
    fine. With stale_ok, one thread waits and everyone else is served."""
    import threading
    import time as _time

    from cache import cached, invalidate

    invalidate("wedged")
    cached("wedged", ttl_seconds=0, producer=lambda: "first")  # prime it

    release = threading.Event()

    def wedged():
        release.wait(10)
        return "second"

    stuck = threading.Thread(target=lambda: cached("wedged", 0, wedged), daemon=True)
    stuck.start()
    _time.sleep(0.2)  # let it take the lock

    started = _time.monotonic()
    got = cached("wedged", ttl_seconds=0, producer=lambda: "third", stale_ok=True)
    waited = _time.monotonic() - started

    release.set()
    stuck.join(timeout=10)

    assert got == "first", "a caller with a usable value must be served it, not queued"
    assert waited < 1.0, f"stale_ok waited {waited:.1f}s — it must not block"


def test_a_cold_key_still_produces_rather_than_returning_nothing():
    from cache import cached, invalidate

    invalidate("cold")
    assert cached("cold", ttl_seconds=60, producer=lambda: "made", stale_ok=True) == "made"


def test_wait_s_gives_up_on_a_slow_producer_and_serves_the_last_value():
    import threading
    import time as _time

    from cache import cached, invalidate

    invalidate("slow")
    cached("slow", ttl_seconds=0, producer=lambda: "old")
    release = threading.Event()
    t = threading.Thread(target=lambda: cached("slow", 0, lambda: (release.wait(10), "new")[1]), daemon=True)
    t.start()
    _time.sleep(0.2)
    assert cached("slow", ttl_seconds=0, producer=lambda: "never", wait_s=0.3) == "old"
    release.set()
    t.join(timeout=10)


def test_background_refresh_never_makes_the_caller_wait():
    """The tick answers every two seconds; the indices board rides along
    only from what is already in hand, refreshed on a thread of its own."""
    import threading
    import time as _t
    from cache import cached_background, invalidate

    invalidate("bg-test")
    release = threading.Event()
    calls = []

    def slow():
        calls.append(1)
        release.wait(5)
        return len(calls)

    t0 = _t.monotonic()
    assert cached_background("bg-test", 0, slow) is None         # nothing yet: answers at once
    assert cached_background("bg-test", 0, slow) is None         # one refresh at a time
    assert _t.monotonic() - t0 < 0.5 and len(calls) == 1
    release.set()
    for _ in range(50):
        if cached_background("bg-test", 60, slow) is not None:
            break
        _t.sleep(0.02)
    assert cached_background("bg-test", 60, slow) == 1


def test_a_failing_background_refresh_keeps_the_last_value():
    import time as _t
    from cache import _CACHE, cached_background, invalidate

    invalidate("bg-fail")
    _CACHE["bg-fail"] = (_t.monotonic() - 100, "old")

    def boom():
        raise RuntimeError("feed down")
    assert cached_background("bg-fail", 10, boom) == "old"
    _t.sleep(0.1)
    assert cached_background("bg-fail", 10, boom) == "old"
