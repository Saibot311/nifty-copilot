"""The check before buying an option. What must hold: the exit is the moment
the reader picked, never past the expiry; the charges are the rate card's;
the break-even move is the smallest move that gets back what was paid with
both legs' charges and the spread at the exit time; the history is measured
from the same time of day (or a close) over exactly the window; and every
line describes, none advises."""

import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import briefing.precheck as pc
from backtest.options_engine import OptionsCostModel
from briefing.journal import black76
from market_data.kite_session import IST

HOL: set = set()
TUE = datetime(2026, 10, 6, 10, 0, tzinfo=IST)
EXP = date(2026, 10, 13)


def at(d, h, m):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


def test_the_exit_is_the_moment_picked_and_never_past_expiry():
    assert pc.exit_time("30m", TUE, EXP, HOL) == at(TUE, 10, 30)
    assert pc.exit_time("close", TUE, EXP, HOL) == at(TUE, 15, 30)
    assert pc.exit_time("1s", TUE, EXP, HOL) == at(date(2026, 10, 7), 15, 30)
    assert pc.exit_time("expiry", TUE, EXP, HOL) == at(EXP, 15, 30)
    assert pc.exit_time("5s", TUE, date(2026, 10, 8), HOL) == at(date(2026, 10, 8), 15, 30)  # capped
    assert pc.exit_time("60m", at(TUE, 15, 0), EXP, HOL) == at(TUE, 15, 30)               # the session ends first
    evening = at(TUE, 17, 0)                                                              # after the close: next session
    assert pc.exit_time("30m", evening, EXP, HOL) == at(date(2026, 10, 7), 9, 45)
    assert pc.exit_time("close", evening, EXP, HOL) == at(date(2026, 10, 7), 15, 30)


def _econ(premium=100.0, bid=99.0, ask=100.0, window="close", strike=22700.0, kind="CE", lots=1, forward=22700.0):
    return pc.economics(kind, strike, EXP, premium, bid, ask, lots, forward, TUE,
                        pc.exit_time(window, TUE, EXP, HOL), HOL, OptionsCostModel(premium_slippage_pct=0.0))


def test_the_charges_are_the_rate_cards():
    e = _econ()
    c = OptionsCostModel(premium_slippage_pct=0.0)
    q = 65
    assert e["quantity"] == q and e["paid_rs"] == pytest.approx(100 * q + c.buy_cost_rs(100, q, TUE.date()), abs=0.01)
    assert e["charges_rs"] == pytest.approx(c.buy_cost_rs(100, q, TUE.date()) + c.sell_cost_rs(100, q, TUE.date()), abs=0.01)
    assert e["charges_pct"] == pytest.approx(e["charges_rs"] / (100 * q) * 100, abs=0.05)
    assert e["sell_now_rs"] == pytest.approx(99 * q - c.sell_cost_rs(99, q, TUE.date()) - e["paid_rs"], abs=0.01)


def test_the_break_even_move_gets_back_exactly_what_was_paid():
    e = _econ()
    m = e["breakeven_pts"]
    assert m > 0
    assert pc.net_at(e, m) == pytest.approx(0.0, abs=1.0)                 # rupees, on a lot
    assert pc.net_at(e, m - 2) < 0 < pc.net_at(e, m + 2)
    assert e["flat_rs"] < 0 and e["flat_rs"] > e["paid_rs"] * -1           # waiting costs decay, not everything


def test_a_put_needs_the_index_to_fall():
    e = _econ(kind="PE")
    assert pc.net_at(e, e["breakeven_pts"] + 5) > 0 and e["direction"] == "down"


def test_at_expiry_the_break_even_is_the_strike_plus_what_it_cost():
    e = _econ(window="expiry", premium=50.0, bid=49.0, ask=50.0, strike=22800.0)
    q = 65
    c = OptionsCostModel(premium_slippage_pct=0.0)
    # sold at the bid: the intrinsic value less half the spread must cover the price and both legs' charges
    need = 22800 + 0.5 + 50 + (c.buy_cost_rs(50, q, TUE.date()) + c.sell_cost_rs(50.5, q, EXP)) / q
    assert 22700 + e["breakeven_pts"] == pytest.approx(need, abs=0.1)


def _bars(day, closes, spread=1.0):
    idx = pd.DatetimeIndex([at(day, 9, 15) + timedelta(minutes=5 * i) for i in range(len(closes))])
    c = np.array(closes, float)
    return pd.DataFrame({"open": c, "high": c + spread, "low": c - spread, "close": c}, index=idx)


def test_intraday_history_starts_at_the_same_time_of_day_and_spans_the_window():
    day = date(2025, 1, 6)
    closes = [100.0] * 9 + [100, 101, 102, 103, 104, 105, 106] + [100.0] * 60   # 09:15 + 9 bars = 10:00 start
    b = _bars(day, closes)
    touch, end = pc.intraday_moves(b, start=at(TUE, 10, 0), minutes=30, direction="up")
    # the last bar closed by 10:00 is the 09:55 bar (close 100); the next six run 10:00-10:30
    assert touch[0] == pytest.approx(105 + 1 - 100)                            # % of 100: points here
    assert end[0] == pytest.approx(105 - 100)
    down_touch, _ = pc.intraday_moves(b, start=at(TUE, 10, 0), minutes=30, direction="down")
    assert down_touch[0] == pytest.approx(1.0)                                 # only the 1-pt wick below


def test_session_history_runs_from_a_close_over_n_sessions():
    days = pd.DatetimeIndex([pd.Timestamp(date(2025, 1, 1) + timedelta(days=i)) for i in range(5)])
    d = pd.DataFrame({"open": 100.0, "high": [100, 104, 103, 110, 101], "low": [99, 98, 95, 99, 90],
                      "close": [100, 102, 97, 105, 100]}, index=days)
    touch, end = pc.session_moves(d, 2, "up")
    assert touch[0] == pytest.approx(4.0) and end[0] == pytest.approx(-3.0)   # from 100: highs 104, 103; close 97
    dt, de = pc.session_moves(d, 2, "down")
    assert dt[0] == pytest.approx(5.0) and de[0] == pytest.approx(3.0)
    assert len(touch) == 3                                                     # the last two closes have no 2 sessions after


def test_the_share_is_counted_at_todays_price():
    touch = np.array([0.1, 0.2, 0.3, 0.4])                                     # % moves
    assert pc.share(touch, 50.0, 25000.0) == 75.0                              # 25, 50, 75, 100 pts at 25,000


def test_the_check_describes_and_never_advises():
    e = _econ(premium=3.0, bid=2.5, ask=3.0, strike=23900.0)
    flags = pc.flags(e, touch=5.0, end=2.0, forecast={"target_day": "2026-10-06", "sigma_pts": 100.0},
                     window="close", spot=22700.0)
    keys = {f["key"] for f in flags if f["tone"] == "warn"}
    assert {"charges", "spread", "breakeven", "history"} <= keys
    assert "−63%" in " ".join(f["text"] for f in flags) or "%)" in " ".join(f["text"] for f in flags)
    words = " ".join(f["text"] for f in flags).lower()
    assert not re.search(r"\b(should|avoid|recommend|don't buy|do not buy|must)\b", words)


def test_the_api_serves_the_check():
    import main
    assert any(getattr(r, "path", "") == "/api/precheck" for r in main.app.routes)
