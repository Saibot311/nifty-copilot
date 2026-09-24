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


# --- India VIX: NSE's own figure, not Yahoo's lagging one ----------------------

def test_india_vix_comes_from_nse_and_says_so(monkeypatch):
    """Yahoo's ^INDIAVIX stopped at 23 Sep (10.35) and skipped sessions;
    NSE's close on the 24th was 12.7. The grid showed the stale one with no
    date on it."""
    import market_data.live_quote as lq
    from quant import pipeline
    monkeypatch.setattr(lq, "live_index_quote", lambda index="NIFTY 50": {
        "india_vix": 12.7, "fetched_at": "2026-09-25T02:46:00+05:30", "market_time": "2026-09-24T15:30+05:30"})

    class Yahoo:
        def get_ohlc(self, *a, **k):
            raise AssertionError("Yahoo is only the fallback")
    v = pipeline._india_vix(Yahoo())
    # NSE's own time for the figure (the close), not the moment it was asked.
    assert v == {"value": 12.7, "source": "NSE", "as_of": "2026-09-24T15:30+05:30"}
    assert lq._nse_time("24-Sep-2026 15:30") == "2026-09-24T15:30+05:30" and lq._nse_time(None) is None


def test_yahoo_is_the_fallback_and_carries_its_date(monkeypatch):
    import market_data.live_quote as lq
    from market_data.base import Candle
    from quant import pipeline

    def down(index="NIFTY 50"):
        raise RuntimeError("NSE unreachable")
    monkeypatch.setattr(lq, "live_index_quote", down)

    class Yahoo:
        def get_ohlc(self, *a, **k):
            return [Candle(timestamp="2026-09-23T00:00:00", open=1, high=1, low=1, close=10.35, volume=0)]
    assert pipeline._india_vix(Yahoo()) == {"value": 10.35, "source": "Yahoo daily", "as_of": "2026-09-23"}


def test_no_vix_is_shown_as_missing(monkeypatch):
    import market_data.live_quote as lq
    from quant import pipeline
    monkeypatch.setattr(lq, "live_index_quote", lambda index="NIFTY 50": {"india_vix": None})

    class Yahoo:
        def get_ohlc(self, *a, **k):
            return []
    assert pipeline._india_vix(Yahoo())["value"] is None


# --- the Today chart ------------------------------------------------------------

def test_the_chart_draws_the_same_series_and_the_same_emas_as_the_grid(monkeypatch):
    """The chart read Yahoo's raw feed (a day behind, with 22 Sep missing)
    and computed its EMAs in the browser from the ~96 bars on screen — so its
    lines did not match the EMA20/EMA50 printed beside it, and the EMA50
    only began halfway across. It now draws what Python computed over the
    full history the grid uses."""
    import numpy as np
    import pandas as pd

    from quant import pipeline
    from quant.indicators import ema
    idx = pd.bdate_range(end="2026-09-24", periods=260)
    close = pd.Series(23000 + np.cumsum(np.random.default_rng(1).normal(0, 80, len(idx))), index=idx)
    df = pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]), "high": close + 50, "low": close - 50,
                       "close": close, "volume": 0.0})
    monkeypatch.setattr(pipeline, "daily_frame", lambda symbol="^NSEI", days=400: df)
    out = pipeline.chart_series(sessions=110)
    assert out["as_of"] == "2026-09-24" and out["sessions"] == 110 and len(out["candles"]) == 110
    last = out["candles"][-1]
    assert last["ema20"] == round(float(ema(close, 20).iloc[-1]), 2)          # over the full history
    assert last["ema50"] == round(float(ema(close, 50).iloc[-1]), 2)
    assert last["ema50"] != round(float(ema(close.tail(110), 50).iloc[-1]), 2)  # not the window alone
    assert all(c["ema50"] is not None for c in out["candles"])                  # a line across the whole chart
    assert [c["date"] for c in out["candles"]] == sorted(c["date"] for c in out["candles"])
