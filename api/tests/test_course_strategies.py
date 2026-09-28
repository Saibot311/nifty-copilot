"""The five course strategies, each rule checked on made-up bars before the
engine saw NIFTY: a quietly edited registration, a stop that should have
fired, a trade on a day the rule skips, and an option priced with tomorrow's
volatility are the ways this could mislead."""

import hashlib
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

import backtest.course_strategies as cs


def test_the_preregistration_has_not_been_edited():
    # Fixed and logged (hypothesis_log, 2026-09-27 06:42 UTC) before any of
    # the five had been computed on NIFTY. A changed idea is a new test.
    fixed = json.dumps({**cs.PREREGISTERED, "tests": cs.TESTS_IN_FAMILY, "min_holdout": cs.MIN_HOLDOUT_TRADES},
                       sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH == cs.PREREG_HASH


PREREGISTERED_HASH = "42e24490f0b52c4d"  # a literal: computing it live would pass any edit


# --- made-up bars ---------------------------------------------------------------------

SLOTS_5M = pd.timedelta_range("09:15:00", "15:25:00", freq="5min")   # 75 bars


def bars(days: list[str], path=None, base=20000.0) -> pd.DataFrame:
    """Flat 5-minute bars at `base` (range 2 points), with `path` overriding
    chosen bars: {(day, "HH:MM"): (open, high, low, close)}."""
    stamps = pd.DatetimeIndex([pd.Timestamp(d) + t for d in days for t in SLOTS_5M]).tz_localize("Asia/Kolkata")
    df = pd.DataFrame({"open": base, "high": base + 1, "low": base - 1, "close": base}, index=stamps)
    for (d, clock), ohlc in (path or {}).items():
        df.loc[pd.Timestamp(f"{d} {clock}").tz_localize("Asia/Kolkata"), ["open", "high", "low", "close"]] = ohlc
    return df


WARM = ["2024-01-01", "2024-01-02", "2024-01-03"]  # 225 bars of warm-up for the EMA


def fixed_indicators(monkeypatch, ema_value=None, st_dir=None, adx_value=None):
    """Replace the indicators with constants, so a test can set the conditions."""
    if ema_value is not None:
        monkeypatch.setattr(cs, "ema", lambda close, n: pd.Series(ema_value, index=close.index, dtype=float))
    if st_dir is not None:
        monkeypatch.setattr(cs, "supertrend", lambda df, p, m: pd.DataFrame({"direction": st_dir(df)}, index=df.index))
    if adx_value is not None:
        monkeypatch.setattr(cs, "adx", lambda df, n: pd.Series(adx_value(df), index=df.index, dtype=float))


# --- shared pieces ---------------------------------------------------------------------

def test_a_definitive_candle_is_a_60_percent_body_in_the_trades_direction():
    assert cs.definitive(100, 110, 100, 106, 1)          # body 6 of 10, green
    assert not cs.definitive(100, 110, 100, 105.9, 1)    # 59%
    assert not cs.definitive(106, 110, 100, 100, 1)      # red candle, long side
    assert cs.definitive(106, 110, 100, 100, -1)
    assert not cs.definitive(100, 100, 100, 100, 1)      # no range


def test_a_gap_through_the_stop_exits_at_the_open_and_a_bar_touching_both_is_a_stop():
    df = bars(["2024-01-01"], {("2024-01-01", "09:20"): (19990, 19995, 19985, 19990),
                               ("2024-01-01", "09:25"): (20000, 20030, 19990, 20000)})
    s = cs.Series(df)
    j, px, why = cs.run_exit(s, 0, 1, 20000, 19995, 20020, 74)
    assert (j, px, why) == (1, 19990, "stop")               # opened below the stop
    j, px, why = cs.run_exit(s, 1, 1, 19990, 19991, 20020, 74)
    assert why == "stop" and px == 19991                     # 09:25 touched both: stop first


# --- Gap Fill ---------------------------------------------------------------------------

def _daily(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=[date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)])


