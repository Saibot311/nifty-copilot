"""The strategy pipeline's five hypotheses, each rule checked on made-up bars and
made-up option rows before the study saw NIFTY: an edited registration, a rule
that peeks at a later bar, a straddle on the wrong expiry, and a signal traded
at the close that produced it are the ways this could mislead."""

import hashlib
import json
import math

import numpy as np
import pandas as pd
import pytest

import backtest.nifty_pipeline as npl
from backtest.course_strategies import Series


def test_the_preregistration_has_not_been_edited():
    # Fixed and committed on 2026-09-30 before any of the five had been
    # computed on NIFTY. A changed idea is a new test.
    fixed = json.dumps({**npl.PREREGISTERED, "tests": npl.TESTS_IN_FAMILY, "min_holdout": npl.MIN_HOLDOUT_TRADES},
                       sort_keys=True)
    assert hashlib.sha256(fixed.encode()).hexdigest()[:16] == PREREGISTERED_HASH == npl.PREREG_HASH


PREREGISTERED_HASH = "e0dd9b3f9fe1986b"  # a literal: computing it live would pass any edit


def test_events_leave_out_the_unannounced_rbi_decisions():
    ev = npl.events()
    assert ev == sorted(set(ev))
    for d in npl.RBI_OFF_CYCLE:
        assert d not in ev
    assert "2024-06-04" in ev and "2019-07-05" in ev and "2022-09-30" in ev
    assert len(ev) == len(npl.RBI_DECISIONS) - len(npl.RBI_OFF_CYCLE) + len(npl.BUDGETS) + len(npl.ELECTION_RESULTS)


# --- made-up 5-minute bars ------------------------------------------------------------

SLOTS_5M = pd.timedelta_range("09:15:00", "15:25:00", freq="5min")   # 75 bars, stamped at the start


def days(n: int, first: str = "2025-01-01") -> list[str]:
    return [d.date().isoformat() for d in pd.bdate_range(first, periods=n)]


def bars(ds: list[str], path=None, base=20000.0) -> pd.DataFrame:
    """Flat bars at `base` with a 2-point range, `path` overriding chosen bars:
    {(day, "HH:MM"): (open, high, low, close)}."""
    stamps = pd.DatetimeIndex([pd.Timestamp(d) + t for d in ds for t in SLOTS_5M]).tz_localize("Asia/Kolkata")
    df = pd.DataFrame({"open": base, "high": base + 1, "low": base - 1, "close": base}, index=stamps)
    for (d, clock), ohlc in (path or {}).items():
        df.loc[pd.Timestamp(f"{d} {clock}").tz_localize("Asia/Kolkata"), ["open", "high", "low", "close"]] = ohlc
    return df


def walk(n_days: int, seed: int) -> pd.DataFrame:
    """A random walk with real OHLC shape, enough days for the noise band."""
    rng = np.random.default_rng(seed)
    ds = days(n_days)
    stamps = pd.DatetimeIndex([pd.Timestamp(d) + t for d in ds for t in SLOTS_5M]).tz_localize("Asia/Kolkata")
    close = 20000 * np.exp(np.cumsum(rng.normal(0, 0.0012, len(stamps))))
    opn = np.r_[20000, close[:-1]] * np.exp(rng.normal(0, 0.0003, len(stamps)))
    hi = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.0004, len(stamps))))
    lo = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.0004, len(stamps))))
    return pd.DataFrame({"open": opn, "high": hi, "low": lo, "close": close}, index=stamps)


def at(s: Series, ts: str) -> int:
    return int(np.flatnonzero(s.ts == pd.Timestamp(ts).tz_localize("Asia/Kolkata"))[0])


# --- noise band -----------------------------------------------------------------------

def noise_days():
    """15 quiet days whose 09:40-10:10 bars each close 10 points (0.05%) off
    the open, so the band at those times is 0.05%; then a test day."""
    ds = days(16)
    path = {}
    for d in ds[:15]:
        for clock in ("09:40", "10:10", "10:40", "11:10"):
            path[(d, clock)] = (20000, 20011, 19999, 20010)
    return ds, path


