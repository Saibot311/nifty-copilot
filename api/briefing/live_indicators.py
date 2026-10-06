"""The indicator grid under the Today chart: readings that work, moving with
the market.

The old grid had two readings that never worked on an index (relative
volume "0.0x" and VWAP "Unavailable" — NIFTY has no traded volume on the
free feed) and computed the rest from yesterday's close all session. Here,
while NSE reports a session newer than the last daily candle, its
open/high/low/last become a provisional candle and every reading includes
it — the same way the live patterns are judged. Until 15:30 that candle is
the day so far, and the grid says so.

Every figure and every word is decided here (I2); the page only lays it out.
Descriptions, not calls: "RSI above 70" is what the number is, never what
to do about it.
"""

from datetime import datetime

import pandas as pd

from briefing.indicator_history import EXPLAIN, TARGETS, bucket, history_table, odds
from quant.indicators import adx, atr, ema, historical_volatility, rsi

MINUS = "−"
TILE_KEYS = ("trend", "rsi", "adx", "atr", "range", "gap", "vix", "iv_vs_hv")


def _frame() -> pd.DataFrame:
    """The daily series the Today chart draws — final candles only."""
    from cache import cached
    from quant.pipeline import daily_frame

    def build():
        df = daily_frame()
        return df[~df["provisional"].astype(bool)] if "provisional" in df.columns else df
    # Daily candles do not change inside a session; the live part is the quote.
    return cached("grid_frame:^NSEI", ttl_seconds=600, producer=build, stale_ok=True)


def _quote() -> dict | None:
    from market_data.live_quote import live_index_quote
    try:
        return live_index_quote()
    except Exception:
        return None


def _is_open() -> bool:
    from market_data.live_quote import market_status, open_by_clock
    try:
        return bool(market_status().get("is_open"))
    except Exception:
        return open_by_clock()


def _today():
    from market_data.kite_session import IST
    return datetime.now(IST).date()


def _chain_iv() -> dict:
    """ATM implied volatility of the nearest expiry that does not expire
    today, from the same cached chain the Options tab reads (one NSE request
    per two minutes at most). An option in its last hours has almost no time
    value, and its IV says nothing about the market: on expiry day, 6 Oct
    2026, it read 1.7% against 11.7% realised."""
    from cache import cached
    from options import chain_analytics
    from options.move_table import nearest_tradable
    try:
        c = cached("option_chain:NIFTY:near", ttl_seconds=120, producer=chain_analytics.live_chain_analytics, stale_ok=True)
        if datetime.strptime(c.get("expiry") or "", "%d-%b-%Y").date() <= _today():
            nxt = nearest_tradable(c.get("available_expiries") or [], _today())
            if nxt:
                c = cached(f"option_chain:NIFTY:{nxt}", ttl_seconds=120, stale_ok=True,
                           producer=lambda: chain_analytics.live_chain_analytics(expiry=nxt))
    except Exception:
        return {"iv": None, "as_of": None}
    ivs = [v for v in (c.get("atm_iv") or {}).values() if v]
    when = None
    try:
        when = datetime.strptime(c.get("as_of") or "", "%d-%b-%Y %H:%M:%S").isoformat(timespec="minutes")
    except ValueError:
        pass
    expiry = None
    try:
        expiry = f"{datetime.strptime(c.get('expiry') or '', '%d-%b-%Y'):%-d %b}"
    except ValueError:
        pass
    return {"iv": sum(ivs) / len(ivs) if ivs else None, "as_of": when, "expiry": expiry}


def _signed(x: float, fmt: str = ",.0f") -> str:
    s = format(abs(x), fmt)
    return f"+{s}" if x > 0 else f"{MINUS}{s}" if x < 0 else s


def _pts(x: float) -> str:
    return f"{x:,.0f}"


def _day(ts) -> str:
    return f"{pd.Timestamp(ts):%-d %b}"


def _session_candle(q: dict | None, last_date) -> tuple[pd.Timestamp, dict] | None:
    """NSE's session so far, when it is a session the daily file does not have yet."""
    if not q or not q.get("market_time"):
        return None
    try:
        day = pd.Timestamp(datetime.fromisoformat(q["market_time"]).date())
        o, h, lo, c = (float(q[k]) for k in ("open", "high", "low", "last"))
    except (TypeError, ValueError, KeyError):
        return None
    if day <= pd.Timestamp(last_date) or min(o, h, lo, c) <= 0 or not lo <= c <= h:
        return None  # pre-open zeros, or a session already in the file
    return day, {"open": o, "high": h, "low": lo, "close": c}


