"""Live NIFTY quote from NSE, for intraday price action.

Everything else in this project runs on daily closes, which is fine for
research but means the dashboard shows yesterday's number during a live
session. This provides the actual current price.

Two things here are scar tissue, and both matter more than they look.

*One session, not one per call.* This used to build a fresh `NSELive()` for
every quote. Each one repeats NSE's cookie handshake and opens its own
socket, and on a dashboard polling every two seconds that is a new
connection every two seconds. NSE throttled us and closed them; twelve were
found sitting in CLOSE_WAIT, never reaped. One session is reused, and is
rebuilt only when a call through it fails.

*The lock is not held across the network.* It used to be. When NSE went
slow, the thread holding it stopped returning, and every later request
queued behind it — the tick endpoint hung permanently while the rest of the
API answered normally. Now one thread refreshes and the others are handed
the last value immediately.

A served value always carries `fetched_at` and `stale`, because a price with
no age on it is the exact thing DESIGN.md forbids: a stale number presented
as a current one.
"""

import threading
import time
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 15
_FETCH_LOCK = threading.Lock()
_SESSION_LOCK = threading.Lock()
_SESSION = None
# How long a caller with a usable older value will wait for a fresh one
# before giving up and serving what it has.
_WAIT_S = 6.0


# NSE's client library sends every request without a timeout, including the
# cookie handshake it makes when it is built. One socket NSE stopped answering
# on blocked its caller forever — and since polled paths hand everyone else the
# last value while one thread refreshes, the price, the market status and the
# option chain froze with nothing on screen saying so.
NSE_TIMEOUT_S = 8.0


def _timeout_session_class():
    import requests

    class _TimeoutSession(requests.Session):
        """requests has no session-wide timeout; this gives every call one."""

        def request(self, method, url, **kwargs):
            kwargs.setdefault("timeout", NSE_TIMEOUT_S)
            return super().request(method, url, **kwargs)

    return _TimeoutSession


def _session():
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            import jugaad_data.nse.live as live

            # NSELive builds its own requests.Session by that module-level
            # name, and uses it at once for the handshake.
            live.Session = _timeout_session_class()
            _SESSION = live.NSELive()
        return _SESSION


def _drop_session() -> None:
    """A session that just failed is not reused: its cookies may be expired
    or its connection half-closed, and the next call should start clean."""
    global _SESSION
    with _SESSION_LOCK:
        closer = getattr(getattr(_SESSION, "s", None), "close", None)
        if closer:
            try:
                closer()
            except Exception:
                pass
        _SESSION = None


def _aged(entry: tuple[float, dict]) -> dict:
    at, quote = entry
    age = time.monotonic() - at
    return {**quote, "age_s": round(age, 1), "stale": age >= _TTL}


def _fetch(index: str) -> dict:
    data = _session().all_indices()
    rows = data.get("data", []) if isinstance(data, dict) else []
    row = next((r for r in rows if r.get("index") == index), None)
    if row is None:
        raise RuntimeError(f"Index '{index}' not present in NSE live feed")
    vix_row = next((r for r in rows if r.get("index") == "INDIA VIX"), None)
    return {
        "index": row.get("index"),
        "last": row.get("last"),
        "change": row.get("variation"),
        "change_pct": row.get("percentChange"),
        "open": row.get("open"),
        "high": row.get("high"),
        "low": row.get("low"),
        "previous_close": row.get("previousClose"),
        "year_high": row.get("yearHigh"),
        "year_low": row.get("yearLow"),
        "india_vix": vix_row.get("last") if vix_row else None,
        "india_vix_change_pct": vix_row.get("percentChange") if vix_row else None,
        "source": "NSE live feed",
        "fetched_at": datetime.now(IST).isoformat(timespec="seconds"),
    }


def live_index_quote(index: str = "NIFTY 50") -> dict:
    """The current quote. Raises only when there is nothing to serve at all."""
    hit = _CACHE.get(index)
    if hit and (time.monotonic() - hit[0]) < _TTL:
        return _aged(hit)

    # With something usable in hand, wait briefly at most; with nothing,
    # this caller has to do the work.
    if hit is not None:
        if not _FETCH_LOCK.acquire(timeout=_WAIT_S):
            return _aged(hit)
    else:
        _FETCH_LOCK.acquire()
    try:
        hit = _CACHE.get(index)
        if hit and (time.monotonic() - hit[0]) < _TTL:
            return _aged(hit)
        try:
            quote = _fetch(index)
        except Exception:
            _drop_session()
            if hit is not None:
                return _aged(hit)  # last good price, labelled with its age
            raise
        _CACHE[index] = (time.monotonic(), quote)
        return _aged(_CACHE[index])
    finally:
        _FETCH_LOCK.release()


OPEN_AT = (9, 15)
CLOSE_AT = (15, 30)


def open_by_clock(now: datetime | None = None) -> bool:
    """What the clock says when NSE cannot be asked: a weekday between 09:15
    and 15:30 IST. It does not know holidays, so it is only ever shown as a
    guess beside an unknown status — never as the status itself."""
    now = (now or datetime.now(IST)).astimezone(IST)
    t = (now.hour, now.minute)
    return now.weekday() < 5 and OPEN_AT <= t < CLOSE_AT


def market_status() -> dict:
    """Whether the market is actually open — matters because a 'live' price
    outside session hours is just the last close wearing a live label."""
    try:
        data = _session().market_status()
    except Exception:
        _drop_session()
        raise
    markets = data.get("marketState", []) if isinstance(data, dict) else []
    cm = next((m for m in markets if m.get("market") == "Capital Market"), None)
    return {
        "market": cm.get("market") if cm else None,
        "status": cm.get("marketStatus") if cm else None,
        "trade_date": cm.get("tradeDate") if cm else None,
        "is_open": (cm.get("marketStatus", "").lower() == "open") if cm else False,
    }
