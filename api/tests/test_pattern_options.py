"""Pattern -> option research helpers. The easy-to-miss errors here are
sign conventions (OTM is above spot for a call, below it for a put) and
double-counting one market move as several trades."""

import pandas as pd

from backtest.pattern_options import _events_per_year, _non_overlapping, _strike_offset_pct, moneyness_label
from backtest.pattern_proximity import _ranges, _shape_of


def test_otm_means_above_spot_for_calls_and_below_for_puts():
    assert _strike_offset_pct("CE", 1.0) == 1.0     # 1% OTM call: strike above spot
    assert _strike_offset_pct("PE", 1.0) == -1.0    # 1% OTM put: strike below spot
    assert _strike_offset_pct("PE", -2.0) == 2.0    # 2% ITM put: strike above spot
    assert moneyness_label(-2.0) == "2% ITM" and moneyness_label(0.0) == "ATM"


def test_signals_inside_an_open_position_are_skipped():
    # hold 3: position from day 1 to day 4, so a signal on days 1-3 is skipped;
    # a signal on the exit day (4) enters on day 5, after the old position closed.
    assert _non_overlapping([0, 1, 2, 3, 4, 10], hold=3) == [0, 4, 10]


def test_forms_per_year_counts_events_not_days():
    idx = pd.bdate_range("2020-01-01", "2021-01-01")
    fired = pd.Series(False, index=idx)
    fired.iloc[10:15] = True   # one 5-day event
    fired.iloc[100] = True     # a second event
    assert _events_per_year(fired, idx) == round(2 / ((idx[-1] - idx[0]).days / 365.25), 2)


def test_trigger_ranges_merge_adjacent_steps_only():
    assert _ranges([0.5, 0.25, 0.75, 1.5]) == [(0.25, 0.75), (1.5, 1.5)]


def test_candle_shape_classification():
    assert _shape_of(100, 100.6, 97, 100.5) == "long lower wick"   # hammer-like
    assert _shape_of(100.5, 103, 99.9, 100) == "long upper wick"   # shooting-star-like
    assert _shape_of(100, 101.5, 99.5, 101) == "ordinary"
