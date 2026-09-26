"""The Today chart: where NIFTY stands, and what close would change the call.

It used to be 110 generic candles with two moving averages — what any
charting site shows better, and nothing to do with the tab's question. It now
draws the decision in front of the reader:

  * 4-hour candles (NSE's split: 09:15-13:15 and 13:15-15:30) built from the
    archived 15-minute bars, with EMA20/EMA50 of those 4-hour closes. These
    are not the indicator grid's EMAs, which are daily, and the chart says so;
  * the previous session's high and low, which the breakout and breakdown
    rules are judged against at the next close;
  * the bands a close would have to land in for each pattern to form (from
    pattern_proximity), in a "next close" column beside the candles;
  * the days a rule was actually met, marked on that day's closing block —
    the rules are decided on the daily close, whatever the candle size;
  * during a session, the block still forming, following the live price —
    provisional.

Everything is computed here (I2); the browser only places it. None of it is
a signal: every pattern it shows was rejected on 2024-26 option data, and
the call on the Today tab stays NO TRADE unless one clears the evidence bar.
"""

from datetime import date, datetime, time, timedelta

import pandas as pd

from backtest.strategies import STRATEGY_REGISTRY
from market_data.kite_session import IST
from quant.indicators import ema

# NSE's 4-hour split, as the charting sites draw it: the morning block, then
# the afternoon one that ends at the 15:30 close.
BLOCK_STARTS = (time(9, 15), time(13, 15))
SESSION_END = time(15, 30)
# Days of 15-minute bars read: enough 4-hour closes for the EMA50 to settle.
HISTORY_DAYS = 400
# Sessions of 15-minute candles sent to the page: 25 a session, so 250.
M15_SESSIONS = 10
M15 = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(IST)


def _bars15() -> pd.DataFrame:
    """NIFTY's 15-minute bars: the local archive (Kite, topped up nightly),
    then Yahoo's for any day after the archive's last — the evening before
    the nightly job, and the session in progress."""
    from market_data.bar_archive import ArchiveProvider
    from market_data.yfinance_provider import YFinanceProvider

    def frame(candles):
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close"])
        idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
        idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
        return pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                             "low": [c.low for c in candles], "close": [c.close for c in candles]}, index=idx)

    today = date.today()
    archived = frame(ArchiveProvider().get_ohlc("^NSEI", "15m", today - timedelta(days=HISTORY_DAYS), today))
    try:
        recent = frame(YFinanceProvider().get_ohlc("^NSEI", "15m", today - timedelta(days=7), today))
    except Exception:
        recent = archived.iloc[:0]
    if not archived.empty:
        recent = recent[recent.index.normalize() > archived.index[-1].normalize()]
    return pd.concat([archived, recent]).sort_index()


def four_hour(bars15: pd.DataFrame) -> pd.DataFrame:
    """15-minute bars folded into NSE's two 4-hour blocks a day, indexed by
    each block's start. `bars` counts the 15-minute bars in each block."""
    idx = bars15.index.tz_convert(IST) if bars15.index.tz is not None else bars15.index
    afternoon = [t >= BLOCK_STARTS[1] for t in idx.time]
    starts = pd.DatetimeIndex([pd.Timestamp.combine(d, BLOCK_STARTS[int(a)]) for d, a in zip(idx.date, afternoon)])
    g = bars15.assign(block=starts.tz_localize(IST)).groupby("block")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "bars": g["close"].size()})
    out.index.name = None
    return out


def _block_over(start: pd.Timestamp, now: datetime) -> bool:
    end = (pd.Timestamp.combine(start.date(), SESSION_END) if start.time() == BLOCK_STARTS[1]
           else pd.Timestamp.combine(start.date(), BLOCK_STARTS[1])).tz_localize(IST)
    return now >= end.to_pydatetime()


def _grid_frame():
    """The indicator grid's own series, so the chart and the grid agree."""
    from quant.pipeline import daily_frame
    df = daily_frame()
    return df[~df["provisional"].astype(bool)] if "provisional" in df.columns else df


def _daily():
    """The longer history the pattern rules are run on."""
    from backtest.strategies import load_daily_data
    df, regime = load_daily_data("^NSEI", 1400)
    if "provisional" in df.columns:
        keep = ~df["provisional"].astype(bool)
        df, regime = df[keep], regime[keep]
    return df, regime


def _proximity() -> dict:
    from backtest.pattern_proximity import pattern_proximity
    from cache import cached
    return cached("proximity:^NSEI", ttl_seconds=1800, producer=lambda: pattern_proximity("^NSEI"))


def _live_candle() -> dict | None:
    """Today's candle from completed 15-minute bars, while the market is open."""
    from backtest.live_patterns import live_patterns
    from cache import cached
    live = cached("live_patterns", ttl_seconds=60, producer=live_patterns)
    c = live.get("candle")
    if not c:
        return None
    # Provisional until 15:30; after it, final but not yet in the daily file.
    return {"open": c.get("open"), "high": c.get("high"), "low": c.get("low"), "close": c.get("close"),
            "as_of": live.get("as_of"), "basis": live.get("basis"), "provisional": live.get("provisional", True)}


