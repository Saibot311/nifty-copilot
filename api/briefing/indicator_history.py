"""What each indicator on the grid is, and what followed readings like today's.

  explain   what the indicator measures, why traders read it, how it moves
            with the market and what it means for someone buying options.
            Fixed words, the same every day.
  history   every session since 2015 put in a bucket by that day's closing
            reading (RSI 30-40, VIX 12-15, ...), and the session after it
            measured from its open: how far it went up, how far down, and
            whether it closed higher. Kept as a share of price, turned into
            points at today's price for every move size from 25 to 300, for
            the bucket today's reading is in and for every day alike.

A bucket "stands out" only when it differs from the other days well beyond
chance (|z| >= 3): eight indicators, a few buckets each, and twelve move
sizes are many comparisons, and some will look different by luck. A
description of what followed, not a signal: nothing here says to buy.
"""

from datetime import date

import numpy as np
import pandas as pd

from quant.indicators import adx, atr, ema, historical_volatility, rsi

TARGETS = tuple(range(25, 301, 25))
MIN_DAYS = 30
STANDS_OUT_Z = 3.0
SINCE = date(2015, 1, 1)

# (label, low, high): low <= reading < high
BUCKETS = {
    "rsi": [("below 30", -np.inf, 30), ("30–40", 30, 40), ("40–50", 40, 50), ("50–60", 50, 60),
            ("60–70", 60, 70), ("above 70", 70, np.inf)],
    "adx": [("under 20", -np.inf, 20), ("20–25", 20, 25), ("25–40", 25, 40), ("40 and over", 40, np.inf)],
    "atr": [("under 0.8× its 1-year median", -np.inf, 0.8), ("0.8–1× its 1-year median", 0.8, 1.0),
            ("1–1.25× its 1-year median", 1.0, 1.25), ("1.25× its 1-year median and over", 1.25, np.inf)],
    "range": [("under 0.75× ATR", -np.inf, 0.75), ("0.75–1× ATR", 0.75, 1.0), ("1–1.5× ATR", 1.0, 1.5),
              ("1.5× ATR and over", 1.5, np.inf)],
    "gap": [("down over 0.5%", -np.inf, -0.5), ("down 0.2–0.5%", -0.5, -0.2), ("flat (within 0.2%)", -0.2, 0.2 + 1e-12),
            ("up 0.2–0.5%", 0.2 + 1e-12, 0.5), ("up over 0.5%", 0.5, np.inf)],
    "vix": [("under 12", -np.inf, 12), ("12–15", 12, 15), ("15–20", 15, 20), ("20–25", 20, 25), ("25 and over", 25, np.inf)],
    "iv_vs_hv": [("30-day IV under 0.8× realised", -np.inf, 0.8), ("30-day IV 0.8–1× realised", 0.8, 1.0),
                 ("30-day IV 1–1.2× realised", 1.0, 1.2), ("30-day IV 1.2× realised and over", 1.2, np.inf)],
}
TREND = ("above both", "between them", "below both")

