"""The market context engine. The ways it could mislead are look-ahead in
the attribution, a volatility measure that uses the future in its "now"
reading, a positioning parser that misreads NSE's file, and an unusual-
activity flag with an unfair baseline."""

import math

import numpy as np
import pandas as pd
import pytest

from market_engine import drivers, expiry, positioning
from market_engine.knowledge import KNOWLEDGE
from market_engine.who_wins import _realised
from storage.participant_oi_db import COLUMNS, parse


# --- why it moved -------------------------------------------------------------

def test_a_global_cue_is_the_session_that_closed_before_india_opened():
    # The US closes after India does. The S&P session dated the same day had
    # not happened yet, so using it would be look-ahead.
    us = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-09-16", "2026-09-17", "2026-09-18"]))
    india = pd.DatetimeIndex(pd.to_datetime(["2026-09-17", "2026-09-18", "2026-09-21"]))
    assert drivers.prior_session(us, india).tolist() == [1.0, 2.0, 3.0]


def test_no_prior_session_means_no_cue():
    us = pd.Series([1.0], index=pd.to_datetime(["2026-09-18"]))
    assert math.isnan(drivers.prior_session(us, pd.DatetimeIndex(pd.to_datetime(["2026-09-18"]))).iloc[0])


def _frame(n=300, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n)
    f = pd.DataFrame({k: rng.normal(0, 1, n) for k in drivers.FACTORS}, index=idx)
    ret = 0.4 * f["sp500"] - 0.2 * f["usdinr"] + rng.normal(0, 0.5, n)
    nifty = pd.DataFrame({"close": 100.0, "return_pct": ret, "gap_pct": ret / 2, "intraday_pct": ret / 2}, index=idx)
    return drivers.Frame(nifty, f)


def test_the_betas_for_a_day_never_see_that_day():
    fr = _frame()
    a = drivers.attribute(fr)
    fr.nifty.iloc[-1, fr.nifty.columns.get_loc("return_pct")] = 50.0  # an absurd move today
    b = drivers.attribute(fr)
    assert a["factors"]["sp500"]["beta"] == b["factors"]["sp500"]["beta"]
    assert b["unexplained_pct"] == pytest.approx(50.0 - b["explained_by_global_pct"], abs=0.01)


def test_the_fitted_relationship_is_recovered():
    a = drivers.attribute(_frame(n=600))
    assert a["factors"]["sp500"]["beta"] == pytest.approx(0.4, abs=0.08)
    assert a["factors"]["usdinr"]["beta"] == pytest.approx(-0.2, abs=0.08)


# --- who wins -----------------------------------------------------------------

def test_realised_vol_is_annualised_root_mean_square():
    # A steady 1% daily move, up or down, is 1% x sqrt(252) a year.
    assert _realised(np.array([0.01, -0.01] * 10)) == pytest.approx(100 * 0.01 * math.sqrt(252))


# --- positioning ----------------------------------------------------------------

NSE_FILE = ('""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Sep 18, 2026"",,,,,,,,,,,,,,\n'
            'Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short\t,Option Index Call Long,'
            'Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,'
            'Option Stock Call Short,Option Stock Put Short,Total Long Contracts      ,Total Short Contracts\n'
            'Client,300,50,1,1,1000,900,950,1000,1,1,1,1,1,1\n'
            'DII,40,30,1,1,5,50,1,1,1,1,1,1,1,1\n'
            'FII,50,340,1,1,700,1300,950,650,1,1,1,1,1,1\n'
            'Pro,60,30,1,1,1100,1200,904,1799,1,1,1,1,1,1\n'
            'TOTAL,450,450,4,4,2805,3450,2805,3450,4,4,4,4,4,4\n')


def test_nses_file_is_parsed_whatever_its_whitespace():
    # Headers carry stray tabs and trailing spaces that vary by year.
    rows = {r["participant"]: r for r in parse(NSE_FILE)}
    assert set(rows) == {"Client", "DII", "FII", "Pro"}  # TOTAL is not a participant
    assert rows["FII"]["fut_idx_short"] == 340 and rows["Client"]["opt_idx_put_short"] == 1000
    assert all(len(r) == 1 + len(COLUMNS) for r in rows.values())


def test_longs_equal_shorts_across_participants():
    day = {r["participant"]: r for r in parse(NSE_FILE)}
    gaps = positioning.zero_sum_check(day)
    assert gaps["fut_idx"] == 0
    assert all(abs(g) <= positioning.ZERO_SUM_TOLERANCE for g in gaps.values())


# --- expiry and unusual activity ----------------------------------------------

def test_a_reversal_needs_a_real_morning_move_undone_by_the_afternoon():
    assert expiry._sharp_reversal({"morning_pct": 0.8, "afternoon_pct": -0.6})
    assert not expiry._sharp_reversal({"morning_pct": 0.8, "afternoon_pct": -0.2})   # barely undone
    assert not expiry._sharp_reversal({"morning_pct": 0.1, "afternoon_pct": -0.1})   # no real move
    assert not expiry._sharp_reversal({"morning_pct": 0.8, "afternoon_pct": 0.5})    # continued


def test_pin_distance_is_to_the_nearest_fifty_point_strike():
    assert expiry._pin_distance(23347.0) == 3.0
    assert expiry._pin_distance(23372.0) == 22.0
    assert expiry._pin_distance(23400.0) == 0.0


def test_shares_are_of_the_days_volume_so_lot_size_changes_cancel(tmp_path):
    import sqlite3
    db = tmp_path / "o.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, contracts REAL)")
    rows = [("2026-09-21", "2026-09-22", k, t, v) for k, t, v in
            [(23400, "PE", 300), (23500, "CE", 100), (23400, "CE", 100)]]
    c.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?)", rows)
    shares = expiry._shares(c, "2026-09-21", "2026-09-22", 23450.0)
    assert sum(shares.values()) == pytest.approx(1.0)
    # Doubling every count (a lot-size change) changes nothing.
    c.execute("UPDATE option_bars SET contracts = contracts * 2")
    assert expiry._shares(c, "2026-09-21", "2026-09-22", 23450.0) == shares


# --- knowledge ------------------------------------------------------------------

def test_every_principle_has_a_source_and_says_what_it_means_for_you():
    for k in KNOWLEDGE:
        assert k["sources"], k["id"]
        assert k["for_you"] and k["principle"], k["id"]
    assert len({k["id"] for k in KNOWLEDGE}) == len(KNOWLEDGE)


def test_nothing_in_the_knowledge_base_tells_you_to_trade():
    # It explains; it does not advise. "buy"/"sell" appear only as descriptions.
    for k in KNOWLEDGE:
        text = (k["principle"] + " " + k["for_you"]).lower()
        for phrase in ("you should buy", "you should sell", "buy now", "sell now", "guaranteed"):
            assert phrase not in text, (k["id"], phrase)
