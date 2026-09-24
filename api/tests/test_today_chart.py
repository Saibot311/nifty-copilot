"""The Today chart answers one question: where is NIFTY now, and what close
would change the call? Everything it draws is computed here (I2): the
candles and EMAs, the previous session's high and low, the price bands where
a pattern would form on the next close, the candles where a pattern formed,
and the provisional live candle. None of it is a signal."""

import numpy as np
import pandas as pd
import pytest

from briefing import today_chart as tc

IDX = pd.bdate_range(end="2026-09-24", periods=260)


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
    return df


def test_the_candles_and_emas_are_the_grids_own(world):
    from quant.indicators import ema
    out = tc.today_chart(sessions=60)
    assert len(out["candles"]) == 60 and out["as_of"] == "2026-09-24"
    assert out["candles"][-1]["ema20"] == round(float(ema(world["close"], 20).iloc[-1]), 2)


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


def test_the_live_candle_is_provisional_and_only_during_a_session(world, monkeypatch):
    assert tc.today_chart(sessions=60)["live"] is None
    monkeypatch.setattr(tc, "_live_candle", lambda: {"open": 23100.0, "high": 23150.0, "low": 23020.0,
                                                     "close": 23080.0, "as_of": "2026-09-25T11:00:00+05:30"})
    live = tc.today_chart(sessions=60)["live"]
    assert live["provisional"] is True and live["close"] == 23080.0


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
