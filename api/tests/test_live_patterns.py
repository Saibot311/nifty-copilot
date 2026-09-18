"""Phase 10 live tracking: 'would form if today closed now' must be the
pattern's own rule applied to today's candle, and the 'how far to the
trigger' figure must point the right way."""

import numpy as np
import pandas as pd

from backtest.live_patterns import _distance, evaluate_today, merge_live


def _history(n=300):
    rng = np.random.default_rng(3)
    close = 20000 * np.exp(np.cumsum(rng.normal(0, 0.008, n)))
    open_ = np.r_[close[0], close[:-1]]
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.003,
                         "low": np.minimum(open_, close) * 0.997, "close": close, "volume": 0.0}, index=idx)


def test_close_above_yesterdays_high_would_form_prev_day_breakout():
    h = _history()
    y = h.iloc[-1]
    today = h.index[-1] + pd.offsets.BDay(1)
    above = {"open": y.close, "high": y.high + 60, "low": y.close - 10, "close": y.high + 50, "volume": 0.0}
    below = {**above, "high": y.high - 5, "close": y.high - 10}
    assert evaluate_today(h, above, today.date())["prev_day_breakout"] is True
    assert evaluate_today(h, below, today.date())["prev_day_breakout"] is False


def test_distance_is_signed_and_zero_inside_a_range():
    assert _distance(100, [[110, 120]]) == 10       # needs to rise 10
    assert _distance(130, [[110, 120]]) == -10      # needs to fall 10
    assert _distance(115, [[110, 120]]) == 0
    assert _distance(100, [[90, 95], [104, 120]]) == 4  # nearest range wins


def test_merge_shows_forming_and_near_patterns_only():
    live = {"candle": {"close": 10000.0}, "would_form_now": ["a"]}
    prox = {"patterns": [
        {"strategy": "a", "label": "A", "option_type": "CE", "formed_today": False, "trigger": {"close_ranges_level": []}},
        {"strategy": "b", "label": "B", "option_type": "CE", "formed_today": False, "trigger": {"close_ranges_level": [[10050, 10500]]}},
        {"strategy": "c", "label": "C", "option_type": "PE", "formed_today": False, "trigger": {"close_ranges_level": [[9000, 9500]]}},
        {"strategy": "pcr", "label": "P", "option_type": "CE", "formed_today": None, "trigger": None},
    ]}
    rows = merge_live(live, prox, None, near_pct=1.0)
    assert [r["strategy"] for r in rows] == ["a", "b"]  # c is 5% away; PCR can't be simulated
    assert rows[0]["would_form_now"] and rows[0]["points_to_trigger"] is None
    assert rows[1]["points_to_trigger"] == 50 and rows[1]["pct_to_trigger"] == 0.5
