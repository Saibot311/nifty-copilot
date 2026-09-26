"""The Today chart answers one question: where is NIFTY now, and what close
would change the call? Everything it draws is computed here (I2): the
4-hour candles and their EMAs, the previous session's high and low, the price
bands where a pattern would form on the day's close, the days a pattern
formed, and the provisional block still forming. None of it is a signal."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from briefing import today_chart as tc

IDX = pd.bdate_range(end="2026-09-24", periods=260)
IST = "Asia/Kolkata"
# A session's 15-minute bars start 09:15 and the last one 15:15: 25 bars.
SLOTS = pd.timedelta_range("09:15:00", "15:15:00", freq="15min")


def fifteen_minute_bars(days, seed=7):
    stamps = pd.DatetimeIndex([d + t for d in days for t in SLOTS]).tz_localize(IST)
    close = 23000 + np.cumsum(np.random.default_rng(seed).normal(0, 12, len(stamps)))
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close + 6, "low": close - 6,
                         "close": close}, index=stamps)


@pytest.fixture
def world(monkeypatch):
    close = pd.Series(23000 + np.cumsum(np.random.default_rng(3).normal(0, 60, len(IDX))), index=IDX)
    df = pd.DataFrame({"open": close.shift(1).fillna(close.iloc[0]), "high": close + 40, "low": close - 40,
                       "close": close, "volume": 0.0})
    monkeypatch.setattr(tc, "_daily", lambda: (df, pd.Series("RANGE", index=IDX)))
    monkeypatch.setattr(tc, "_grid_frame", lambda: df)
    monkeypatch.setattr(tc, "_proximity", lambda: {"as_of": "2026-09-24", "patterns": [
        {"strategy": "prev_day_breakout", "label": "Prev-Day-High Breakout", "option_type": "CE",
         "probability_next": 0.115, "formed_today": False,
         "trigger": {"close_ranges_level": [[23282, 23755]], "partial_ranges_level": [], "needs": []}},
        {"strategy": "hammer_reversal", "label": "Hammer", "option_type": "CE", "probability_next": 0.03,
         "formed_today": False,
         "trigger": {"close_ranges_level": [], "partial_ranges_level": [[22371, 23755]], "needs": ["a long lower wick"]}},
        {"strategy": "ema_pullback", "label": "EMA Pullback", "option_type": "CE", "probability_next": 0.0,
         "formed_today": False, "trigger": None},
    ]})
    fires = {"up_rule": IDX[-3], "down_rule": IDX[-70]}
    monkeypatch.setattr(tc, "IN_PLAY_EXTRA", {"up_rule", "down_rule"}, raising=False)
    monkeypatch.setattr(tc, "STRATEGY_REGISTRY", {
        "up_rule": {"fn": lambda d, r: pd.Series(d.index == fires["up_rule"], index=d.index), "params": {},
                    "label": "Up Rule", "option_type": "CE"},
        "down_rule": {"fn": lambda d, r: pd.Series(d.index == fires["down_rule"], index=d.index), "params": {},
                      "label": "Down Rule", "option_type": "PE"}})
    monkeypatch.setattr(tc, "_live_candle", lambda: None)
    monkeypatch.setattr(tc, "_bars15", lambda: fifteen_minute_bars(IDX[-130:]))
    monkeypatch.setattr(tc, "_now", lambda: datetime.fromisoformat("2026-09-24T20:00+05:30"))
    return df


def test_candles_are_four_hour_blocks_built_from_the_15_minute_bars(world):
    """NSE's 4-hour split: 09:15-13:15 and 13:15-15:30, two a session."""
    bars = fifteen_minute_bars(IDX[-130:])
    out = tc.today_chart(sessions=60)
    assert len(out["candles"]) == 120
    last_two = out["candles"][-2:]
    assert [c["t"] for c in last_two] == ["2026-09-24T09:15", "2026-09-24T13:15"]
    day = bars[bars.index.date == IDX[-1].date()]
    morning, afternoon = day.iloc[:16], day.iloc[16:]
    assert last_two[0]["open"] == round(morning["open"].iloc[0], 2)
    assert last_two[0]["high"] == round(morning["high"].max(), 2) and last_two[0]["low"] == round(morning["low"].min(), 2)
    assert last_two[1]["close"] == round(afternoon["close"].iloc[-1], 2)


def test_the_emas_are_of_the_4_hour_closes_over_the_whole_history(world):
    from quant.indicators import ema
    h4 = tc.four_hour(fifteen_minute_bars(IDX[-130:]))
    out = tc.today_chart(sessions=60)
    assert out["candles"][-1]["ema20"] == round(float(ema(h4["close"], 20).iloc[-1]), 2)
    assert out["candles"][-1]["ema50"] == round(float(ema(h4["close"], 50).iloc[-1]), 2)


def test_only_the_block_that_ends_at_the_close_carries_the_day(world):
    candles = tc.today_chart(sessions=60)["candles"]
    assert all(c["day_close"] == c["t"].endswith("13:15") for c in candles)
    assert all(c["date"] == c["t"][:10] for c in candles)


def test_the_levels_the_next_close_is_judged_against(world):
    out = tc.today_chart(sessions=60)
    last = world.iloc[-1]
    assert out["levels"]["prev_high"] == round(float(last["high"]), 2)
    assert out["levels"]["prev_low"] == round(float(last["low"]), 2)
    assert out["levels"]["last_close"] == round(float(last["close"]), 2)


