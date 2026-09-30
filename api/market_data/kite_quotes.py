"""Live prices from Kite: the index, and the option contracts the paper book
is holding.

Two reasons this exists beside live_quote.py (NSE's public feed): the NSE
feed carries indices but not a specific option contract, and a logged-in
Kite session gives both in one call with a published rate limit.

Kite quotes are keyed by instrument token, so the NFO instrument list is
fetched once a day and cached — it is ~100k rows and changes daily at best.
Everything degrades to None rather than a guess: a paper position with no
live price keeps its last closing mark, labelled as such.
"""

import threading
import time
from datetime import date, datetime

from .kite_session import IST, KiteNotLoggedIn, authenticated_client

_LOCK = threading.Lock()
_INSTRUMENTS: dict = {"day": None, "by_key": {}}
_QUOTE_CACHE: dict = {"at": 0.0, "data": {}}
QUOTE_TTL = 1.0  # Kite allows one quote call a second; one process, one cache
_SLOT_LOCK = threading.Lock()
_LAST_CALL = {"at": 0.0}


def _quote_slot() -> None:
    """Wait for this process's turn at Kite's quote APIs (ltp, quote): one
    call a second between them. The tick and the indices board both call
    from background threads and would otherwise collide into a refusal."""
    with _SLOT_LOCK:
        wait = QUOTE_TTL - (time.monotonic() - _LAST_CALL["at"])
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL["at"] = time.monotonic()


def index_quote(key: str) -> dict:
    """An index's last price, open, high, low and previous close from Kite,
    e.g. key "BSE:SENSEX". `as_of` is the exchange's time for the figure; the
    exchange keeps sending the closing value after 15:30, so later stamps
    are shown as the close they repeat."""
    _quote_slot()
    q = authenticated_client().quote([key])[key]
    o = q["ohlc"]
    ts = q.get("timestamp")
    if isinstance(ts, datetime):
        ts = ts.replace(tzinfo=IST) if ts.tzinfo is None else ts.astimezone(IST)
        close = ts.replace(hour=15, minute=30, second=0, microsecond=0)
        as_of = min(ts, close).isoformat(timespec="minutes")
    else:
        as_of = None
    return {"last": float(q["last_price"]), "previous_close": float(o["close"]), "open": float(o["open"]),
            "high": float(o["high"]), "low": float(o["low"]), "as_of": as_of, "source": "Kite"}


def _instrument_map() -> dict[tuple, int]:
    """(underlying, expiry, strike, CE/PE) -> instrument token, refreshed daily."""
    today = date.today().isoformat()
    with _LOCK:
        if _INSTRUMENTS["day"] == today:
            return _INSTRUMENTS["by_key"]
    rows = authenticated_client().instruments("NFO")
    by_key = {}
    for r in rows:
        if r.get("segment") != "NFO-OPT" or r.get("instrument_type") not in ("CE", "PE"):
            continue
        expiry = r.get("expiry")
        by_key[(r.get("name"), expiry.isoformat() if hasattr(expiry, "isoformat") else str(expiry),
                float(r.get("strike") or 0), r["instrument_type"])] = int(r["instrument_token"])
    with _LOCK:
        _INSTRUMENTS.update(day=today, by_key=by_key)
    return by_key


def option_tokens(contracts: list[dict]) -> dict[int, int]:
    """{paper trade id: instrument token} for the contracts we can resolve."""
    try:
        by_key = _instrument_map()
    except (KiteNotLoggedIn, Exception):
        return {}
    out = {}
    for c in contracts:
        token = by_key.get((c["underlying"], c["expiry"], float(c["strike"]), c["option_type"]))
        if token:
            out[c["id"]] = token
    return out


def last_prices(tokens: list[int], index: str = "NSE:NIFTY 50") -> dict:
    """One call: the index plus every requested contract. Cached for a second
    so several dashboard tabs cannot multiply into a rate-limit breach."""
    now = time.monotonic()
    with _LOCK:
        if now - _QUOTE_CACHE["at"] < QUOTE_TTL and set(tokens) <= set(_QUOTE_CACHE["data"].get("tokens", [])):
            return _QUOTE_CACHE["data"]
    kite = authenticated_client()
    wanted = [index, *[str(t) for t in tokens]]
    _quote_slot()
    raw = kite.ltp(wanted)
    data = {
        "index": (raw.get(index) or {}).get("last_price"),
        "by_token": {int(k): v.get("last_price") for k, v in raw.items() if k.isdigit() and v},
        "tokens": list(tokens),
        # Just the source: whether it is live is the market status's to say.
        "source": "Kite",
        # When this price was fetched, so the dashboard can say how old it is.
        "quote_at": datetime.now(IST).isoformat(timespec="seconds"),
    }
    with _LOCK:
        _QUOTE_CACHE.update(at=now, data=data)
    return data
