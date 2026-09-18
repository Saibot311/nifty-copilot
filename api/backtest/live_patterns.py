"""Phase 10 — live trigger tracking during market hours.

Every pattern is decided on a daily close. During the session, this asks:
"if today closed right now, which patterns would form?" — by building
today's candle so far and running every pattern on the real history plus
that candle. Exact, not estimated; but PROVISIONAL until 15:30, because
the day's close is what the patterns actually use.

Today's candle comes from the completed 15-minute bars (Kite, when logged
in) — the original spec's decision point, so the answer only changes on a
15-minute close rather than flickering with every tick. Without a Kite
session it falls back to the live NSE quote and says so.
"""

from datetime import date, datetime, timedelta

import pandas as pd

from market_data.kite_session import IST, KiteNotConfigured, KiteNotLoggedIn
from market_data.live_quote import live_index_quote, market_status
from market_data.zerodha_provider import MARKET_CLOSE, ZerodhaProvider, is_provisional
from quant.regime import classify_regime_series

from .pattern_proximity import WINDOW_BARS
from .strategies import STRATEGY_REGISTRY, load_daily_data


def todays_candle(now: datetime) -> tuple[dict | None, str]:
    """(candle, basis). candle is None if there's nothing from today yet."""
    try:
        bars = [b for b in ZerodhaProvider().get_ohlc("^NSEI", "15m", now.date(), now.date(), now=now) if not b.provisional]
        if bars:
            return {
                "open": bars[0].open, "high": max(b.high for b in bars), "low": min(b.low for b in bars),
                "close": bars[-1].close, "volume": 0.0,
            }, f"15-min close at {(datetime.fromisoformat(bars[-1].timestamp) + timedelta(minutes=15)):%H:%M}"
    except (KiteNotLoggedIn, KiteNotConfigured):
        pass
    q = live_index_quote()
    if not q.get("last"):
        return None, "no live data"
    return {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["last"], "volume": 0.0}, (
        f"live NSE price at {now:%H:%M} (log in to Zerodha for 15-min closes)"
    )


def evaluate_today(history: pd.DataFrame, candle: dict, today: date) -> dict[str, bool]:
    ext = pd.concat([history, pd.DataFrame([candle], index=[pd.Timestamp(today)])])
    reg = classify_regime_series(ext)
    return {
        k: bool(v["fn"](ext, reg, **v["params"]).astype(bool).iloc[-1])
        for k, v in STRATEGY_REGISTRY.items() if not k.startswith("pcr_")
    }


def live_patterns(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    status = market_status()
    session_over = now.time() >= MARKET_CLOSE
    if not status.get("is_open") and not session_over:
        return {"market_open": False, "message": f"Market is {str(status.get('status') or 'closed').lower()}.",
                "patterns": []}

    df, _ = load_daily_data("^NSEI", 1400)
    last_ts = df.index[-1].to_pydatetime().replace(tzinfo=IST)
    if df.index[-1].date() == now.date() or is_provisional(last_ts, "day", now):
        df = df.iloc[:-1]  # judge against yesterday and earlier; today is the candle we build
    history = df.iloc[-WINDOW_BARS:]

    candle, basis = todays_candle(now)
    if candle is None:
        return {"market_open": True, "message": "No price data for today yet.", "patterns": []}

    formed = evaluate_today(history, candle, now.date())
    prev_close = float(history["close"].iloc[-1])
    return {
        "market_open": bool(status.get("is_open")),
        "provisional": not session_over,
        "as_of": now.isoformat(timespec="minutes"),
        "basis": basis,
        "previous_close": round(prev_close, 2),
        "candle": {k: round(v, 2) for k, v in candle.items() if k != "volume"},
        "change_pct": round((candle["close"] / prev_close - 1) * 100, 2),
        "would_form_now": sorted(k for k, v in formed.items() if v),
        "note": (
            "Would form IF today closed at the current level. Patterns use the daily close, so this is "
            "provisional until 15:30 and can change on every 15-minute close."
        ),
    }


def _distance(close: float, ranges: list[list[float]]) -> float | None:
    """Points to move for the close to land in the nearest trigger range (0 if inside)."""
    best = None
    for lo, hi in ranges:
        d = 0.0 if lo <= close <= hi else (lo - close if close < lo else hi - close)
        if best is None or abs(d) < abs(best):
            best = d
    return best


def merge_live(live: dict, prox: dict, research: dict | None, near_pct: float = 1.0) -> list[dict]:
    """One row per pattern that would form now or is within `near_pct` of a
    trigger range, with its option and that option's track record."""
    if not live.get("candle"):
        return []
    close = live["candle"]["close"]
    by_name = {p["strategy"]: p for p in (research or {}).get("patterns", [])}
    rows = []
    for p in prox["patterns"]:
        if p.get("formed_today") is None:  # PCR: not simulable from price
            continue
        trig = p.get("trigger") or {}
        sure = trig.get("close_ranges_level") or []
        now = p["strategy"] in live["would_form_now"]
        dist = _distance(close, sure) if sure else None
        if not now and (dist is None or abs(dist) / close * 100 > near_pct):
            continue
        r = by_name.get(p["strategy"], {})
        rows.append({
            "strategy": p["strategy"], "label": p["label"], "option_type": p["option_type"],
            "would_form_now": now,
            "trigger_ranges_level": sure,
            "points_to_trigger": None if now or dist is None else round(dist, 1),
            "pct_to_trigger": None if now or dist is None else round(dist / close * 100, 2),
            "status": r.get("status"),
            "suggested_option": (r.get("suggested_option") or {}).get("description"),
            "holdout": r.get("holdout"),
            "baseline_rs": (r.get("baseline") or {}).get("holdout_avg_profit_per_lot_rs"),
            "holdout_t_stat": r.get("holdout_t_stat"),
        })
    rows.sort(key=lambda x: (not x["would_form_now"], abs(x["pct_to_trigger"] or 0)))
    return rows