def test_zones_are_where_a_pattern_would_form_on_the_next_close(world):
    zones = tc.today_chart(sessions=60)["zones"]
    assert [(z["label"], z["side"], z["low"], z["high"], z["certain"]) for z in zones] == [
        ("Prev-Day-High Breakout", "call", 23282, 23755, True),
        ("Hammer", "call", 22371, 23755, False)]            # needs a wick too: a lighter band, and says so
    assert zones[1]["needs"] == ["a long lower wick"]


def test_formed_markers_are_the_candles_a_rule_was_met_on_inside_the_window(world):
    out = tc.today_chart(sessions=60)
    assert out["formed"] == [{"date": str(IDX[-3].date()), "strategy": "up_rule", "label": "Up Rule", "side": "call"}]


def test_in_a_session_the_block_still_forming_is_provisional_and_follows_the_price(world, monkeypatch):
    assert tc.today_chart(sessions=60)["live"] is None
    today = pd.Timestamp("2026-09-25")
    bars = fifteen_minute_bars(list(IDX[-130:]) + [today])
    so_far = bars[bars.index < pd.Timestamp("2026-09-25 11:00", tz=IST)]      # 09:15 ... 10:45
    monkeypatch.setattr(tc, "_bars15", lambda: so_far)
    monkeypatch.setattr(tc, "_now", lambda: datetime.fromisoformat("2026-09-25T11:02+05:30"))
    monkeypatch.setattr(tc, "_live_candle", lambda: {"open": 23100.0, "high": 23150.0, "low": 23020.0,
                                                     "close": 23080.0, "as_of": "2026-09-25T11:02:00+05:30"})
    out = tc.today_chart(sessions=60)
    assert out["candles"][-1]["t"] == "2026-09-24T13:15"          # the morning block is not over
    live = out["live"]
    assert live["provisional"] is True and live["t"] == "2026-09-25T09:15" and live["close"] == 23080.0
    assert live["open"] == round(so_far["open"].iloc[-7], 2)
    assert live["high"] == round(max(so_far["high"].iloc[-7:].max(), 23080.0), 2)


def test_after_13_15_the_morning_block_is_a_candle_and_the_afternoon_one_is_forming(world, monkeypatch):
    today = pd.Timestamp("2026-09-25")
    bars = fifteen_minute_bars(list(IDX[-130:]) + [today])
    so_far = bars[bars.index < pd.Timestamp("2026-09-25 14:00", tz=IST)]
    monkeypatch.setattr(tc, "_bars15", lambda: so_far)
    monkeypatch.setattr(tc, "_now", lambda: datetime.fromisoformat("2026-09-25T14:03+05:30"))
    monkeypatch.setattr(tc, "_live_candle", lambda: {"open": 23100.0, "high": 23150.0, "low": 23020.0,
                                                     "close": 23080.0, "as_of": "2026-09-25T14:03:00+05:30"})
    out = tc.today_chart(sessions=60)
    assert out["candles"][-1]["t"] == "2026-09-25T09:15" and out["candles"][-1]["day_close"] is False
    assert out["live"]["t"] == "2026-09-25T13:15"


def test_each_zone_says_what_close_forms_it_and_how_far_that_is(world):
    out = tc.today_chart(sessions=60)
    ref = out["levels"]["reference"]
    z = out["zones"][0]                                   # 23,282-23,755: above wherever the index is now
    if ref < z["low"]:
        assert z["condition"] == "at or above" and z["edge"] == 23282
        assert z["distance_pts"] == round(23282 - ref, 1) and z["distance_pct"] == round((23282 - ref) / ref * 100, 2)


def test_markers_are_only_for_the_patterns_in_play_today(world, monkeypatch):
    fires = IDX[-3]
    monkeypatch.setattr(tc, "STRATEGY_REGISTRY", {
        "prev_day_breakout": {"fn": lambda d, r: pd.Series(d.index == fires, index=d.index), "params": {},
                              "label": "Prev-Day-High Breakout", "option_type": "CE"},
        "unrelated": {"fn": lambda d, r: pd.Series(d.index == fires, index=d.index), "params": {},
                      "label": "Unrelated", "option_type": "PE"}})
    assert [f["strategy"] for f in tc.today_chart(sessions=60)["formed"]] == ["prev_day_breakout"]


def test_after_the_close_nothing_is_forming_and_the_day_is_two_candles(world, monkeypatch):
    today = pd.Timestamp("2026-09-25")
    monkeypatch.setattr(tc, "_bars15", lambda: fifteen_minute_bars(list(IDX[-130:]) + [today]))
    monkeypatch.setattr(tc, "_now", lambda: datetime.fromisoformat("2026-09-25T16:10+05:30"))
    monkeypatch.setattr(tc, "_live_candle", lambda: {"open": 23100.0, "high": 23150.0, "low": 23020.0,
                                                     "close": 23080.0, "as_of": "2026-09-25T16:10:00+05:30"})
    out = tc.today_chart(sessions=60)
    assert out["live"] is None
    assert [c["t"] for c in out["candles"][-2:]] == ["2026-09-25T09:15", "2026-09-25T13:15"]
