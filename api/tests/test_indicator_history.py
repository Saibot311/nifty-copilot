"""What followed each indicator reading. What must hold: each day is put in
its bucket from that day's own reading; what followed is the next session,
never the same one; the odds are counted exactly at today's price for every
move size; a bucket stands out only when it differs from the other days well
beyond chance; and every tile on the grid is explained."""

from datetime import date, timedelta

import pandas as pd
import pytest

import briefing.indicator_history as ih


def test_each_reading_falls_in_one_bucket():
    assert ih.bucket("rsi", 36.3) == "30–40" and ih.bucket("rsi", 72) == "above 70" and ih.bucket("rsi", 29.9) == "below 30"
    assert ih.bucket("adx", 41.0) == "40 and over" and ih.bucket("adx", 12) == "under 20"
    assert ih.bucket("vix", 13.59) == "12–15"
    assert ih.bucket("gap", 0.21) == "up 0.2–0.5%" and ih.bucket("gap", 0.0) == "flat (within 0.2%)"
    assert ih.bucket("trend", "below both") == "below both"
    assert ih.bucket("rsi", None) is None


def _frame(n=80):
    days = pd.DatetimeIndex([pd.Timestamp(date(2025, 1, 1) + timedelta(days=i)) for i in range(n)])
    close = pd.Series([100 + (i % 10) for i in range(n)], index=days, dtype=float)
    return pd.DataFrame({"open": close - 1, "high": close + 2, "low": close - 3, "close": close})


def test_what_followed_is_the_next_session_from_its_open():
    df = _frame()
    nxt = ih.next_session(df)
    d0, d1 = df.index[10], df.index[11]
    o, h, lo = df.loc[d1, ["open", "high", "low"]]
    assert nxt.loc[d0, "up_pct"] == pytest.approx((h - o) / o * 100)
    assert nxt.loc[d0, "down_pct"] == pytest.approx((o - lo) / o * 100)
    assert bool(nxt.loc[d0, "closed_up"]) == (df.loc[d1, "close"] > df.loc[d0, "close"])
    assert pd.isna(nxt["up_pct"].iloc[-1])                                 # the last day has no next session yet


def test_readings_use_only_each_days_own_data():
    df = _frame()
    r = ih.readings(df, vix={}, iv30={})
    later = df.copy()
    later.iloc[-1, later.columns.get_loc("close")] = 999                  # change the last day only
    r2 = ih.readings(later, vix={}, iv30={})
    pd.testing.assert_frame_equal(r.iloc[:-1], r2.iloc[:-1])


def test_the_odds_are_counted_exactly_for_every_move_size():
    rows = pd.DataFrame({"rsi": ["30–40"] * 4 + ["50–60"] * 4,
                         "up_pct": [0.1, 0.2, 0.3, 0.4, 0.0, 0.0, 0.0, 0.0],
                         "down_pct": [0.0] * 8, "closed_up": [True, True, False, False] * 2})
    od = ih.odds(rows, "rsi", "30–40", price=25000.0)                      # 25, 50, 75, 100 pts up
    i = {t: k for k, t in enumerate(ih.TARGETS)}
    assert od["like"]["n"] == 4 and od["all"]["n"] == 8
    assert od["like"]["up"][i[50]] == 75.0 and od["like"]["either"][i[100]] == 25.0
    assert od["all"]["up"][i[50]] == 37.5 and od["like"]["closed_up_pct"] == 50.0


def test_every_tile_on_the_grid_is_explained():
    import briefing.live_indicators as li
    for key in li.TILE_KEYS:
        e = ih.EXPLAIN[key]
        assert all(e[k] for k in ("what", "why", "reacts", "buyer")), key
