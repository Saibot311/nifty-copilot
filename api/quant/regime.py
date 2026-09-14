"""Market regime classification. Objective, threshold-based — no LLM
judgment involved. Thresholds (ADX 20/25) are the commonly published
Wilder defaults, not tuned to make any particular result look good; they
should be revisited empirically once Phase 6-8 backtesting exists.
"""

from dataclasses import dataclass

import pandas as pd

from .indicators import adx, ema


@dataclass
class RegimeResult:
    regime: str  # TREND_BULL | TREND_BEAR | RANGE | TRANSITION
    adx_value: float
    ema_fast: float
    ema_slow: float


def classify_regime(df: pd.DataFrame, fast_span: int = 20, slow_span: int = 50) -> RegimeResult:
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