def _first_day(complete: pd.DataFrame, sessions: int) -> pd.Timestamp:
    days = complete.index.normalize().unique()
    return days[-sessions] if len(days) >= sessions else days[0]


def _forming_block(open_blocks: pd.DataFrame, day: dict, now: datetime) -> dict | None:
    """The block in progress: its 15-minute bars so far, carried to the live
    price (a 15-minute bar only exists once it has closed). Outside the
    session nothing is forming: after 15:30 the day's blocks are candles."""
    if not BLOCK_STARTS[0] <= now.time() < SESSION_END:
        return None
    today = [ts for ts in open_blocks.index if ts.date() == now.date()]
    start = (today[-1] if today else
             pd.Timestamp.combine(now.date(), BLOCK_STARTS[int(now.time() >= BLOCK_STARTS[1])]).tz_localize(IST))
    price = float(day["close"])
    if today:
        b = open_blocks.loc[start]
        o, h, lo = float(b["open"]), max(float(b["high"]), price), min(float(b["low"]), price)
    else:
        o = h = lo = price
    return {"t": f"{start:%Y-%m-%dT%H:%M}", "date": str(start.date()), "open": round(o, 2), "high": round(h, 2),
            "low": round(lo, 2), "close": round(price, 2), "as_of": day.get("as_of"), "basis": day.get("basis"),
            "provisional": True}


def _live_candle_today(grid) -> dict | None:
    day = _live_candle()
    if day and (day.get("as_of") or "")[:10] <= str(grid.index[-1].date()):
        return None
    return day


def _fifteen_minute(bars15: pd.DataFrame, day: dict | None, now: datetime) -> tuple[list[dict], dict | None]:
    """The 15-minute view: the last M15_SESSIONS sessions of closed bars, with
    EMAs of 15-minute closes over the whole history, and in a session the bar
    still forming, carried to the live price."""
    if bars15.empty:
        return [], None
    e20, e50 = ema(bars15["close"], 20), ema(bars15["close"], 50)
    closed = bars15[[ts + M15 <= pd.Timestamp(now) for ts in bars15.index]]
    chg = closed["close"].pct_change() * 100
    days = closed.index.normalize().unique()
    tail = closed[closed.index.normalize() >= days[-min(M15_SESSIONS, len(days))]]
    last_slot = (pd.Timestamp.combine(date(2000, 1, 1), SESSION_END) - M15).time()
    rows = [{"t": f"{ts:%Y-%m-%dT%H:%M}", "date": str(ts.date()), "day_close": ts.time() == last_slot,
             "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
             "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
             "ema20": round(float(e20.loc[ts]), 2), "ema50": round(float(e50.loc[ts]), 2),
             "change_pct": None if pd.isna(chg.loc[ts]) else round(float(chg.loc[ts]), 2)}
            for ts, r in tail.iterrows()]

    live = None
    if day and day.get("close") and BLOCK_STARTS[0] <= now.time() < SESSION_END:
        open_at = pd.Timestamp.combine(now.date(), BLOCK_STARTS[0]).tz_localize(IST)
        slot = open_at + M15 * int((pd.Timestamp(now) - open_at) / M15)
        price = float(day["close"])
        if slot in bars15.index:
            b = bars15.loc[slot]
            o, h, lo = float(b["open"]), max(float(b["high"]), price), min(float(b["low"]), price)
        else:
            o = h = lo = price
        live = {"t": f"{slot:%Y-%m-%dT%H:%M}", "date": str(slot.date()), "open": round(o, 2), "high": round(h, 2),
                "low": round(lo, 2), "close": round(price, 2), "as_of": day.get("as_of"), "provisional": True,
                "change_pct": round((price / rows[-1]["close"] - 1) * 100, 2) if rows else None}
    return rows, live


# Test hook: strategies to treat as in play besides those with a zone today.
IN_PLAY_EXTRA: set[str] = set()


def _side(option_type: str | None) -> str:
    return "call" if option_type == "CE" else "put"


