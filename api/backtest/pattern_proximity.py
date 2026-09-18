"""Which patterns formed on the last close, and which could form on the next
one — with the price levels that would trigger them and a base-rate
probability.

Method (generic across every price pattern, no per-pattern special cases):
  1. Build candidate next-session candles: close -3%..+3% in 0.25% steps,
     opening gap down / flat / up, and three shapes (ordinary wicks, long
     lower wick, long upper wick).
  2. Append each candidate to the real history and run every pattern on it.
  3. Weight each candidate by how often a day in that same bucket (return,
     gap, shape) actually happened over the last ~3 years.

So "18% chance" means: on 18% of recent days, the day looked like one that
would trigger this pattern from today's position. It's a base rate, not a
forecast — it knows nothing about news or tomorrow's direction.
"""

from datetime import datetime

import numpy as np
import pandas as pd

from market_data.kite_session import IST
from market_data.zerodha_provider import is_provisional
from quant.regime import classify_regime_series

from .pattern_info import PATTERN_INFO
from .strategies import STRATEGY_REGISTRY, load_daily_data

RETURNS = np.round(np.arange(-3.0, 3.001, 0.25), 2)
GAPS = {"gap down": -0.4, "flat open": 0.0, "gap up": 0.4}
SHAPES = ("ordinary", "long lower wick", "long upper wick")
HISTORY_DAYS = 750
WINDOW_BARS = 420  # enough for the 252-bar 52-week patterns plus indicator warm-up


def _shape_of(o, h, l, c) -> str:
    body = abs(c - o)
    upper, lower = h - max(o, c), min(o, c) - l
    if body > 0 and lower >= 2 * body and upper <= 0.5 * body:
        return "long lower wick"
    if body > 0 and upper >= 2 * body and lower <= 0.5 * body:
        return "long upper wick"
    return "ordinary"


def _gap_of(gap_pct: float) -> str:
    return "gap down" if gap_pct < -0.2 else "gap up" if gap_pct > 0.2 else "flat open"


def bucket_frequencies(df: pd.DataFrame) -> dict[tuple, float]:
    """Share of recent days falling in each (return, gap, shape) bucket."""
    recent = df.iloc[-HISTORY_DAYS - 1:]
    prev = recent["close"].shift(1)
    counts: dict[tuple, int] = {}
    n = 0
    for i in range(1, len(recent)):
        row, pc = recent.iloc[i], prev.iloc[i]
        r = float(np.clip(round((row["close"] / pc - 1) * 100 / 0.25) * 0.25, RETURNS[0], RETURNS[-1]))
        key = (round(r, 2), _gap_of((row["open"] / pc - 1) * 100), _shape_of(row["open"], row["high"], row["low"], row["close"]))
        counts[key] = counts.get(key, 0) + 1
        n += 1
    return {k: v / n for k, v in counts.items()}


def _candidate(prev_close: float, r: float, gap: float, shape: str, wick: float) -> dict:
    o, c = prev_close * (1 + gap / 100), prev_close * (1 + r / 100)
    top, bot, body = max(o, c), min(o, c), abs(c - o)
    if shape == "long lower wick":
        high, low = top + 0.2 * body, bot - max(2.5 * body, 3 * wick * prev_close)
    elif shape == "long upper wick":
        high, low = top + max(2.5 * body, 3 * wick * prev_close), bot - 0.2 * body
    else:
        high, low = top + wick * prev_close, bot - wick * prev_close
    return {"open": o, "high": high, "low": low, "close": c, "volume": 0.0}


