"""Similarity engine: features must use only past bars, analogs must only
come from days whose outcome was already known, and one episode must not
fill the analog list."""

import numpy as np
import pandas as pd

from backtest.similarity import FEATURES, HORIZON, K, SPACING, _neighbours, features, similar_days


def _df(n=900, seed=5):
    rng = np.random.default_rng(seed)
    close = 10000 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, n)))
    idx = pd.bdate_range("2010-01-01", periods=n)  # pre-2018: no options-archive lookups
    return pd.DataFrame({"open": close, "high": close * 1.004, "low": close * 0.996, "close": close, "volume": 0.0}, index=idx)


def test_features_never_use_future_bars():
    df = _df()
    full = features(df)
    for i in (400, 600, 850):
        cut = features(df.iloc[: i + 1])
        pd.testing.assert_series_equal(cut.iloc[-1], full.iloc[i], check_names=False)


def test_neighbours_come_only_from_the_known_pool_and_are_spread_out():
    f = features(_df())[FEATURES].to_numpy()
    q = len(f) - 1
    pool_end = q - HORIZON + 1
    nb = _neighbours(f, q, pool_end)
    assert len(nb) == K
    idx = sorted(i for i, _ in nb)
    assert max(idx) < pool_end
    assert all(b - a >= SPACING for a, b in zip(idx, idx[1:]))


def test_analog_outcomes_are_reported_against_the_base_rate():
    r = similar_days(_df())
    assert set(r["outcomes"]) == {"analogs", "all_days"}
    assert all(a["date"] < r["as_of"] for a in r["analogs"])
    assert r["walk_forward"]["test_points"] > 30