def today_chart(sessions: int = 60) -> dict:
    """The last `sessions` days as 4-hour candles (two a day)."""
    now = _now()
    grid = _grid_frame()
    bars15 = _bars15()
    h4 = four_hour(bars15)
    e20, e50 = ema(h4["close"], 20), ema(h4["close"], 50)

    # A block still in progress is not a candle yet: it is drawn as the
    # provisional one, following the live price.
    done = pd.Series([_block_over(ts, now) for ts in h4.index], index=h4.index, dtype=bool)
    complete = h4[done]
    tail = complete[complete.index.normalize() >= _first_day(complete, sessions)]
    chg = complete["close"].pct_change() * 100
    candles = [{"t": f"{ts:%Y-%m-%dT%H:%M}", "date": str(ts.date()), "day_close": ts.time() == BLOCK_STARTS[1],
                "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
                "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
                "ema20": round(float(e20.loc[ts]), 2), "ema50": round(float(e50.loc[ts]), 2),
                "change_pct": None if pd.isna(chg.loc[ts]) else round(float(chg.loc[ts]), 2)}
               for ts, r in tail.iterrows()]

    m15, live_m15 = _fifteen_minute(bars15, _live_candle_today(grid), now)

    # The 1D view: the indicator grid's own daily series and EMAs.
    d20, d50 = ema(grid["close"], 20), ema(grid["close"], 50)
    dchg = grid["close"].pct_change() * 100
    daily = [{"t": str(ts.date()), "date": str(ts.date()), "day_close": True,
              "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
              "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
              "ema20": round(float(d20.loc[ts]), 2), "ema50": round(float(d50.loc[ts]), 2),
              "change_pct": None if pd.isna(dchg.loc[ts]) else round(float(dchg.loc[ts]), 2)}
             for ts, r in grid.tail(sessions).iterrows()]

    last = grid.iloc[-1]
    day_live = _live_candle()
    if day_live and (day_live.get("as_of") or "")[:10] <= str(grid.index[-1].date()):
        day_live = None  # that session is already a candle of its own
    live = _forming_block(h4[~done], day_live, now) if day_live else None
    if live and candles:
        live["change_pct"] = round((live["close"] / candles[-1]["close"] - 1) * 100, 2)
    live_day = None
    if day_live and day_live.get("close"):
        d = (day_live.get("as_of") or "")[:10]
        live_day = {"t": d, "date": d, "open": round(float(day_live["open"]), 2),
                    "high": round(float(day_live["high"]), 2), "low": round(float(day_live["low"]), 2),
                    "close": round(float(day_live["close"]), 2), "as_of": day_live.get("as_of"),
                    "provisional": bool(day_live.get("provisional", True)),
                    "change_pct": round((float(day_live["close"]) / float(grid["close"].iloc[-1]) - 1) * 100, 2)}
    levels = {"session": str(grid.index[-1].date()), "prev_high": round(float(last["high"]), 2),
              "prev_low": round(float(last["low"]), 2), "last_close": round(float(last["close"]), 2)}
    # The price every distance is measured from: the price now in a session,
    # the last close otherwise.
    levels["reference"] = (round(float(day_live["close"]), 2) if day_live and day_live.get("close")
                           else levels["last_close"])
    ref = levels["reference"]

    # Where a close would have to land for each pattern to form. A "partial"
    # range also needs a feature of the candle itself (a long wick): lighter,
    # and it says what else it needs.
    zones = []
    for p in _proximity().get("patterns", []):
        trig = p.get("trigger") or {}
        common = {"strategy": p["strategy"], "label": p["label"], "side": _side(p.get("option_type")),
                  "base_rate": p.get("probability_next")}
        for lo, hi in trig.get("close_ranges_level") or []:
            zones.append({**common, "low": lo, "high": hi, "certain": True, "needs": []})
        for lo, hi in trig.get("partial_ranges_level") or []:
            zones.append({**common, "low": lo, "high": hi, "certain": False, "needs": trig.get("needs") or []})
    for z in zones:
        if z["low"] <= ref <= z["high"]:
            z.update(condition="already here", edge=None, distance_pts=0.0, distance_pct=0.0)
        else:
            edge = z["low"] if ref < z["low"] else z["high"]
            z.update(condition="at or above" if ref < z["low"] else "at or below", edge=edge,
                     distance_pts=round(edge - ref, 1), distance_pct=round((edge - ref) / ref * 100, 2))
    zones.sort(key=lambda z: (not z["certain"], abs(z["distance_pts"])))
    prox_formed = {p["strategy"] for p in _proximity().get("patterns", []) if p.get("formed_today")}
    in_play = {z["strategy"] for z in zones} | prox_formed | IN_PLAY_EXTRA

    # The candles where a rule was actually met — the "signal candle".
    df, regime = _daily()
    window = {pd.Timestamp(c["date"]) for c in candles + daily}
    formed = []
    for name, spec in STRATEGY_REGISTRY.items():
        if name not in in_play:
            continue  # history is shown for the patterns in play today, not all 26
        try:
            fired = spec["fn"](df, regime, **spec["params"]).astype(bool)
        except Exception:
            continue
        for ts in fired[fired].index:
            if ts.normalize() in window:
                formed.append({"date": str(ts.date()), "strategy": name, "label": spec.get("label", name),
                               "side": _side(spec.get("option_type"))})
    formed.sort(key=lambda f: (f["date"], f["label"]))

    return {
        "as_of": levels["session"],
        "timeframe": "4h",
        "last_candle": candles[-1]["t"] if candles else None,
        "sessions": len({c["date"] for c in candles}),
        "candles": candles,
        "levels": levels,
        "zones": zones,
        "formed": formed,
        "live": live,
        "daily": daily,
        "live_day": live_day,
        "m15": m15,
        "live_m15": live_m15,
        "source": "4-hour blocks from NIFTY's 15-minute bars: the local archive, and Yahoo's for days after it",
        "note": ("Shaded bands: where the day's close (15:30) would have to land for a pattern to form; the patterns "
                 "are decided on the daily close, not on a 4-hour one. Every pattern shown "
                 "was rejected on 2024-26 option data — a band is where a setup appears, not a reason to trade, and "
                 "the call above stays NO TRADE unless one clears the evidence bar."),
    }