def _ranges(values: list[float]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for v in sorted(values):
        if out and abs(v - out[-1][1] - 0.25) < 1e-9:
            out[-1][1] = v
        else:
            out.append([v, v])
    return [(a, b) for a, b in out]


def pattern_proximity(symbol: str = "^NSEI", now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    df, _ = load_daily_data(symbol, 1400)
    last_ts = df.index[-1].to_pydatetime().replace(tzinfo=IST)
    if is_provisional(last_ts, "day", now):
        df = df.iloc[:-1]  # today's bar is still forming: judge from the last final close
    as_of = str(df.index[-1].date())

    window = df.iloc[-WINDOW_BARS:]
    prev_close = float(window["close"].iloc[-1])
    wick = float(((window["high"] - window[["open", "close"]].max(axis=1)) / window["close"]).median())
    freqs = bucket_frequencies(df)
    next_day = window.index[-1] + pd.offsets.BDay(1)

    price_patterns = {k: v for k, v in STRATEGY_REGISTRY.items() if not k.startswith("pcr_")}
    regime_now = classify_regime_series(window)
    formed_today = {
        k: bool(v["fn"](window, regime_now, **v["params"]).astype(bool).iloc[-1]) for k, v in price_patterns.items()
    }

    triggers: dict[str, list[tuple]] = {k: [] for k in price_patterns}
    for gap_name, gap in GAPS.items():
        for shape in SHAPES:
            for r in RETURNS:
                row = pd.DataFrame([_candidate(prev_close, float(r), gap, shape, wick)], index=[next_day])
                ext = pd.concat([window, row])
                reg = classify_regime_series(ext)
                for k, v in price_patterns.items():
                    if bool(v["fn"](ext, reg, **v["params"]).astype(bool).iloc[-1]):
                        triggers[k].append((float(r), gap_name, shape))

    patterns = []
    for k, spec in STRATEGY_REGISTRY.items():
        entry = {
            "strategy": k, "label": spec["label"], "direction": spec["direction"],
            "option_type": spec["option_type"], **PATTERN_INFO.get(k, {}),
        }
        if k not in price_patterns:
            entry.update(formed_today=None, probability_next=None, trigger=None,
                         note="Depends on the next session's option open interest, which can't be simulated from price.")
            patterns.append(entry)
            continue

        hits = triggers[k]
        prob = sum(freqs.get((round(r, 2), g, s), 0.0) for r, g, s in hits)
        trigger = None
        if hits:
            combos_per_close: dict[float, set] = {}
            for r, g, sh in hits:
                combos_per_close.setdefault(r, set()).add((g, sh))
            n_combos = len(GAPS) * len(SHAPES)
            certain = [r for r, c in combos_per_close.items() if len(c) == n_combos]
            partial = [r for r, c in combos_per_close.items() if len(c) < n_combos]
            shapes, gaps = {s for _, _, s in hits}, {g for _, g, _ in hits}
            needs = []
            if len(shapes) == 1 and "ordinary" not in shapes:
                needs.append(f"a candle with a {next(iter(shapes))}")
            if len(gaps) == 1:
                needs.append(f"a {next(iter(gaps))}")

            def levels(rs):
                return [[round(prev_close * (1 + a / 100)), round(prev_close * (1 + b / 100))] for a, b in _ranges(rs)]

            trigger = {
                # closes that trigger it whatever the open and wicks look like
                "close_ranges_pct": [list(x) for x in _ranges(certain)],
                "close_ranges_level": levels(certain),
                # closes that trigger it only with some opens/candle shapes
                "partial_ranges_level": levels(partial),
                "needs": needs,
            }
        entry.update(formed_today=formed_today[k], probability_next=round(prob, 3), trigger=trigger)
        patterns.append(entry)

    patterns.sort(key=lambda p: (not p.get("formed_today"), -(p.get("probability_next") or 0)))
    return {
        "as_of": as_of,
        "last_close": round(prev_close, 2),
        "patterns": patterns,
        "method_note": (
            f"Probabilities are base rates: the share of the last ~{HISTORY_DAYS} sessions that looked like a day "
            "which would trigger the pattern from today's position (same close-to-close move, opening gap and "
            "candle shape, in 0.25% steps). They say how often such a day happens, not whether tomorrow will be one."
        ),
    }