EXPLAIN = {
    "trend": {
        "what": "Two moving averages of NIFTY's daily closes. EMA 20 follows roughly the last month and EMA 50 the "
                "last quarter, each weighting recent days more.",
        "why": "They show the direction of the trend over weeks. Price above both with EMA 20 over EMA 50 is the "
               "textbook uptrend; below both with EMA 20 under EMA 50, the downtrend.",
        "reacts": "Price moves first and the averages follow, EMA 20 faster than EMA 50. A sharp rally can lift "
                  "price above EMA 20 in a day or two; EMA 20 crossing EMA 50 takes weeks. In a sideways market "
                  "price criss-crosses both and the picture flips often.",
        "buyer": "It describes direction over weeks, not the next hour, and says nothing about how far the next "
                 "session will move.",
    },
    "rsi": {
        "what": "The Relative Strength Index: the size of NIFTY's up-closes against its down-closes over 14 "
                "sessions, on a 0–100 scale. 50 means they balanced.",
        "why": "It measures momentum. Over 70 is called overbought and under 30 oversold: the moves have been "
               "one-sided, not that they must reverse.",
        "reacts": "Rises on strong up-days and falls on sharp drops, the latest days counting most. In a strong "
                  "trend it can stay above 70 or below 30 for weeks.",
        "buyer": "It shows which way recent days leaned, not how big the next move will be; the record below shows "
                 "what followed readings like this one.",
    },
    "adx": {
        "what": "The Average Directional Index: how strongly NIFTY has been trending over 14 sessions, whichever "
                "the direction, on a 0–100 scale.",
        "why": "It separates trending markets from choppy ones. 25 is the usual line for a trend; under 20, price "
               "has mostly gone sideways.",
        "reacts": "Rises while moves keep going one way, up or down, and falls when price chops back and forth. It "
                  "is slow, and it does not say which way the trend runs: the EMAs do.",
        "buyer": "A high reading means recent days moved consistently one way; it does not promise the next one will.",
    },
    "atr": {
        "what": "The Average True Range: NIFTY's typical daily range in points over 14 sessions, gaps from the "
                "previous close included.",
        "why": "The plainest measure of how much NIFTY moves in a day. Against its own 1-year median it shows "
               "whether the market is calmer or wilder than usual.",
        "reacts": "Grows after wide days and gaps and shrinks through quiet stretches. A shock lifts it quickly; it "
                  "settles back slowly.",
        "buyer": "A bought option needs movement. ATR is the yardstick for how much movement a normal day has "
                 "brought lately.",
    },
    "range": {
        "what": "Today's high minus today's low, in points, against ATR.",
        "why": "It shows whether today has already moved as much as a typical day.",
        "reacts": "It can only widen as the session goes on, and a news shock widens it at once. It is final at 15:30.",
        "buyer": "A range already past ATR means a normal day's movement has happened; a narrow one means it has "
                 "not. Neither says what comes next.",
    },
    "gap": {
        "what": "Today's opening price minus the previous session's close.",
        "why": "It shows how much overnight news, from global markets to GIFT Nifty and results, was priced in "
               "before trading began.",
        "reacts": "Set at 09:15 and fixed for the day. It follows what global indices and GIFT Nifty did overnight.",
        "buyer": "Option prices at the open already include the gap; the move you pay for is the one after it.",
    },
    "vix": {
        "what": "India VIX: NSE's measure of how much movement the NIFTY options market expects over the next 30 "
                "days, as an annualised percentage.",
        "why": "It is the market's price for uncertainty: the higher it is, the dearer options are.",
        "reacts": "It usually rises when NIFTY falls sharply and drifts lower in calm or rising markets. It climbs "
                  "before events such as elections and budgets and drops after them.",
        "buyer": "You pay for it. A higher VIX means a higher price for the same strike, and if VIX falls after you "
                 "buy, the option can lose value even when NIFTY does not move.",
    },
    "iv_vs_hv": {
        "what": "The implied volatility of the at-the-money option against the volatility NIFTY actually delivered "
                "over the last 20 sessions.",
        "why": "It compares what options charge for movement with how much movement there has been.",
        "reacts": "IV moves with option prices through the day; realised volatility changes once a day, with each "
                  "close. On an expiry day the expiring option's IV can read far too low or high, because so little "
                  "time is left.",
        "buyer": "IV above realised means options price in more movement than NIFTY has lately delivered; below, less.",
    },
}


