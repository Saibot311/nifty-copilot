"""GIFT Nifty: NIFTY futures on NSE International Exchange (GIFT City),
trading about 21 hours a day while India's market is shut.

What it is for here: context. It shows how NIFTY futures are trading after
India's 15:30 close and before its next open. It is not a signal — an
option bought at the close cannot act on the evening's move before the next
session opens, and the archive holds one option price a day.

There is no free, official daily history of GIFT Nifty (NSE and BSE publish
theirs; NSE IX does not). So the nightly job snapshots it from today, and a
history accumulates from 2026-09-22 onward.
"""

from datetime import datetime

import requests

URL = "https://www.nseix.com/api/streamer-market-watch/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.nseix.com/", "Accept": "application/json"}


def _f(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(payload: dict, symbol: str = "NIFTY") -> dict | None:
    """The near-month index future for `symbol`: the nearest expiry that has
    traded today."""
    rows = []
    for block in payload.get("MBP_data_Market_Watch", []):
        for r in block.get("token_data", []):
            if r.get("INSTRUMENTTYPE") == "FUTIDX" and r.get("SYMBOL") == symbol:
                rows.append(r)
    traded = [r for r in rows if (r.get("VOLUME") or 0) and _f(r.get("LASTPRICE"))]
    if not traded:
        return None
    near = min(traded, key=lambda r: datetime.strptime(r["EXPIRYDATE"], "%d-%b-%Y"))
    last, prev = _f(near["LASTPRICE"]), _f(near.get("CLOSE"))
    return {
        "symbol": f"GIFT {symbol}",
        "expiry": datetime.strptime(near["EXPIRYDATE"], "%d-%b-%Y").date().isoformat(),
        "last": last,
        "previous_close": prev,
        "change_pct": round((last / prev - 1) * 100, 2) if last and prev else None,
        "open": _f(near.get("OPEN")), "high": _f(near.get("HIGH")), "low": _f(near.get("LOW")),
        "volume": near.get("VOLUME"),
        "last_trade_time": near.get("LTT"),
    }


def fetch(symbol: str = "NIFTY", timeout: int = 15) -> dict | None:
    resp = requests.get(URL, headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return parse(resp.json(), symbol)
