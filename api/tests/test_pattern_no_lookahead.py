"""I1 for every registered pattern: a signal on bar i may only depend on
bars 0..i. Checked generically by truncation — compute the signal on the
full series and on the series cut off at bar i; bar i must agree.

Written after finding that the swing-high/low filter used a *centered*
rolling window, letting four candlestick patterns see two bars ahead.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.strategies import STRATEGY_REGISTRY
from quant.regime import classify_regime_series

# PCR patterns read the options archive rather than the price frame; they
# can't be exercised on synthetic prices.
PRICE_PATTERNS = [n for n in STRATEGY_REGISTRY if not n.startswith("pcr_")]


FIRST_CHECKED_BAR = 260  # past the 252-bar lookback of the 52-week patterns


@pytest.fixture(scope="module")
def synthetic_df():
    """Random OHLC with fat wicks (so candlestick patterns occur), an up-leg
    then a down-leg (so both 52-week patterns occur), and a ~30-day cycle
    (so trends contain pullbacks for the EMA reclaim/rejection patterns)."""
    rng = np.random.default_rng(7)
    n = 700
    t = np.arange(n)
    drift = np.where(t < 480, 0.0015, -0.0015)
    cycle = 0.006 * np.sin(2 * np.pi * t / 30)
    close = 10000 * np.exp(np.cumsum(drift + cycle + rng.normal(0, 0.009, n)))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.exponential(0.005, n))
    low = np.minimum(open_, close) * (1 - rng.exponential(0.005, n))
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 0.0}, index=idx)


@pytest.mark.parametrize("name", PRICE_PATTERNS)
def test_signal_never_depends_on_future_bars(name, synthetic_df):
    spec = STRATEGY_REGISTRY[name]
    full = spec["fn"](synthetic_df, classify_regime_series(synthetic_df), **spec["params"]).astype(bool)
    checked = range(FIRST_CHECKED_BAR, len(synthetic_df) - 3)

    # A look-ahead test on a pattern that never fires proves nothing.
    assert full.iloc[checked.start:checked.stop].any(), f"{name} never fired on the synthetic data"

    for i in checked:
        cut = synthetic_df.iloc[: i + 1]
        partial = spec["fn"](cut, classify_regime_series(cut), **spec["params"]).astype(bool)
        assert bool(partial.iloc[-1]) == bool(full.iloc[i]), (
            f"{name}: signal on {synthetic_df.index[i].date()} changes once later bars exist"
        )


# Patterns defined as "crossed/reclaimed/flipped today" describe a single
# transition day, so they can never be true two days running. Written after
# EMA Pullback/Rejection were found firing on every day of a trend: in pandas 3,
# ~ on a shifted boolean (object dtype) is integer bit-flip, and ~True is truthy.
TRANSITION_PATTERNS = [
    "ema_pullback", "ema_rejection_short", "rsi_reversal", "bollinger_reversion",
    "supertrend_flip_bull", "supertrend_flip_bear", "ema_crossover_bull", "ema_crossover_bear",
    "macd_bull_cross", "macd_bear_cross", "rsi_overbought_reversal", "bollinger_upper_rejection",
    "stochastic_oversold_reversal", "stochastic_overbought_reversal",
]


@pytest.mark.parametrize("name", TRANSITION_PATTERNS)
def test_transition_patterns_never_fire_two_days_running(name, synthetic_df):
    spec = STRATEGY_REGISTRY[name]
    sig = spec["fn"](synthetic_df, classify_regime_series(synthetic_df), **spec["params"]).astype(bool)
    assert sig.any(), f"{name} never fired on the synthetic data"
    both = sig & sig.shift(1, fill_value=False)
    assert not both.any(), f"{name} fired on consecutive days, e.g. {sig.index[both.values][0].date()}"
