"""A handful of price-action checks, fully implemented. This is deliberately
not the full list from the project spec (previous-week levels, opening-range
breakout, engulfing, etc.) — those get added incrementally as they're
actually needed for a strategy, rather than all at once as unused code.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass
class PriceActionFlags:
    prev_day_high: float
    prev_day_low: float
    broke_prev_day_high: bool
    broke_prev_day_low: bool
    structure: str  # "higher_high_higher_low" | "lower_high_lower_low" | "mixed"


def evaluate(df: pd.DataFrame, structure_lookback: int = 5) -> PriceActionFlags:
    if len(df) < structure_lookback + 1:
        raise ValueError(f"Need at least {structure_lookback + 1} bars for price-action checks.")

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    recent = df.iloc[-structure_lookback:]
    highs = recent["high"].to_numpy()
    lows = recent["low"].to_numpy()

    higher_highs = all(highs[i] > highs[i - 1] for i in range(1, len(highs)))
    higher_lows = all(lows[i] > lows[i - 1] for i in range(1, len(lows)))
    lower_highs = all(highs[i] < highs[i - 1] for i in range(1, len(highs)))
    lower_lows = all(lows[i] < lows[i - 1] for i in range(1, len(lows)))

    if higher_highs and higher_lows:
        structure = "higher_high_higher_low"
    elif lower_highs and lower_lows:
        structure = "lower_high_lower_low"
    else:
        structure = "mixed"

    return PriceActionFlags(
        prev_day_high=round(float(prev["high"]), 2),
        prev_day_low=round(float(prev["low"]), 2),
        broke_prev_day_high=bool(latest["high"] > prev["high"]),
        broke_prev_day_low=bool(latest["low"] < prev["low"]),
        structure=structure,
    )
