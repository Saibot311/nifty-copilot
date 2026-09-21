"""Market regime classification. Objective, threshold-based — no LLM
judgment involved. Thresholds (ADX 20/25) are the commonly published
Wilder defaults, not tuned to make any particular result look good; they
should be revisited empirically once Phase 6-8 backtesting exists.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import adx, ema


@dataclass
class RegimeResult:
    regime: str  # TREND_BULL | TREND_BEAR | RANGE | TRANSITION
    adx_value: float
    ema_fast: float
    ema_slow: float


def classify_regime(df: pd.DataFrame, fast_span: int = 20, slow_span: int = 50) -> RegimeResult:
    # The EMA and ADX here are pandas ewm without min_periods, so they return
    # a number from the second bar on. The isna() check below could therefore
    # never fire, and 30 bars came back labelled TREND_BULL instead of
    # raising as documented. The slow EMA's span is the real minimum.
    if len(df) < slow_span:
        raise ValueError(f"Not enough history to classify regime (need {slow_span}+ bars, got {len(df)}).")
    close = df["close"]
    ema_fast = ema(close, fast_span)
    ema_slow = ema(close, slow_span)
    adx_series = adx(df)

    latest_adx = adx_series.iloc[-1]
    latest_fast = ema_fast.iloc[-1]
    latest_slow = ema_slow.iloc[-1]

    if pd.isna(latest_adx) or pd.isna(latest_fast) or pd.isna(latest_slow):
        raise ValueError("Not enough history to classify regime (need 50+ bars).")

    trending = latest_adx >= 25
    ranging = latest_adx < 20

    if trending and latest_fast > latest_slow:
        regime = "TREND_BULL"
    elif trending and latest_fast < latest_slow:
        regime = "TREND_BEAR"
    elif ranging:
        regime = "RANGE"
    else:
        # ADX between 20-25: neither clearly trending nor clearly ranging.
        regime = "TRANSITION"

    return RegimeResult(
        regime=regime,
        adx_value=round(float(latest_adx), 2),
        ema_fast=round(float(latest_fast), 2),
        ema_slow=round(float(latest_slow), 2),
    )


def classify_regime_series(df: pd.DataFrame, fast_span: int = 20, slow_span: int = 50) -> pd.Series:
    """Same rule as classify_regime, applied bar-by-bar for the whole
    history. Safe from lookahead: EMA/ADX at row i are computed by pandas'
    rolling/ewm operations using only rows <= i, by construction — the
    regime label at row i reflects only information available at that bar,
    never a future one. Used by the backtester to know the regime as it
    would genuinely have appeared at the time of each historical trade.
    """
    close = df["close"]
    ema_fast = ema(close, fast_span)
    ema_slow = ema(close, slow_span)
    adx_series = adx(df)

    trending = adx_series >= 25
    ranging = adx_series < 20
    bullish = ema_fast > ema_slow

    regime = np.select(
        [trending & bullish, trending & ~bullish, ranging],
        ["TREND_BULL", "TREND_BEAR", "RANGE"],
        default="TRANSITION",
    )
    result = pd.Series(regime, index=df.index)
    result[adx_series.isna() | ema_fast.isna() | ema_slow.isna()] = "UNKNOWN"
    # Before the slow EMA has its span of history the label is a guess, and
    # a regime filter must not act on a guess.
    result.iloc[: slow_span - 1] = "UNKNOWN"
    return result