def live_indicators() -> dict:
    df = _frame()[["open", "high", "low", "close"]].astype(float)
    q = _quote()
    today = _session_candle(q, df.index[-1])
    open_now = _is_open() if today else False
    if today:
        day, candle = today
        df = pd.concat([df, pd.DataFrame([candle], index=[day])])
        as_of = q["market_time"]
        at = datetime.fromisoformat(as_of)
        basis = (f"Includes {_day(day)} so far · {at:%H:%M} IST · final at 15:30" if open_now
                 else f"As of the {_day(day)} close · NSE live feed")
    else:
        as_of = str(df.index[-1].date())
        basis = f"As of the {_day(df.index[-1])} close"

    close = df["close"]
    price = float(close.iloc[-1])
    e20, e50 = float(ema(close, 20).iloc[-1]), float(ema(close, 50).iloc[-1])
    r = rsi(close)
    a = adx(df)
    atr_s = atr(df)
    atr_v = float(atr_s.iloc[-1])
    atr_med = float(atr_s.tail(250).median())
    hv = float(historical_volatility(close).iloc[-1])
    bar, prev = df.iloc[-1], df.iloc[-2]
    session = _day(df.index[-1])
    earlier = "at the close before" if today else "a session earlier"

    tiles = []
    hist = _history()

    def tile(key, name, value, detail, state, when=as_of, now="", reading=None):
        tiles.append({"key": key, "name": name, "value": value, "detail": detail, "state": state,
                      "as_of": when, "explain": EXPLAIN[key], "now": now,
                      "history": _odds(hist, key, reading, price)})

    where = ("above both" if price > max(e20, e50) else "below both" if price < min(e20, e50)
             else "between them")
    tile("trend", "Price vs EMA 20 / 50", f"{_pts(price)} {where}",
         f"EMA20 {_pts(e20)} · EMA50 {_pts(e50)}",
         "EMA20 over EMA50" if e20 > e50 else "EMA20 under EMA50",
         now=(f"NIFTY is {where.replace('them', 'the two averages').replace('both', 'both averages')}, "
              f"{_signed((price / e20 - 1) * 100, '.1f')}% from EMA 20, and EMA 20 is "
              f"{'above' if e20 > e50 else 'below'} EMA 50: "
              + ("the textbook uptrend." if where == "above both" and e20 > e50 else
                 "the textbook downtrend." if where == "below both" and e20 < e50 else "a mixed picture.")),
         reading=where)

    rv, rp = float(r.iloc[-1]), float(r.iloc[-2])
    tile("rsi", "RSI (14)", f"{rv:.1f}", f"{rp:.1f} {earlier} · 30 and 70 are the usual bands",
         "above 70" if rv > 70 else "below 30" if rv < 30 else "between 30 and 70",
         now=(f"{rv:.1f}, {'up' if rv > rp else 'down' if rv < rp else 'unchanged'} from {rp:.1f}: "
              + ("down-closes have far outweighed up-closes over 14 sessions." if rv < 30 else
                 "down-closes have outweighed up-closes lately, not to an extreme." if rv < 50 else
                 "up-closes have outweighed down-closes lately, not to an extreme." if rv <= 70 else
                 "up-closes have far outweighed down-closes over 14 sessions.")),
         reading=rv)

    av, ap = float(a.iloc[-1]), float(a.iloc[-2])
    tile("adx", "ADX (14)", f"{av:.1f}", f"{ap:.1f} {earlier} · 25+ is the usual trending line",
         "trending" if av >= 25 else "not trending",
         now=(f"{av:.1f}, {'rising' if av > ap else 'falling' if av < ap else 'flat'} from {ap:.1f}: "
              + (f"NIFTY has moved consistently one way, {'up' if e20 > e50 else 'down'} by the EMAs." if av >= 25 else
                 "a weak trend at most." if av >= 20 else "mostly sideways.")),
         reading=av)

    tile("atr", "ATR (14)", f"{_pts(atr_v)} pts",
         f"{atr_v / price * 100:.2f}% of price · 1-year median {_pts(atr_med)} pts",
         "above its 1-year median" if atr_v > atr_med else "below its 1-year median",
         now=(f"A typical day lately covers about {_pts(atr_v)} pts, {atr_v / atr_med:.2f}× the 1-year median: "
              f"{'busier' if atr_v > atr_med else 'calmer'} than usual."),
         reading=atr_v / atr_med)

    rng = float(bar["high"] - bar["low"])
    tile("range", f"Range, {session}" + (" so far" if open_now else ""), f"{_pts(rng)} pts",
         f"{rng / atr_v * 100:.0f}% of ATR · high {_pts(bar['high'])} · low {_pts(bar['low'])}",
         "wider than ATR" if rng > atr_v else "inside ATR",
         now=(f"{session} has covered {_pts(rng)} pts{' so far' if open_now else ''}, {rng / atr_v * 100:.0f}% of a "
              f"typical day's range."),
         reading=rng / atr_v)

    gap = float(bar["open"] - prev["close"])
    tile("gap", f"Opening gap, {session}", f"{_signed(gap)} pts",
         f"{_signed(gap / float(prev['close']) * 100, '.2f')}% · open {_pts(bar['open'])} "
         f"against the {_day(df.index[-2])} close {_pts(prev['close'])}",
         "gap up" if gap > 0 else "gap down" if gap < 0 else "flat open",
         now=(f"NIFTY opened {_pts(abs(gap))} pts {'above' if gap > 0 else 'below'} the previous close "
              f"({_signed(gap / float(prev['close']) * 100, '.2f')}%)." if gap else "NIFTY opened at the previous close."),
         reading=gap / float(prev["close"]) * 100)

    vix = (q or {}).get("india_vix")
    if vix is not None:
        chg = (q or {}).get("india_vix_change_pct")
        chg = float(chg) if chg is not None else None
        tile("vix", "India VIX", f"{float(vix):.2f}",
             f"{_signed(chg, '.2f')}% from the previous close · NSE" if chg is not None else "NSE",
             "" if chg is None else "up on the day" if chg > 0 else "down on the day" if chg < 0 else "unchanged",
             when=q.get("market_time") or q.get("fetched_at"),
             now=(f"{float(vix):.2f} prices in a move of about ±{float(vix) / 252 ** 0.5:.2f}% "
                  f"(±{_pts(price * float(vix) / 100 / 252 ** 0.5)} pts) on a typical day: one standard deviation, "
                  f"the annual figure divided by the square root of 252 sessions."),
             reading=float(vix))
    else:
        tile("vix", "India VIX", "not available", "NSE's feed did not answer", "", when=as_of)

    iv = _chain_iv()
    if iv.get("iv"):
        ratio = iv["iv"] / hv
        exp = f" · expiry {iv['expiry']}" if iv.get("expiry") else ""
        expiring = bool(iv.get("expiry")) and iv["expiry"] == f"{pd.Timestamp(df.index[-1]):%-d %b}"
        tile("iv_vs_hv", "ATM IV vs 20-day realised", f"{iv['iv']:.1f}% vs {hv:.1f}%",
             f"IV is {ratio:.2f}× what NIFTY actually moved{exp}",
             "IV above realised" if ratio > 1 else "IV below realised", when=iv.get("as_of") or as_of,
             now=(f"Options on the nearest expiry price in {ratio:.2f}× the movement NIFTY delivered over 20 sessions."
                  + (" That expiry is today, so its IV is not a fair reading." if expiring else "")),
             reading=_iv30_ratio(hist, hv))
    else:
        tile("iv_vs_hv", "ATM IV vs 20-day realised", "not available",
             f"option chain did not answer · realised {hv:.1f}%", "", when=as_of, reading=_iv30_ratio(hist, hv))

    return {"live": open_now, "basis": basis, "as_of": as_of, "session": str(df.index[-1].date()),
            "tiles": tiles, "targets": list(TARGETS),
            "history_note": (f"Every session since {hist['since'][:4]} put in a bucket by its closing reading, and the "
                             f"session after it measured from its open, in points at today's price. Readings in a live "
                             f"session are provisional; the record's are closing ones. A bucket stands out only when "
                             f"it differs from the other days well beyond chance. What followed, not a forecast."
                             if hist else "The record of what followed each reading is not available.")}


def _history() -> dict | None:
    try:
        return history_table()
    except Exception:
        return None


def _odds(hist: dict | None, key: str, reading, price: float) -> dict | None:
    label = bucket(key, reading)
    if not hist or label is None:
        return None
    return odds(hist["rows"], key, label, price)


def _iv30_ratio(hist: dict | None, hv: float) -> float | None:
    """The record buckets IV by the 30-day figure (an expiring option's IV is
    no guide), so today's bucket uses the latest 30-day IV too."""
    return hist["last_iv30"] / hv if hist and hist.get("last_iv30") and hv else None