def test_gap_fill_fades_a_gap_up_in_an_uptrend_and_targets_the_previous_close():
    daily = _daily([(19700, 19800, 19690, 19750), (19750, 19900, 19740, 19880), (19880, 20010, 19870, 20000),
                    (20100, 20120, 19990, 20000)])
    d = "2024-01-04"
    df = bars(WARM + [d], {(d, "09:15"): (20100, 20110, 20090, 20095),     # gap up 0.5%, body 20095-20100
                           (d, "09:20"): (20095, 20096, 20070, 20080),     # closes below the body, 0.40% above PDC
                           (d, "09:25"): (20080, 20081, 19995, 20000)}, base=20080)
    trades = cs.gap_fill(cs.Series(df), daily)
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == -1 and t["entry"] == 20080 and t["entry_ts"].endswith("09:20:00+05:30")
    assert t["reason"] == "target" and t["exit"] == 20000


def test_gap_fill_skips_a_break_too_close_to_the_previous_close_and_a_gap_against_the_trend():
    daily = _daily([(19700, 19800, 19690, 19750), (19750, 19900, 19740, 19880), (19880, 20010, 19870, 20000),
                    (20100, 20120, 19990, 20000)])
    d = "2024-01-04"
    near = bars(WARM + [d], {(d, "09:15"): (20060, 20070, 20050, 20055),
                             (d, "09:20"): (20055, 20056, 20020, 20030)}, base=20030)   # 0.15% from PDC
    assert cs.gap_fill(cs.Series(near), daily) == []
    down = bars(WARM + [d], {(d, "09:15"): (19950, 19960, 19940, 19945),
                             (d, "09:20"): (19945, 19990, 19944, 19985)}, base=19985)   # gap down in an uptrend
    assert cs.gap_fill(cs.Series(down), daily) == []


def test_gap_fill_takes_no_trade_once_the_gap_has_filled():
    """Found by hand on NIFTY's 17 Sep 2026: a 0.10% gap down filled in its
    first candle, and a close above that candle's body — 0.29% above the
    previous close, on the wrong side of it — was taken as a long whose
    "target" lay below the entry."""
    daily = _daily([(20300, 20310, 20190, 20200), (20200, 20210, 19990, 20000), (20000, 20100, 19980, 20050),
                    (19990, 20100, 19980, 20080)])                      # down 1%+ over three days; PDC 20050
    d = "2024-01-04"
    df = bars(WARM + [d], {(d, "09:15"): (20030, 20070, 20028, 20060),  # gap down 0.1%, filled in the first candle
                           (d, "09:20"): (20060, 20115, 20058, 20110)}, base=20110)   # above the body, 0.30% above PDC
    assert cs.gap_fill(cs.Series(df), daily) == []


# --- Trap (adapted) -------------------------------------------------------------------------

def test_the_trap_sells_a_sweep_of_the_morning_high_that_closes_back_inside(monkeypatch):
    fixed_indicators(monkeypatch, ema_value=19900.0)
    d = "2024-01-04"
    df = bars(WARM + [d], {(d, "10:00"): (20000, 20040, 19995, 20000),       # the 4-hour block's high: 20040
                           (d, "13:30"): (20030, 20050, 20025, 20035),       # sweeps 20040, closes back inside
                           (d, "13:35"): (20035, 20036, 19950, 19960)}, base=20000)
    trades = cs.trap_nifty(cs.Series(df), skip=set())
    assert len(trades) == 1 and trades[0]["side"] == -1 and trades[0]["entry"] == 20035
    assert trades[0]["entry_ts"].endswith("13:30:00+05:30")


