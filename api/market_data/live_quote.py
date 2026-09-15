"""Live NIFTY quote from NSE, for intraday price action.

Everything else in this project runs on daily closes, which is fine for
research but means the dashboard shows yesterday's number during a live
session. This provides the actual current price.

Cached for a few seconds so a dashboard load doesn't hammer NSE, and
raises rather than returning stale or invented values when unreachable.
"""

import threading
import time

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 15
_LOCK = threading.Lock()


def live_index_quote(index: str = "NIFTY 50") -> dict:
    with _LOCK:
        hit = _CACHE.get(index)
        if hit and (time.monotonic() - hit[0]) < _TTL:
            return hit[1]

        from jugaad_data.nse import NSELive

        data = NSELive().all_indices()
        rows = data.get("data", []) if isinstance(data, dict) else []
        row = next((r for r in rows if r.get("index") == index), None)
        if row is None:
            raise RuntimeError(f"Index '{index}' not present in NSE live feed")

        vix_row = next((r for r in rows if r.get("index") == "INDIA VIX"), None)

        quote = {
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
        }
        _CACHE[index] = (time.monotonic(), quote)
        return quote


def market_status() -> dict:
    """Whether the market is actually open — matters because a 'live' price
    outside session hours is just the last close wearing a live label."""
    from jugaad_data.nse import NSELive

    data = NSELive().market_status()
    markets = data.get("marketState", []) if isinstance(data, dict) else []
    cm = next((m for m in markets if m.get("market") == "Capital Market"), None)
    return {
        "market": cm.get("market") if cm else None,
        "status": cm.get("marketStatus") if cm else None,
        "trade_date": cm.get("tradeDate") if cm else None,
        "is_open": (cm.get("marketStatus", "").lower() == "open") if cm else False,
    }
