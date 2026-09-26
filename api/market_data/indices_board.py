"""The Market tab's indices board: NIFTY 50 and Bank Nifty from NSE's live
feed, Sensex from Yahoo's one-minute bars (BSE refuses outside requests),
and GIFT Nifty from NSE IX — each with its own time.

The commentary is written here from those numbers (I2): which way each
moved, which is leading, where each sits in its day's range, and what GIFT
Nifty is doing while India is shut. It describes; it does not suggest.
"""

from datetime import datetime, timedelta

from .live_quote import IST

MINUS = "−"
# A row this far behind the freshest one, in a session, is said to be behind.
BEHIND_S = 300
# Two moves closer than this (percentage points) are "moving with" each other.
WITH_PP = 0.15

# GIFT Nifty with no trade for this long has stopped for the night or the weekend.
GIFT_QUIET_S = 900

NAMES = {"nifty": "NIFTY", "banknifty": "Bank Nifty", "sensex": "Sensex", "gift": "GIFT Nifty"}


def _pct(x: float) -> str:
    return f"+{x:.2f}%" if x > 0 else f"{MINUS}{abs(x):.2f}%" if x < 0 else "0.00%"


def _pts(x: float) -> str:
    s = f"{abs(x):,.2f}"
    return f"+{s}" if x > 0 else f"{MINUS}{s}" if x < 0 else s


def _hm(iso: str | None) -> str:
    return iso[11:16] if iso and len(iso) >= 16 else "time unknown"


def _row(key: str, q: dict, as_of: str | None, source: str) -> dict:
    last, prev = float(q["last"]), float(q["previous_close"])
    hi, lo = q.get("high"), q.get("low")
    pos = None
    if hi is not None and lo is not None and float(hi) > float(lo):
        pos = round((last - float(lo)) / (float(hi) - float(lo)) * 100)
    change = last - prev
    return {"key": key, "name": NAMES[key], "last": round(last, 2), "previous_close": round(prev, 2),
            "change": round(change, 2), "change_pct": round(change / prev * 100, 2),
            "change_text": f"{_pts(change)} ({_pct(change / prev * 100)})",
            "open": q.get("open"), "high": hi, "low": lo, "day_position": pos,
            "as_of": as_of, "source": source, "behind": False}