def test_the_trap_skips_expiry_sessions_and_an_entry_hugging_the_ema(monkeypatch):
    d = "2024-01-04"
    df = bars(WARM + [d], {(d, "10:00"): (20000, 20040, 19995, 20000),
                           (d, "13:30"): (20030, 20050, 20025, 20035)}, base=20000)
    fixed_indicators(monkeypatch, ema_value=19900.0)
    assert cs.trap_nifty(cs.Series(df), skip={date(2024, 1, 4)}) == []
    fixed_indicators(monkeypatch, ema_value=20032.0)                          # 0.015% away
    assert cs.trap_nifty(cs.Series(df), skip=set()) == []


# --- Triple Sync ---------------------------------------------------------------------------

def test_triple_sync_needs_the_conditions_to_turn_true_inside_the_window(monkeypatch):
    d = "2024-01-04"
    path = {(d, "09:30"): (20000, 20020, 19998, 20015),                      # definitive green
            (d, "09:35"): (20015, 20060, 20014, 20055)}
    df = bars(WARM + [d], path, base=20000)
    turn_at = pd.Timestamp(f"{d} 09:30").tz_localize("Asia/Kolkata")
    fixed_indicators(monkeypatch, ema_value=19000.0,
                     st_dir=lambda f: np.where(f.index >= turn_at, 1, -1), adx_value=lambda f: np.full(len(f), 30.0))
    trades = cs.triple_sync(cs.Series(df), skip=set())
    assert len(trades) == 1 and trades[0]["side"] == 1 and trades[0]["entry_ts"].endswith("09:30:00+05:30")
    risk = 20015 - 19998
    assert trades[0]["reason"] == "target" and trades[0]["exit"] == 20015 + 1.5 * risk
    # Already true the day before: no trade.
    fixed_indicators(monkeypatch, st_dir=lambda f: np.ones(len(f), int))
    assert cs.triple_sync(cs.Series(df), skip=set()) == []


# --- TMS Pro ---------------------------------------------------------------------------------

def test_tms_takes_one_trade_per_setup_and_books_the_fixed_0_6_percent(monkeypatch):
    days = WARM + ["2024-01-04"]
    d = "2024-01-04"
    df = bars(days, {(d, "10:00"): (20000, 20020, 19999, 20018),              # definitive green: entry 20018
                     (d, "10:05"): (20018, 20140, 20017, 20130),              # touches +0.6% = 20138.1
                     (d, "10:10"): (20130, 20150, 20125, 20148)}, base=20000)
    fixed_indicators(monkeypatch, ema_value=19000.0, st_dir=lambda f: np.ones(len(f), int))
    trades = cs.tms_pro(cs.Series(df))
    first = [t for t in trades if t["entry_ts"].startswith(d)]
    assert first[0]["entry"] == 20018 and first[0]["reason"] == "target"
    assert first[0]["exit"] == pytest.approx(20018 * 1.006, abs=0.01)
    assert len(first) == 1                                                    # same setup: no second entry


# --- Impulsive Momentum -------------------------------------------------------------------------

def test_impulsive_momentum_trades_the_break_after_the_virtual_fade_is_stopped_out(monkeypatch):
    fixed_indicators(monkeypatch, ema_value=20000.0)
    d = "2024-01-04"
    df = bars(WARM + [d], {
        (d, "09:15"): (19990, 19995, 19985, 19990),        # below the EMA
        (d, "09:20"): (19990, 20015, 19989, 20010),        # upside break
        (d, "09:25"): (20010, 20011, 19992, 19995),        # back inside: red
        (d, "09:30"): (19995, 19996, 19980, 19985),        # red, closes below 19992: DCC -> virtual short, stop 20011
        (d, "09:35"): (19985, 20020, 19984, 20018),        # touches 20011 and closes above: real long at 20018
        (d, "09:40"): (20018, 20100, 20017, 20095)}, base=19985)
    trades = cs.impulsive_momentum(cs.Series(df), skip=set())
    assert len(trades) == 1 and trades[0]["side"] == 1 and trades[0]["entry"] == 20018
    assert trades[0]["entry_ts"].endswith("09:35:00+05:30")
    risk = 20018 - 19980                                   # stop: the lower low of this candle and the one before
    assert trades[0]["reason"] == "target" and trades[0]["exit"] == 20018 + 2 * risk