def test_noise_band_buys_the_call_on_the_first_half_hourly_close_above_the_band():
    ds, path = noise_days()
    d = ds[15]
    path[(d, "09:40")] = (20000, 20006, 19999, 20005)   # inside: 20000 x 1.0005 = 20010
    path[(d, "10:10")] = (20000, 20021, 19999, 20020)   # 10:15 close above -> buy the call
    path[(d, "10:20")] = (20020, 20021, 19990, 20000)   # back inside at 10:25: not a check time
    path[(d, "10:40")] = (20020, 20031, 20019, 20030)   # still above at 10:45
    path[(d, "11:10")] = (20030, 20031, 20004, 20005)   # inside at 11:15 -> out
    s = Series(bars(ds, path))
    trades = [t for t in npl.noise_band(s, {}) if t["entry_ts"].startswith(d)]
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == 1 and t["entry_i"] == at(s, f"{d} 10:10") and t["entry"] == 20020
    assert t["exit_i"] == at(s, f"{d} 11:10") and t["reason"] == "back inside"


def test_noise_band_anchors_on_the_previous_close_when_it_is_higher_and_trades_once():
    ds, path = noise_days()
    d = ds[15]
    path[(d, "10:10")] = (20000, 20021, 19999, 20020)   # above 20000 x 1.0005, not above 20015 x 1.0005
    path[(d, "10:40")] = (20000, 20041, 19999, 20040)   # above 20025.0 -> the call
    path[(d, "11:10")] = (20000, 20001, 19960, 19970)   # below the lower band: no second trade
    s = Series(bars(ds, path))
    trades = [t for t in npl.noise_band(s, {pd.Timestamp(ds[14]).date(): 20015.0}) if t["entry_ts"].startswith(d)]
    assert [(t["side"], t["entry_i"]) for t in trades] == [(1, at(s, f"{d} 10:40"))]
    assert trades[0]["reason"] == "back inside" and trades[0]["exit_i"] == at(s, f"{d} 11:10")


@pytest.mark.parametrize("missing, trades", [(4, 1), (5, 0)])
def test_noise_band_needs_the_bar_in_ten_of_the_last_fourteen_sessions(missing, trades):
    ds, path = noise_days()
    d = ds[15]
    path[(d, "10:10")] = (20000, 20021, 19999, 20020)   # a break at 10:15
    df = bars(ds, path)
    gone = [pd.Timestamp(f"{x} 10:10").tz_localize("Asia/Kolkata") for x in ds[1:1 + missing]]
    s = Series(df.drop(gone))
    assert len([t for t in npl.noise_band(s, {}) if t["entry_ts"].startswith(d)]) == trades


def test_noise_band_waits_for_fourteen_prior_sessions():
    ds, path = noise_days()
    path[(ds[13], "10:10")] = (20000, 20041, 19999, 20040)
    assert npl.noise_band(Series(bars(ds[:14], path)), {}) == []


def test_noise_band_holds_to_15_25_when_price_never_returns():
    ds, path = noise_days()
    d = ds[15]
    for clock in SLOTS_5M[5:]:
        hhmm = f"{clock.components.hours:02d}:{clock.components.minutes:02d}"
        path[(d, hhmm)] = (19950, 19951, 19949, 19950)   # below the lower band all day
    s = Series(bars(ds, path))
    t = [t for t in npl.noise_band(s, {}) if t["entry_ts"].startswith(d)][0]
    assert t["side"] == -1 and t["reason"] == "time" and t["exit_i"] == at(s, f"{d} 15:20")


# --- last half hour and the 5-minute opening range -------------------------------------

def test_last_half_hour_takes_its_side_from_the_first_half_hour_and_trades_15_00_to_15_25():
    ds = days(3)
    path = {(ds[1], "09:40"): (20000, 20031, 19999, 20030), (ds[2], "09:40"): (20000, 20001, 19969, 19970)}
    s = Series(bars(ds, path))
    trades = npl.last_half_hour(s, {})
    assert [t["side"] for t in trades] == [1, -1]
    for t, d in zip(trades, ds[1:]):
        assert t["entry_ts"] == f"{d}T14:55:00+05:30" and t["exit_ts"] == f"{d}T15:20:00+05:30"


