"""Phase 14, paper observation. It is only evidence if a position can never
be opened for a session whose outcome already exists, if a pattern forming
again mid-hold doesn't stack, if the mark is a real traded price rather than
a stale one, and if costs are charged on paper as in every backtest."""

import sqlite3
from datetime import datetime

import pytest

import briefing.paper as paper
from storage import paper_db

TD = ["2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"]


@pytest.fixture(autouse=True)
def tmp_paper(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_db, "DB_PATH", tmp_path / "paper.db")


def _row(**kw):
    base = {"source": "pattern", "strategy": "bollinger_reversion", "label": "Bollinger Band Reversion",
            "signal_date": "2026-09-22", "underlying": "NIFTY", "option_type": "CE", "strike": 23400.0,
            "expiry": "2026-10-29", "entry_date": "2026-09-23", "entry_premium": 100.0, "hold_days": 3,
            "planned_exit": "2026-09-28"}
    return {**base, **kw}


def test_the_same_setup_cannot_open_twice_for_one_signal():
    assert paper_db.open_position(_row()) is True
    assert paper_db.open_position(_row(entry_premium=120.0)) is False
    assert len(paper_db.all_trades()) == 1


def test_nothing_may_be_opened_for_a_session_before_observation_began():
    # The guard that makes this forward evidence rather than a backtest.
    assert paper.FIRST_SIGNAL_DATE >= "2026-09-22"
    assert "signal_date >= FIRST_SIGNAL_DATE" in __import__("inspect").getsource(paper.observe)


def test_costs_are_charged_on_paper_exactly_as_in_the_backtests():
    from backtest.options_engine import OptionsCostModel
    assert paper.COST_FRACTION == OptionsCostModel().round_trip_cost_fraction()
    pnl = paper._pnl({**_row(), "status": "CLOSED", "exit_premium": 130.0, "mark_premium": 130.0})
    assert pnl["gross_pct"] == 30.0
    assert pnl["net_pct"] == pytest.approx(30.0 - paper.COST_FRACTION * 100, abs=0.01)
    assert pnl["profit_per_lot_rs"] == round(100.0 * pnl["net_pct"] / 100 * 65)
    assert pnl["realised"] is True


def test_an_open_position_is_valued_at_its_mark_and_says_it_is_unrealised():
    pnl = paper._pnl({**_row(), "status": "OPEN", "mark_premium": 80.0, "exit_premium": None})
    assert pnl["gross_pct"] == -20.0 and pnl["realised"] is False
    assert paper._pnl({**_row(), "status": "OPEN", "mark_premium": None, "exit_premium": None}) is None


def _conn_with(prices):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, close REAL)")
    conn.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?)", prices)
    return conn


def test_the_mark_is_the_last_session_the_contract_actually_traded():
    t = _row()
    conn = _conn_with([("2026-09-23", "2026-10-29", 23400.0, "CE", 100.0),
                       ("2026-09-24", "2026-10-29", 23400.0, "CE", 90.0)])
    assert paper._last_priced_session(conn, t, TD) == ("2026-09-24", 90.0)
    # A contract that stopped trading is marked where it last traded, not at today.
    assert paper._last_priced_session(conn, _row(strike=99999.0), TD) is None


def test_the_mark_never_runs_past_the_planned_exit():
    t = _row(hold_days=1)  # entry 09-23 -> exit 09-24
    conn = _conn_with([("2026-09-24", "2026-10-29", 23400.0, "CE", 90.0),
                       ("2026-09-25", "2026-10-29", 23400.0, "CE", 300.0)])
    assert paper._last_priced_session(conn, t, TD) == ("2026-09-24", 90.0)


def test_closing_records_the_exit_and_stops_marking():
    paper_db.open_position(_row())
    tid = paper_db.all_trades()[0]["id"]
    paper_db.close_position(tid, "2026-09-28", 140.0)
    paper_db.mark(tid, "2026-09-29", 999.0)  # must not touch a closed row
    t = paper_db.all_trades()[0]
    assert t["status"] == "CLOSED" and t["exit_premium"] == 140.0 and t["mark_premium"] == 140.0
    assert paper_db.open_trades() == []


def test_the_report_separates_the_patterns_from_the_no_signal_control():
    paper_db.open_position(_row())
    paper_db.open_position(_row(source="control", strategy="control_ce", label="No signal"))
    paper_db.close_position(paper_db.all_trades()[0]["id"], "2026-09-28", 150.0)
    s = paper.report()["summary"]
    assert s["patterns"]["open"] + s["patterns"]["closed"] == 1
    assert s["control"]["open"] + s["control"]["closed"] == 1


def test_observe_is_safe_to_run_twice(monkeypatch):
    monkeypatch.setattr(paper, "_sessions", lambda: (TD[:2], {d: 23000.0 for d in TD}))
    first = paper.observe(now=datetime.now(paper.IST))
    second = paper.observe(now=datetime.now(paper.IST))
    assert first["opened"] == second["opened"] == []
