"""The regime classifier had no tests. Every regime-filtered pattern
depends on it, so a label it cannot justify is a signal it cannot justify."""

import numpy as np
import pandas as pd
import pytest

from quant.regime import classify_regime, classify_regime_series


def _df(n, drift=0.002, seed=1):
    rng = np.random.default_rng(seed)
    close = 20000 * np.exp(np.cumsum(rng.normal(drift, 0.004, n)))
    return pd.DataFrame({"open": close, "high": close * 1.004, "low": close * 0.996, "close": close},
                        index=pd.bdate_range("2021-01-01", periods=n))


def test_refuses_to_classify_without_enough_history():
    # Found by the audit: 30 bars returned TREND_BULL; the docstring said it raised.
    with pytest.raises(ValueError, match="need 50"):
        classify_regime(_df(30))


def test_the_series_does_not_label_bars_it_lacks_history_for():
    s = classify_regime_series(_df(120))
    assert (s.iloc[:49] == "UNKNOWN").all()
    assert (s.iloc[49:] != "UNKNOWN").all()


def test_a_steady_climb_reads_as_a_bull_trend():
    assert classify_regime(_df(300, drift=0.004)).regime == "TREND_BULL"


def test_a_steady_fall_reads_as_a_bear_trend():
    assert classify_regime(_df(300, drift=-0.004)).regime == "TREND_BEAR"


def test_single_bar_and_series_agree_on_the_last_bar():
    df = _df(400, drift=0.0005, seed=9)
    assert classify_regime(df).regime == classify_regime_series(df).iloc[-1]
