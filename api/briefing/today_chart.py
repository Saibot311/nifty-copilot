"""The Today chart: where NIFTY stands, and what close would change the call.

It used to be 110 generic candles with two moving averages — what any
charting site shows better, and nothing to do with the tab's question. It now
draws the decision in front of the reader:

  * the recent candles and EMA20/EMA50 — the grid's own series and values;
  * the previous session's high and low, which the breakout and breakdown
    rules are judged against at the next close;
  * the bands a close would have to land in for each pattern to form (from
    pattern_proximity), in a "next close" column beside the candles;
  * the candles where a rule was actually met, marked where they happened;
  * during a session, today's candle from live 15-minute bars — provisional.

Everything is computed here (I2); the browser only places it. None of it is
a signal: every pattern it shows was rejected on 2024-26 option data, and
the call on the Today tab stays NO TRADE unless one clears the evidence bar.
"""

from backtest.strategies import STRATEGY_REGISTRY
from quant.indicators import ema


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


# Test hook: strategies to treat as in play besides those with a zone today.
IN_PLAY_EXTRA: set[str] = set()


def _side(option_type: str | None) -> str:
    return "call" if option_type == "CE" else "put"


def today_chart(sessions: int = 90) -> dict:
    grid = _grid_frame()
    e20, e50 = ema(grid["close"], 20), ema(grid["close"], 50)
    tail = grid.tail(sessions)
    candles = [{"date": str(ts.date()), "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
                "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
                "ema20": round(float(e20.loc[ts]), 2), "ema50": round(float(e50.loc[ts]), 2)}
               for ts, r in tail.iterrows()]
    last = grid.iloc[-1]
    live = _live_candle()
    if live and (live.get("as_of") or "")[:10] <= str(grid.index[-1].date()):
        live = None  # that session is already a candle of its own
    levels = {"session": str(grid.index[-1].date()), "prev_high": round(float(last["high"]), 2),
              "prev_low": round(float(last["low"]), 2), "last_close": round(float(last["close"]), 2)}
    # The price every distance is measured from: the live candle's close in a
    # session, the last close otherwise.
    levels["reference"] = round(float(live["close"]), 2) if live and live.get("close") else levels["last_close"]
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
    window = {ts.normalize() for ts in tail.index}
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
        "sessions": len(candles),
        "candles": candles,
        "levels": levels,
        "zones": zones,
        "formed": formed,
        "live": {"provisional": True, **live} if live else None,
        "source": "Yahoo daily, with missing or late sessions filled from NSE's index report",
        "note": ("Shaded bands: where the next close would have to land for a pattern to form. Every pattern shown "
                 "was rejected on 2024-26 option data — a band is where a setup appears, not a reason to trade, and "
                 "the call above stays NO TRADE unless one clears the evidence bar."),
    }