def test_last_half_hour_measures_from_the_official_previous_close():
    ds = days(2)
    s = Series(bars(ds, {(ds[1], "09:40"): (20000, 20011, 19999, 20010)}))
    assert npl.last_half_hour(s, {pd.Timestamp(ds[0]).date(): 20050.0})[0]["side"] == -1


def test_opening_range_stops_at_the_first_candles_far_side():
    ds = days(2)
    path = {(ds[0], "09:15"): (20000, 20012, 19990, 20010),     # green: call at 20010, stop 19990
            (ds[0], "11:00"): (20000, 20001, 19985, 19995),     # touches the stop
            (ds[1], "09:15"): (20000, 20001, 19999, 20000)}     # unchanged: no trade
    s = Series(bars(ds, path))
    trades = npl.opening_range_5m(s)
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == 1 and t["entry"] == 20010 and t["exit"] == 19990 and t["reason"] == "stop"
    assert t["exit_ts"] == f"{ds[0]}T11:00:00+05:30"


def test_opening_range_holds_to_15_25_without_a_stop():
    ds = days(1)
    s = Series(bars(ds, {(ds[0], "09:15"): (20010, 20012, 19990, 19995)}))   # red: put, stop 20012
    t = npl.opening_range_5m(s)[0]
    assert t["side"] == -1 and t["reason"] == "time" and t["exit_ts"] == f"{ds[0]}T15:20:00+05:30"


RULES = {"noise_band": lambda s: npl.noise_band(s, {}), "last_half_hour": lambda s: npl.last_half_hour(s, {}),
         "opening_range_5m": npl.opening_range_5m}


