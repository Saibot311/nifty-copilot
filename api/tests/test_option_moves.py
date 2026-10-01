"""What a move does to option prices: the model must reproduce today's price
before it moves anything, and the measured slope must be read from the
snapshots of one session only."""

import sqlite3
from datetime import date, datetime

import pytest

import options.move_table as mt
from briefing.journal import black76
from market_data.kite_session import IST

NOW = datetime(2026, 10, 2, 11, 0, tzinfo=IST)
YEARS = mt.years_to(date(2026, 10, 6), NOW)


def test_the_model_reproduces_the_price_now_and_moves_the_right_way():
    c = mt.leg({"bid": 155.0, "ask": 157.0, "ltp": 156.5}, "CE", 22400.0, 22421.95, YEARS)
    assert c["price"] == 156.0 and c["basis"] == "mid"
    iv = c["iv"] / 100
    assert black76(22421.95, 22400.0, YEARS, iv, "CE") == pytest.approx(156.0, abs=0.05)
    assert c["up"]["50"] > 0 > c["down"]["50"] and c["up"]["100"] > c["up"]["50"]
    assert c["up"]["50"] > -c["down"]["50"]                 # convexity: a buyer gains more up than loses down
    assert 0.45 < c["delta"] < 0.6


def test_a_call_and_a_put_at_one_strike_have_deltas_a_point_apart():
    c = mt.leg({"bid": 155.0, "ask": 157.0}, "CE", 22400.0, 22421.95, YEARS)
    p = mt.leg({"bid": 133.0, "ask": 135.0}, "PE", 22400.0, 22421.95, YEARS)
    assert c["delta"] - p["delta"] == pytest.approx(1.0, abs=0.06)
    assert p["up"]["50"] < 0 < p["down"]["50"]


def test_a_price_at_intrinsic_has_no_model_rather_than_an_invented_one():
    c = mt.leg({"ltp": 421.0}, "CE", 22000.0, 22421.95, YEARS)
    assert c["iv"] is None and c["up"] == {} and c["basis"] == "last"
    assert mt.leg(None, "CE", 22000.0, 22421.95, YEARS) is None


def test_the_slope_is_premium_points_per_index_point():
    assert mt.slope([(22000 + 10 * k, 100 + 5.0 * k) for k in range(8)]) == 0.5
    assert mt.slope([(22000, 100)] * 3) is None


def test_measured_reads_the_latest_session_of_that_expiry_only(tmp_path):
    db = tmp_path / "snaps.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE snapshots (taken_at TEXT, expiry TEXT, strike REAL, option_type TEXT, spot REAL, ltp REAL)")
    rows = [(f"2026-10-01T10:{k:02d}:00", "2026-10-06", 22400.0, "CE", 22400 + 10 * k, 150 + 3.0 * k) for k in range(8)]
    rows += [(f"2026-10-02T10:{k:02d}:00", "2026-10-06", 22400.0, "CE", 22400 + 10 * k, 150 + 6.0 * k) for k in range(8)]
    rows += [(f"2026-10-02T10:{k:02d}:00", "2026-10-13", 22400.0, "CE", 22400 + 10 * k, 150 + 9.0 * k) for k in range(8)]
    conn.executemany("INSERT INTO snapshots VALUES (?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()
    out = mt.measured(date(2026, 10, 6), [22400.0], db)
    assert out["session"] == "2026-10-02" and out["slopes"] == {"22400CE": 0.6}


def test_the_default_expiry_is_the_nearest_not_expiring_today():
    listed = ["06-Oct-2026", "13-Oct-2026"]
    assert mt.nearest_tradable(listed, date(2026, 10, 2)) == "06-Oct-2026"
    assert mt.nearest_tradable(listed, date(2026, 10, 6)) == "13-Oct-2026"


def test_the_table_is_eight_strikes_either_side_of_the_money():
    rows = [{"strike": 22000.0 + 50 * k, "is_atm": k == 10, "call": {"bid": 100.0, "ask": 101.0},
             "put": {"bid": 90.0, "ask": 91.0}} for k in range(25)]
    chain = {"underlying_value": 22500.0, "expiry": "06-Oct-2026", "rows": rows, "as_of": "x",
             "expiries": ["06-Oct-2026"], "days_to_expiry": 4}
    out = mt.build_move_table(chain, NOW, db_path=__import__("pathlib").Path("/nonexistent.db"))
    assert [r["strike"] for r in out["rows"]] == [22100.0 + 50 * k for k in range(17)]
    assert out["moves"] == [25, 50, 100, 200]
