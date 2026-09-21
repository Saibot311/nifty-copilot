"""Phase 5's indicators against independent implementations of their
published definitions. Until the audit these had no tests at all, though
every signal in the system is built on them.

The references are plain loops, deliberately not pandas' ewm/rolling, so
agreement means two different routes reach the same number. Recursive
indicators are compared after a warm-up, because two correct seedings
differ at first and then converge."""

import math

import numpy as np
import pandas as pd
import pytest

from audit.checks_quant import (ref_adx, ref_atr, ref_bollinger, ref_ema, ref_rsi, ref_stoch_k)
from quant import indicators as ind

WARM = 250


@pytest.fixture(scope="module")
def df():
    rng = np.random.default_rng(3)
    n = 900
    close = 20000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    spread = np.abs(rng.normal(0, 0.006, n)) * close
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 0.0},
                        index=pd.bdate_range("2020-01-01", periods=n))


def _close(a, b, rel=1e-9):
    a, b = list(a)[WARM:], list(b)[WARM:]
    for x, y in zip(a, b):
        if not (math.isnan(x) or math.isnan(y)):
            assert x == pytest.approx(y, rel=rel)


def test_ema(df):
    _close(ind.ema(df["close"], 20), ref_ema(df["close"].tolist(), 20))


def test_rsi_is_wilders(df):
    _close(ind.rsi(df["close"], 14), ref_rsi(df["close"].tolist(), 14), rel=1e-6)


def test_atr_is_wilders(df):
    _close(ind.atr(df, 14), ref_atr(df["high"].tolist(), df["low"].tolist(), df["close"].tolist()), rel=1e-6)


def test_adx_is_wilders(df):
    _close(ind.adx(df, 14), ref_adx(df["high"].tolist(), df["low"].tolist(), df["close"].tolist()), rel=1e-5)


def test_stochastic(df):
    _close(ind.stochastic(df)["k"], ref_stoch_k(df["high"].tolist(), df["low"].tolist(), df["close"].tolist()))


def test_bollinger_uses_the_population_standard_deviation(df):
    # Found by the audit: rolling().std() is the sample std, so the bands
    # were sqrt(20/19) ~ 2.6% wider than Bollinger's definition.
    up, lo = ref_bollinger(df["close"].tolist())
    bands = ind.bollinger_bands(df["close"])
    _close(bands["upper"], up)
    _close(bands["lower"], lo)