@pytest.mark.parametrize("name", sorted(RULES))
def test_no_rule_uses_a_bar_after_its_entry(name):
    """Scramble every bar after an entry: the entry, and every trade before
    it, must come out the same."""
    rule = RULES[name]
    df = walk(22, seed=7)
    full = rule(Series(df))
    assert len(full) >= 3
    rng = np.random.default_rng(11)
    for t in full[:: max(1, len(full) // 4)]:
        cut = t["entry_i"] + 1
        scrambled = df.copy()
        scale = np.exp(rng.normal(0, 0.01, len(df) - cut))[:, None]
        scrambled.iloc[cut:] = scrambled.iloc[cut:].to_numpy() * scale
        again = rule(Series(scrambled))
        before = lambda rows: [(u["entry_ts"], u["side"]) for u in rows if u["entry_i"] < t["entry_i"]]  # noqa: E731
        assert before(again) == before(full)
        assert any(u["entry_ts"] == t["entry_ts"] and u["side"] == t["side"] and u["entry"] == t["entry"]
                   for u in again)


# --- daily straddles on made-up option rows ---------------------------------------------

def row(close, oi=5000, contracts=10):
    return {"close": close, "open_interest": oi, "contracts": contracts}


class FakeArchive:
    def __init__(self, by_day: dict, iv: dict | None = None):
        self.by_day, self.iv = by_day, iv or {}

    def day(self, d):
        return self.by_day.get(d, {})


def test_straddle_takes_the_nearest_strike_both_legs_trade_on_an_expiry_after_the_exit():
    rows = {("2025-01-02", 20000, "CE"): row(100), ("2025-01-02", 20000, "PE"): row(100),   # expires on the exit day
            ("2025-01-09", 20000, "CE"): row(150), ("2025-01-09", 20000, "PE"): row(140, oi=10),  # put too thin
            ("2025-01-09", 20050, "CE"): row(120), ("2025-01-09", 20050, "PE"): row(170),
            ("2025-01-09", 19900, "CE"): row(210), ("2025-01-09", 19900, "PE"): row(90)}
    out = {("2025-01-09", 20050, "CE"): row(130), ("2025-01-09", 20050, "PE"): row(180)}
    a = FakeArchive({"2025-01-01": rows, "2025-01-02": out})
    t = npl.straddle(a, "2025-01-01", "2025-01-02", 20010.0)
    assert (t["expiry"], t["strike"], t["premium_in"], t["premium_out"]) == ("2025-01-09", 20050, 290, 310)
    c = npl.COSTS
    lot = npl.LOT_SIZE
    costs = (c.buy_cost_rs(120, lot, "2025-01-01") + c.buy_cost_rs(170, lot, "2025-01-01")
             + c.sell_cost_rs(130, lot, "2025-01-02") + c.sell_cost_rs(180, lot, "2025-01-02"))
    assert t["option_pct"] == round(100 * (20 * lot - costs) / (290 * lot), 3)


def test_straddle_is_skipped_when_a_leg_has_no_exit_price():
    rows = {("2025-01-09", 20000, "CE"): row(150), ("2025-01-09", 20000, "PE"): row(140)}
    a = FakeArchive({"2025-01-01": rows, "2025-01-02": {("2025-01-09", 20000, "CE"): row(160)}})
    assert npl.straddle(a, "2025-01-01", "2025-01-02", 20000.0) is None


def chain(level=100.0):
    return {("2030-01-01", 20000, "CE"): row(level), ("2030-01-01", 20000, "PE"): row(level)}


def test_event_straddle_buys_the_close_before_each_event_and_splits_the_rest_into_the_baseline():
    sessions = ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06"]
    a = FakeArchive({d: chain(100 + k) for k, d in enumerate(sessions)})
    trades, base = npl.event_straddle(a, sessions, {d: 20000.0 for d in sessions})
    assert [(t["entry"], t["exit"]) for t in trades] == [("2024-06-03", "2024-06-04")]
    assert [(t["entry"], t["exit"]) for t in base] == [("2024-06-04", "2024-06-05"), ("2024-06-05", "2024-06-06")]


def test_realised_vol_is_the_annualised_stdev_of_21_log_returns():
    closes = [100 * math.exp(0.01 * ((-1) ** k)) for k in range(22)]
    r = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    assert npl.realised_vol(closes) == pytest.approx(np.std(r, ddof=1) * math.sqrt(252))
    assert npl.realised_vol(closes[:21]) is None


def test_cheap_vol_enters_the_close_after_the_signal_and_holds_one_at_a_time():
    sessions = [d.date().isoformat() for d in pd.bdate_range("2025-01-01", periods=40)]
    rng = np.random.default_rng(3)
    spot = dict(zip(sessions, 20000 * np.exp(np.cumsum(rng.normal(0, 0.01, 40)))))
    rv = npl.trailing_rv(spot)
    signal_day = sessions[22]
    iv = {d: (rv[d] / 2 if d in (signal_day, sessions[23]) else rv[d] * 2) for d in sessions if d in rv}
    a = FakeArchive({d: chain() for d in sessions})
    trades, base = npl.cheap_vol_straddle(a, sessions, spot, iv)
    assert [(t["signal_day"], t["entry"], t["exit"]) for t in trades] == [(signal_day, sessions[23], sessions[28])]
    assert trades[0]["iv"] < trades[0]["rv"]                  # the signal day's IV, not the entry day's
    assert all(t["signal_day"] not in (signal_day, sessions[23]) for t in base)


def test_a_rule_that_loses_in_either_period_is_rejected():
    dev = [{"entry": "2020-01-01", "exit": "2020-01-02", "option_pct": v} for v in (5.0, -1.0, 4.0)]
    hold = [{"entry": "2025-01-01", "exit": "2025-01-02", "option_pct": -2.0 + 0.1 * k} for k in range(20)]
    base = [{"entry": e, "exit": x, "option_pct": -3.0 + 0.01 * k} for k, (e, x) in
            enumerate([("2020-02-01", "2020-02-02")] * 5 + [("2025-02-01", "2025-02-02")] * 5)]
    v = npl.judge_daily(dev + hold, base)
    assert v["verdict"] == "REJECTED" and v["development"]["num_trades"] == 3 and v["holdout"]["num_trades"] == 20
    assert v["holdout"]["baseline_n"] == 5
