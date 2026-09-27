"""The afternoon-breakout idea came from a result, so its test must not reuse
the data that suggested it. These hold the rules, the unseen 2015-17 period
and the monthly-expiry calendar that period needs."""

import hashlib
import json
from datetime import date

import pytest

import backtest.breakout_research as br
import backtest.course_strategies as cs
from tests.test_course_strategies import WARM, bars, fixed_indicators


def test_the_preregistration_has_not_been_edited():
    # Logged (hypothesis_log, 2026-09-27) before either hypothesis was computed.
    fixed = json.dumps({**br.PREREGISTERED, "tests": br.TESTS_IN_FAMILY, "min_confirmation": br.MIN_CONFIRMATION_TRADES},
                       sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH == br.PREREG_HASH


PREREGISTERED_HASH = "bbe333f83a7202a8"


def test_the_confirmation_period_is_the_one_no_study_used():
    assert br.period_of(date(2016, 5, 3)) == "confirmation"
    assert br.period_of(date(2018, 1, 2)) == "discovery" and br.period_of(date(2025, 1, 2)) == "discovery"
    assert br.period_of(date(2014, 12, 31)) is None


def test_the_breakout_rides_to_the_close_unless_it_closes_back_inside():
    d = "2024-01-04"
    later = {(d, f"{h:02d}:{m:02d}"): (20070, 20072, 20068, 20070)          # the afternoon stays above the range
             for h in (13, 14, 15) for m in range(0, 60, 5) if (13, 35) <= (h, m) <= (15, 20)}
    df = bars(WARM + [d], {(d, "10:00"): (20000, 20040, 19995, 20000),       # range 19995-20040
                           (d, "13:30"): (20035, 20060, 20030, 20055),       # first close above 20040: long
                           **later, (d, "15:25"): (20090, 20100, 20085, 20095)}, base=20000)
    t = br.afternoon_breakout(cs.Series(df), skip=set())
    assert len(t) == 1 and t[0]["side"] == 1 and t[0]["entry"] == 20055 and t[0]["reason"] == "time"
    back = bars(WARM + [d], {(d, "10:00"): (20000, 20040, 19995, 20000),
                             (d, "13:30"): (20035, 20060, 20030, 20055),
                             (d, "13:35"): (20055, 20056, 20020, 20030)}, base=20000)
    t = br.afternoon_breakout(cs.Series(back), skip=set())
    assert t[0]["reason"] == "back inside" and t[0]["exit"] == 20030


def test_the_reversed_trap_takes_the_other_side_of_the_same_trigger(monkeypatch):
    fixed_indicators(monkeypatch, ema_value=19900.0)
    monkeypatch.setattr(br, "ema", cs.ema)
    d = "2024-01-04"
    df = bars(WARM + [d], {(d, "10:00"): (20000, 20040, 19995, 20000),
                           (d, "13:30"): (20030, 20050, 20025, 20035),       # sweeps 20040, closes back inside
                           (d, "13:35"): (20035, 20150, 20034, 20140)}, base=20000)
    s = cs.Series(df)
    trap, rev = cs.trap_nifty(s, skip=set()), br.trap_reversed(s, skip=set())
    assert trap[0]["entry_ts"] == rev[0]["entry_ts"] and trap[0]["side"] == -rev[0]["side"] == -1
    risk = 20035 - 19999                                                      # the lower low of the last two candles
    assert rev[0]["reason"] == "target" and rev[0]["exit"] == 20035 + 3 * risk


def test_2015_17_expiries_are_last_thursdays_moved_back_over_holidays():
    sessions = [date(2016, 3, d) for d in (21, 22, 23, 28, 29, 30, 31)]  # 24 Mar 2016 (Holi) closed
    assert br.monthly_expiries(sessions, date(2018, 1, 1)) == [date(2016, 3, 31)]
    sessions = [date(2016, 3, d) for d in (21, 22, 23, 28, 29, 30)]      # no 31st: back to the 30th
    assert br.monthly_expiries(sessions, date(2018, 1, 1)) == [date(2016, 3, 30)]


def test_the_dashboard_gets_seven_summaries_and_no_trade_lists(monkeypatch):
    import main
    period = {"num_trades": 10, "mean_pct": 1.0, "median_pct": -2.0, "win_rate": 40.0, "baseline_mean_pct": -1.0,
              "t_vs_baseline": 0.5, "index_points_mean": 3.0, "index_win_rate": 45.0, "trades": [{"entry": 1}]}
    course = {"computed_at": "x", "prereg_hash": "c", "tests_in_family": 58,
              "preregistered": {"hypotheses": {f"s{i}": {"timeframe": "5m"} for i in range(5)}},
              "hypotheses": [{"name": f"s{i}", "label": f"S{i}", "verdict": "REJECTED", "reason": "r", "required_t": 3.2,
                              "development": period, "holdout": period} for i in range(5)]}
    brk = {"prereg_hash": "b", "tests_in_family": 60,
           "hypotheses": [{"name": f"b{i}", "label": f"B{i}", "verdict": "REJECTED", "reason": "r", "required_t": 3.2,
                           "confirmation": period, "discovery_split": {"2018-23": period, "2024-26": period}}
                          for i in range(2)]}
    monkeypatch.setattr(cs, "load_course_research", lambda: course)
    monkeypatch.setattr(br, "load_breakout_research", lambda: brk)
    out = main.course_research()
    assert len(out["rows"]) == 7 and out["tests_in_family"] == 60
    assert "\"trades\":" not in json.dumps(out)          # the per-trade lists stay in the file
    assert [r["judged"] for r in out["rows"]] == ["2024–26"] * 5 + ["2015–17"] * 2