# --- the modelled option ---------------------------------------------------------------------

def test_black_scholes_obeys_put_call_parity_and_expires_at_intrinsic():
    c = cs.bs_price(1, 20000, 20100, 5 / 365, 0.14)
    p = cs.bs_price(-1, 20000, 20100, 5 / 365, 0.14)
    assert c - p == pytest.approx(20000 - 20100, abs=1e-6)
    assert cs.bs_price(1, 20200, 20100, 0, 0.14) == 100 and cs.bs_price(-1, 20200, 20100, 0, 0.14) == 0


def test_the_option_uses_yesterdays_volatility_and_the_courses_strike_table():
    sessions = [date(2024, 1, d) for d in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12)]
    expiries = [date(2024, 1, 4), date(2024, 1, 11)]
    iv = {date(2024, 1, 2): 0.12, date(2024, 1, 3): 0.50}
    m = cs.OptionModel(sessions, expiries, iv)
    assert m.prior_iv(date(2024, 1, 3)) == 0.12          # the 3rd's own figure is not known at its open
    assert m.choose("tms_pro", date(2024, 1, 1), 20010, 1) == (19900, date(2024, 1, 4))   # 3 sessions: 100 ITM
    assert m.choose("tms_pro", date(2024, 1, 2), 20010, -1) == (20150, date(2024, 1, 4))  # 2 sessions: 150 ITM put
    assert m.choose("tms_pro", date(2024, 1, 3), 20010, 1) == (20000, date(2024, 1, 11))  # 1 session: next, ATM
    assert m.choose("gap_fill", date(2024, 1, 4), 20010, 1) == (20000, date(2024, 1, 11))  # never expiring today


def test_a_flat_trade_loses_the_costs():
    m = cs.OptionModel([date(2024, 1, 1)], [date(2024, 1, 11)], {date(2023, 12, 29): 0.13})
    t = pd.Timestamp("2024-01-01 10:00").tz_localize("Asia/Kolkata")
    r = m.trade_return("gap_fill", 1, t, t, 20000, 20000)
    assert r["option_pct"] == pytest.approx(
        -cs.OptionsCostModel().cost_pct(r["premium_in"], r["premium_in"], "2024-01-01", "2024-01-01"), abs=1e-3)


def test_each_leg_pays_the_rates_of_its_own_day():
    """A position bought before the Finance Act 2026 and sold after it pays
    the new STT on the sale."""
    m = cs.OptionModel([date(2026, 3, 31), date(2026, 4, 1)], [date(2026, 4, 28)], {date(2026, 3, 30): 0.13})
    t_in = pd.Timestamp("2026-03-31 10:00").tz_localize("Asia/Kolkata")
    t_out = pd.Timestamp("2026-04-01 10:00").tz_localize("Asia/Kolkata")
    r = m.trade_return("gap_fill", 1, t_in, t_out, 23000, 23000)
    gross = (r["premium_out"] / r["premium_in"] - 1) * 100
    cost = cs.OptionsCostModel().cost_pct(r["premium_in"], r["premium_out"], "2026-03-31", "2026-04-01")
    assert r["option_pct"] == pytest.approx(gross - cost, abs=0.01)


def test_periods_drop_a_trade_that_straddles_the_split():
    assert cs.period_of(date(2023, 6, 1), date(2023, 6, 1)) == "development"
    assert cs.period_of(date(2023, 12, 29), date(2024, 1, 1)) is None
    assert cs.period_of(date(2024, 1, 2), date(2024, 1, 2)) == "holdout"
    assert cs.period_of(date(2017, 6, 1), date(2017, 6, 1)) is None