def bucket(key: str, value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if key == "trend":
        return value if value in TREND else None
    for label, lo, hi in BUCKETS[key]:
        if lo <= value < hi:
            return label
    return None


def where(price: float, e20: float, e50: float) -> str:
    return "above both" if price > max(e20, e50) else "below both" if price < min(e20, e50) else "between them"


def readings(df: pd.DataFrame, vix: dict, iv30: dict) -> pd.DataFrame:
    """Each day's closing reading of every indicator, from that day and earlier only."""
    c = df["close"]
    e20, e50 = ema(c, 20), ema(c, 50)
    a = atr(df)
    hv = historical_volatility(c)
    days = [d.date() if hasattr(d, "date") else d for d in df.index]
    iv = pd.Series([iv30.get(d) for d in days], index=df.index, dtype=float) * 100
    return pd.DataFrame({
        "trend": [where(p, x, y) for p, x, y in zip(c, e20, e50)],
        "rsi": rsi(c),
        "adx": adx(df),
        "atr": a / a.rolling(250, min_periods=60).median(),
        "range": (df["high"] - df["low"]) / a,
        "gap": (df["open"] / c.shift(1) - 1) * 100,
        "vix": pd.Series([vix.get(d) for d in days], index=df.index, dtype=float),
        "iv_vs_hv": iv / hv,
    }, index=df.index)


def next_session(df: pd.DataFrame) -> pd.DataFrame:
    """The session after each day, from its open: % up to its high, % down to its low, closed higher."""
    nxt = df.shift(-1)
    return pd.DataFrame({"up_pct": (nxt["high"] / nxt["open"] - 1) * 100,
                         "down_pct": (1 - nxt["low"] / nxt["open"]) * 100,
                         "closed_up": (nxt["close"] > df["close"]).where(nxt["close"].notna())}, index=df.index)


def table(df: pd.DataFrame, vix: dict, iv30: dict) -> pd.DataFrame:
    r = readings(df, vix, iv30)
    out = pd.DataFrame({k: [bucket(k, v) for v in r[k]] for k in r.columns}, index=df.index)
    return out.join(next_session(df)).dropna(subset=["up_pct"])


def _side(rows: pd.DataFrame, price: float) -> dict:
    n = len(rows)
    up = rows["up_pct"].to_numpy(float) / 100 * price
    down = rows["down_pct"].to_numpy(float) / 100 * price
    either = np.maximum(up, down)

    def share(x, t):
        return round(float((x >= t - 1e-9).mean() * 100), 1) if n else None
    closed = rows["closed_up"].dropna()
    return {"n": n, "up": [share(up, t) for t in TARGETS], "down": [share(down, t) for t in TARGETS],
            "either": [share(either, t) for t in TARGETS],
            "median_either_pts": round(float(np.median(either)), 0) if n else None,
            "closed_up_pct": round(float(closed.astype(bool).mean() * 100), 1) if len(closed) else None}


def _compare(p1, n1, p2, n2) -> str:
    if p1 is None or p2 is None or n1 < MIN_DAYS or n2 < MIN_DAYS:
        return "few"
    a, b = p1 / 100, p2 / 100
    pool = (a * n1 + b * n2) / (n1 + n2)
    se = (pool * (1 - pool) * (1 / n1 + 1 / n2)) ** 0.5
    z = (a - b) / se if se else 0.0
    return "more" if z >= STANDS_OUT_Z else "less" if z <= -STANDS_OUT_Z else "like"


def odds(rows: pd.DataFrame, key: str, label: str, price: float) -> dict:
    """What followed days in `label` against every day, at `price`, for every move size;
    each size compared with the other days."""
    have = rows[rows[key].notna()]
    like, rest = have[have[key] == label], have[have[key] != label]
    mine, other = _side(like, price), _side(rest, price)
    return {"bucket": label, "like": mine, "all": _side(have, price),
            "vs_rest": {s: [_compare(p, mine["n"], q, other["n"]) for p, q in zip(mine[s], other[s])]
                        for s in ("up", "down", "either")},
            "closed_up_vs_rest": _compare(mine["closed_up_pct"], mine["n"], other["closed_up_pct"], other["n"])}


def load() -> tuple[pd.DataFrame, dict, dict]:
    """Daily NIFTY since 2015 (Kite's archive, NSE's report where it lacks a
    session), India VIX closes and the 30-day IV."""
    import sqlite3

    from backtest.course_strategies import API_DIR
    from briefing.day_forecast import fill_from_nse
    from market_data.bar_archive import ArchiveProvider
    today = date.today()
    daily = {date.fromisoformat(c.timestamp[:10]): {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
             for c in ArchiveProvider().get_ohlc("^NSEI", "1d", SINCE, today)}
    nse, vix, iv30 = {}, {}, {}
    try:
        conn = sqlite3.connect(f"file:{API_DIR / 'data' / 'nse_indices.db'}?mode=ro", uri=True)
        try:
            for name, d, o, h, lo, c in conn.execute(
                    "SELECT index_name, trade_date, open, high, low, close FROM index_daily "
                    "WHERE index_name IN ('Nifty 50', 'India VIX') AND trade_date >= ?", (SINCE.isoformat(),)):
                if name == "India VIX":
                    vix[date.fromisoformat(d)] = float(c)
                else:
                    nse[date.fromisoformat(d)] = {"open": o, "high": h, "low": lo, "close": c}
        finally:
            conn.close()
        daily, _ = fill_from_nse(daily, nse)
    except sqlite3.Error:
        pass
    try:
        conn = sqlite3.connect(f"file:{API_DIR / 'data' / 'iv.db'}?mode=ro", uri=True)
        try:
            iv30 = {date.fromisoformat(d): float(v) for d, v in conn.execute(
                "SELECT trade_date, iv_30d FROM iv_daily WHERE iv_30d > 0")}
        finally:
            conn.close()
    except sqlite3.Error:
        pass
    days = sorted(daily)
    df = pd.DataFrame([daily[d] for d in days], index=pd.DatetimeIndex([pd.Timestamp(d) for d in days])).astype(float)
    return df, vix, iv30


def history_table() -> dict:
    """Cached for an hour: the record changes once a day."""
    from cache import cached

    def build():
        df, vix, iv30 = load()
        t = table(df, vix, iv30)
        return {"rows": t, "since": str(df.index[0].date()), "through": str(t.index[-1].date()) if len(t) else None,
                "last_iv30": iv30[max(iv30)] * 100 if iv30 else None}
    return cached("indicator_history", ttl_seconds=3600, producer=build, background=True)
