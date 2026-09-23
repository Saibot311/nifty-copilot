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
from datetime import date

from .kite_session import KiteNotLoggedIn, authenticated_client

_LOCK = threading.Lock()
_INSTRUMENTS: dict = {"day": None, "by_key": {}}
_QUOTE_CACHE: dict = {"at": 0.0, "data": {}}
QUOTE_TTL = 1.0  # Kite allows one quote call a second; one process, one cache


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
    raw = kite.ltp(wanted)
    data = {
        "index": (raw.get(index) or {}).get("last_price"),
        "by_token": {int(k): v.get("last_price") for k, v in raw.items() if k.isdigit() and v},
        "tokens": list(tokens),
        "source": "Kite (live)",
    }
    with _LOCK:
        _QUOTE_CACHE.update(at=now, data=data)
    return data
