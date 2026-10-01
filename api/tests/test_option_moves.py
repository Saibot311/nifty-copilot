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


# --- time: a market clock, NSE's holidays, decay to each horizon ----------------------

HOL = {date(2026, 10, 2)}          # Gandhi Jayanti, a Friday


def test_a_session_counts_one_unit_and_a_closed_gap_its_measured_share():
    at_close = datetime(2026, 9, 29, 15, 30, tzinfo=IST)               # Tuesday close
    one_night = mt.years_to(date(2026, 9, 30), at_close, HOL) * mt.UNITS_PER_YEAR
    assert one_night == pytest.approx(mt.GAP_WEIGHT[1] + 1.0)
    # Thursday close -> Monday close over the Friday holiday and the weekend: one gap of 4 days, one session
    long_break = mt.years_to(date(2026, 10, 5), datetime(2026, 10, 1, 15, 30, tzinfo=IST), HOL) * mt.UNITS_PER_YEAR
    assert long_break == pytest.approx(mt.GAP_WEIGHT[4] + 1.0)


def test_inside_a_session_only_the_rest_of_it_counts():
    noon = datetime(2026, 9, 30, 12, 22, 30, tzinfo=IST)               # half of 09:15-15:30
    assert mt.years_to(date(2026, 9, 30), noon) * mt.UNITS_PER_YEAR == pytest.approx(0.5)
    assert mt.years_to(date(2026, 9, 30), datetime(2026, 9, 30, 15, 31, tzinfo=IST)) == 0.0


def test_horizons_skip_nse_holidays_and_stop_at_expiry():
    hz = mt.horizons(datetime(2026, 10, 2, 3, 0, tzinfo=IST), date(2026, 10, 6), HOL)
    assert [h["key"] for h in hz] == ["now", "2026-10-05", "2026-10-06"]
    assert hz[-1]["label"] == "By 6 Oct close (expiry)"
    hz = mt.horizons(datetime(2026, 9, 30, 11, 0, tzinfo=IST), date(2026, 10, 1), HOL)
    assert [h["key"] for h in hz] == ["now", "today", "2026-10-01"]


def test_waiting_costs_a_buyer_and_at_expiry_only_intrinsic_value_is_left():
    now = datetime(2026, 10, 2, 3, 0, tzinfo=IST)
    hz = mt.horizons(now, date(2026, 10, 6), HOL)
    years = mt.years_to(date(2026, 10, 6), now, HOL)
    c = mt.leg({"bid": 156.0, "ask": 157.0}, "CE", 22400.0, 22452.0, years, hz, date(2026, 10, 6), HOL)
    assert c["at"]["now"]["flat"] == pytest.approx(0, abs=0.01)
    assert c["at"]["2026-10-05"]["flat"] < 0
    assert c["at"]["2026-10-05"]["up"]["50"] < c["up"]["50"]                   # the same move, a day later, is worth less
    assert c["at"]["2026-10-06"]["flat"] == pytest.approx(52.0 - 156.5)       # intrinsic at expiry minus the price paid


def test_options_are_valued_against_the_put_call_parity_forward():
    row = {"strike": 22400.0, "call": {"bid": 156.0, "ask": 157.0}, "put": {"bid": 103.5, "ask": 104.5}}
    assert mt.forward_from(row, 22421.95) == (22452.5, "put-call parity at the money")
    assert mt.forward_from({"strike": 22400.0, "call": None, "put": {"ltp": 9}}, 22421.95)[0] == 22421.95


def test_live_reprices_each_contract_at_the_index_now_with_the_decay_since():
    rows = [{"strike": 22400.0, "is_atm": True, "call": {"bid": 156.0, "ask": 157.0}, "put": {"bid": 103.5, "ask": 104.5}}]
    chain = {"underlying_value": 22421.95, "expiry": "06-Oct-2026", "rows": rows, "as_of": "01-Oct-2026 15:40:00",
             "expiries": ["06-Oct-2026"], "days_to_expiry": 4}
    built = datetime(2026, 10, 5, 9, 30, tzinfo=IST)
    table = mt.build_move_table(chain, built, db_path=__import__("pathlib").Path("/nonexistent.db"), holidays=HOL)
    same = mt.live_estimate(table, 22421.95, built, HOL)
    assert same["move"] == 0 and same["rows"][0]["call"]["change"] == pytest.approx(0, abs=0.05)
    up = mt.live_estimate(table, 22471.95, built, HOL)
    assert up["rows"][0]["call"]["change"] == pytest.approx(table["rows"][0]["call"]["up"]["50"], abs=0.05)
    later = mt.live_estimate(table, 22471.95, datetime(2026, 10, 5, 14, 30, tzinfo=IST), HOL)
    assert later["rows"][0]["call"]["change"] < up["rows"][0]["call"]["change"]          # five hours of decay paid
    assert mt.live_estimate(None, 22000.0, built) is None
