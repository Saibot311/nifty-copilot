"""Structural hypotheses for an option buyer. The ways they could mislead:
a quietly edited hypothesis, a signal that sees the future, a month-end or
holiday date only knowable afterwards, and a baseline test that forgets the
baseline is a sample too."""

import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

import backtest.structural_research as sr
from backtest.walkforward import welch_t_stat


def test_the_preregistration_has_not_been_edited():
    # Fixed and logged (hypothesis_log, 2026-09-22 11:04 UTC) before any of
    # the six had been computed. A changed idea is a new test, not an edit.
    fixed = json.dumps({**sr.PREREGISTERED, "tests": sr.TESTS_IN_FAMILY, "min_holdout": sr.MIN_HOLDOUT_TRADES,
                        "min_dte": sr.MIN_DTE}, sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH
    assert sr.PREREG_HASH == PREREGISTERED_HASH


PREREGISTERED_HASH = "6f8cf90f4c351b4a"  # a literal: computing it live would pass any edit


def test_every_trade_is_a_bought_call_or_put():
    df = _df()
    for sigs in (sr.absorbed_gap(df), sr.turn_of_month([str(d.date()) for d in df.index])):
        assert {k for _, k in sigs} <= {"CE", "PE"}


def _df(n=300, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = close * np.exp(rng.normal(0, 0.01, n))
    return pd.DataFrame({"open": open_, "close": close}, index=idx)


@pytest.mark.parametrize("builder", ["gap", "vol"])
def test_signals_never_change_when_the_future_is_cut_off(builder):
    df = _df()
    iv = pd.Series(0.15, index=[str(d.date()) for d in df.index])
    run = (lambda d: sr.absorbed_gap(d)) if builder == "gap" else (lambda d: sr.cheap_volatility_trend(d, iv))
    full = run(df)
    for cut in (120, 200, 260):
        part = run(df.iloc[:cut])
        last = str(df.index[cut - 1].date())
        assert part == [s for s in full if s[0] <= last]


def test_the_positioning_percentile_uses_only_the_past():
    s = pd.Series(np.arange(300, dtype=float))
    p = sr.trailing_percentile(s, 250)
    assert p.iloc[:249].isna().all() and p.iloc[260] == 100.0
    s2 = s.copy()
    s2.iloc[280:] = -1  # changing later days must not move an earlier rank
    assert sr.trailing_percentile(s2, 250).iloc[270] == p.iloc[270]


def test_turn_of_month_skips_the_month_still_running():
    td = [d.date().isoformat() for d in pd.bdate_range("2026-07-01", "2026-09-15")]
    sigs = [d for d, _ in sr.turn_of_month(td)]
    assert sigs == ["2026-07-29", "2026-08-27"]  # third-last sessions; September isn't over


def test_pre_holiday_signals_three_sessions_before_a_weekday_holiday():
    td = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09"]
    # 2026-03-10 (Tue) missing -> holiday; last session before it is 03-09 (Mon)
    hol = sr.weekday_holidays(set(td) | {"2026-03-11"}, "2026-03-02", "2026-03-11")
    assert hol == ["2026-03-10"]
    assert sr.pre_holiday(td, hol) == [("2026-03-05", "CE")]  # buy 03-06 close, sell 03-09 close


def test_signals_are_spaced_so_trades_never_overlap():
    td = [f"2026-01-{d:02d}" for d in range(1, 21)]
    sigs = [(td[0], "CE"), (td[2], "PE"), (td[4], "CE"), (td[9], "CE")]
    assert sr.non_overlapping(sigs, td, hold=3) == [(td[0], "CE"), (td[4], "CE"), (td[9], "CE")]


def test_one_leg_weighted_welch_is_plain_welch():
    a, b = [1.0, 3.0, 2.0, 5.0], [0.0, 1.0, -1.0, 0.5, 0.2]
    t, mean = sr.weighted_welch(a, [(4, b)])
    assert t == welch_t_stat(a, b) and mean == pytest.approx(sum(b) / len(b))


def test_two_leg_baseline_is_weighted_by_signal_share():
    ce, pe = [10.0, 12.0, 11.0], [-5.0, -4.0, -6.0]
    _, mean = sr.weighted_welch([1.0, 2.0, 3.0, 4.0], [(3, ce), (1, pe)])
    assert mean == pytest.approx(0.75 * 11 + 0.25 * -5)


def test_overnight_and_intraday_compound_to_the_whole_move():
    df = _df()
    d = sr.overnight_vs_intraday(df, since="2000-01-01")
    whole = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    parts = (1 + d["overnight_total_pct"] / 100) * (1 + d["intraday_total_pct"] / 100) - 1
    assert parts == pytest.approx(whole, abs=0.002)
    assert not math.isnan(d["overnight_up_share"])
