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

from quant.indicators import adx, atr, ema, historical_volatility, rsi

MINUS = "−"


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


def _chain_iv() -> dict:
    """ATM implied volatility of the nearest expiry, from the same cached
    chain the Options tab reads (one NSE request per two minutes at most)."""
    from cache import cached
    from options.chain_analytics import live_chain_analytics
    try:
        c = cached("option_chain:NIFTY:near", ttl_seconds=120, producer=live_chain_analytics, stale_ok=True)
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
    atr_v = float(atr(df).iloc[-1])
    hv = float(historical_volatility(close).iloc[-1])
    bar, prev = df.iloc[-1], df.iloc[-2]
    session = _day(df.index[-1])
    earlier = "at the close before" if today else "a session earlier"

    tiles = []

    def tile(key, name, value, detail, state, when=as_of):
        tiles.append({"key": key, "name": name, "value": value, "detail": detail, "state": state,
                      "as_of": when})

    where = ("above both" if price > max(e20, e50) else "below both" if price < min(e20, e50)
             else "between them")
    tile("trend", "Price vs EMA 20 / 50", f"{_pts(price)} {where}",
         f"EMA20 {_pts(e20)} · EMA50 {_pts(e50)}",
         "EMA20 over EMA50" if e20 > e50 else "EMA20 under EMA50")

    rv, rp = float(r.iloc[-1]), float(r.iloc[-2])
    tile("rsi", "RSI (14)", f"{rv:.1f}", f"{rp:.1f} {earlier} · 30 and 70 are the usual bands",
         "above 70" if rv > 70 else "below 30" if rv < 30 else "between 30 and 70")

    av, ap = float(a.iloc[-1]), float(a.iloc[-2])
    tile("adx", "ADX (14)", f"{av:.1f}", f"{ap:.1f} {earlier} · 25+ is the usual trending line",
         "trending" if av >= 25 else "not trending")

    tile("atr", "ATR (14)", f"{_pts(atr_v)} pts", f"{atr_v / price * 100:.2f}% of price · a typical day's range",
         "")

    rng = float(bar["high"] - bar["low"])
    tile("range", f"Range, {session}" + (" so far" if open_now else ""), f"{_pts(rng)} pts",
         f"{rng / atr_v * 100:.0f}% of ATR · high {_pts(bar['high'])} · low {_pts(bar['low'])}",
         "wider than ATR" if rng > atr_v else "inside ATR")

    gap = float(bar["open"] - prev["close"])
    tile("gap", f"Opening gap, {session}", f"{_signed(gap)} pts",
         f"{_signed(gap / float(prev['close']) * 100, '.2f')}% · open {_pts(bar['open'])} "
         f"against the {_day(df.index[-2])} close {_pts(prev['close'])}",
         "gap up" if gap > 0 else "gap down" if gap < 0 else "flat open")

    vix = (q or {}).get("india_vix")
    if vix is not None:
        chg = (q or {}).get("india_vix_change_pct")
        tile("vix", "India VIX", f"{float(vix):.2f}",
             (f"{_signed(float(chg), '.2f')}% on the day · NSE" if chg is not None else "NSE"), "",
             when=q.get("market_time") or q.get("fetched_at"))
    else:
        tile("vix", "India VIX", "not available", "NSE's feed did not answer", "", when=as_of)

    iv = _chain_iv()
    if iv.get("iv"):
        ratio = iv["iv"] / hv
        exp = f" · expiry {iv['expiry']}" if iv.get("expiry") else ""
        tile("iv_vs_hv", "ATM IV vs 20-day realised", f"{iv['iv']:.1f}% vs {hv:.1f}%",
             f"IV is {ratio:.2f}× what NIFTY actually moved{exp}",
             "IV above realised" if ratio > 1 else "IV below realised", when=iv.get("as_of") or as_of)
    else:
        tile("iv_vs_hv", "ATM IV vs 20-day realised", "not available",
             f"option chain did not answer · realised {hv:.1f}%", "", when=as_of)

    return {"live": open_now, "basis": basis, "as_of": as_of, "session": str(df.index[-1].date()),
            "tiles": tiles}