def _gift_time(stamp: str | None) -> str | None:
    try:
        return datetime.strptime(stamp or "", "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST).isoformat()
    except ValueError:
        return None


def board(nse: dict | None, sensex: dict | None, gift: dict | None, *, market_open: bool,
          now: datetime | None = None) -> dict:
    rows, missing = [], []
    nse_rows = (nse or {}).get("rows", {})
    for key, name in (("nifty", "NIFTY 50"), ("banknifty", "NIFTY BANK")):
        q = nse_rows.get(name)
        if q and q.get("last") and q.get("previous_close"):
            rows.append(_row(key, q, nse.get("market_time"), "NSE"))
        else:
            missing.append(NAMES[key])
    if sensex and sensex.get("last") and sensex.get("previous_close"):
        rows.append(_row("sensex", sensex, sensex.get("as_of"), "Yahoo, 1-min bars"))
    else:
        missing.append("Sensex")
    if gift and gift.get("last") and gift.get("previous_close"):
        rows.append(_row("gift", gift, _gift_time(gift.get("last_trade_time")), "NSE IX, near-month future"))
    else:
        missing.append("GIFT Nifty")

    # In a session, a spot index minutes behind the others is a feed lagging,
    # and the board says so rather than line it up as if it were current.
    if market_open:
        times = {r["key"]: datetime.fromisoformat(r["as_of"]) for r in rows if r["as_of"]}
        if times:
            newest = max(times.values())
            for r in rows:
                t = times.get(r["key"])
                if r["key"] != "gift" and t and (newest - t).total_seconds() > BEHIND_S:
                    r["behind"] = True

    return {"market_open": market_open, "rows": rows,
            "commentary": commentary(rows, missing, market_open=market_open, now=now or datetime.now(IST))}


def commentary(rows: list[dict], missing: list[str], *, market_open: bool, now: datetime) -> list[str]:
    by = {r["key"]: r for r in rows}
    spot = [by[k] for k in ("nifty", "banknifty", "sensex") if k in by]
    lines: list[str] = []
    when = "on the day" if market_open else "at the close"

    if len(spot) >= 2:
        ups = [r for r in spot if r["change_pct"] > 0]
        downs = [r for r in spot if r["change_pct"] < 0]
        everyone = "All three" if len(spot) == 3 else "Both"
        if len(ups) == len(spot):
            lines.append(f"{everyone} indices are up {when}.")
        elif len(downs) == len(spot):
            lines.append(f"{everyone} indices are down {when}.")
        else:
            parts = [f"{r['name']} {'up' if r['change_pct'] > 0 else 'down' if r['change_pct'] < 0 else 'flat'}"
                     for r in spot]
            lines.append(f"Mixed {when}: " + ", ".join(parts) + ".")

    n = by.get("nifty")
    if n:
        for other in (by.get("banknifty"), by.get("sensex")):
            if not other:
                continue
            gap = other["change_pct"] - n["change_pct"]
            pair = f"{_pct(other['change_pct'])} against {_pct(n['change_pct'])}"
            if abs(gap) < WITH_PP:
                lines.append(f"{other['name']} is moving with NIFTY: {pair}.")
            else:
                lines.append(f"{other['name']} is {'leading' if gap > 0 else 'lagging'} NIFTY: {pair}.")

    for r in spot[:2]:
        p = r["day_position"]
        if p is None:
            continue
        where = "near the day's high" if p >= 80 else "near the day's low" if p <= 20 else "mid-range"
        lines.append(f"{r['name']} is {where}: {p}% of the way from its low "
                     f"{r['low']:,.0f} to its high {r['high']:,.0f}.")

    g = by.get("gift")
    if g:
        at = _hm(g["as_of"])
        traded = datetime.fromisoformat(g["as_of"]) if g["as_of"] else None
        if traded and (now - traded).total_seconds() > GIFT_QUIET_S:
            lines.append(f"GIFT Nifty last traded at {at} IST on {traded:%-d %b}: {_pct(g['change_pct'])} on its "
                         f"own previous close.")
        elif market_open:
            lines.append(f"GIFT Nifty is {_pct(g['change_pct'])} on its own previous close, last trade {at} IST.")
        else:
            lines.append(f"GIFT Nifty is trading while India is shut: {_pct(g['change_pct'])} on its own previous "
                         f"close, last trade {at} IST. Context for the evening, not a forecast of the open.")

    for r in rows:
        if r["behind"]:
            lines.append(f"{r['name']} was last updated at {_hm(r['as_of'])} IST, behind the others ({r['source']}).")
    for name in missing:
        lines.append(f"{name} is not available right now: its feed did not answer.")
    return lines


def _sensex() -> dict | None:
    import yfinance as yf

    from .yfinance_provider import _session
    t = yf.Ticker("^BSESN", session=_session())
    bars = t.history(period="1d", interval="1m", actions=False)
    daily = t.history(period="7d", interval="1d", actions=False)
    if bars.empty or len(daily) < 2:
        return None
    day = bars.index[-1].date()
    prev_rows = daily[[d.date() < day for d in daily.index]]
    if prev_rows.empty:
        return None
    last_bar = bars.index[-1].tz_convert(IST)
    return {"last": float(bars["Close"].iloc[-1]), "previous_close": float(prev_rows["Close"].iloc[-1]),
            "open": float(bars["Open"].iloc[0]), "high": float(bars["High"].max()), "low": float(bars["Low"].min()),
            # A one-minute bar stamped 15:29 closed at 15:30.
            "as_of": (last_bar.replace(second=0) + timedelta(minutes=1)).isoformat(timespec="minutes")}


def fetch_board() -> dict:
    from cache import cached

    from .gift_nifty import fetch as fetch_gift
    from .live_quote import live_index_quote, market_status, open_by_clock

    nse = None
    try:
        q = live_index_quote()
        nse = {"market_time": q.get("market_time"), "rows": q.get("rows") or {}}
    except Exception:
        pass
    try:
        sensex = cached("sensex_live", ttl_seconds=30, producer=_sensex, stale_ok=True)
    except Exception:
        sensex = None
    try:
        gift = cached("gift_nifty", ttl_seconds=60, producer=fetch_gift, stale_ok=True)
    except Exception:
        gift = None
    try:
        is_open = bool(cached("market_status", ttl_seconds=60, producer=market_status, stale_ok=True).get("is_open"))
    except Exception:
        is_open = open_by_clock()
    out = board(nse, sensex, gift, market_open=is_open)
    out["as_of"] = datetime.now(IST).isoformat(timespec="seconds")
    return out
