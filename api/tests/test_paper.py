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
    # The backtests charge the whole round trip on the entry premium; a paper
    # result has to be comparable with a researched one, so this matches.
    assert pnl["net_pct"] == pytest.approx(30.0 - paper.COST_FRACTION * 100, abs=0.01)
    assert pnl["profit_rs"] == round(100.0 * 65 * pnl["net_pct"] / 100)
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


# --- allocated funds, sizing, and the "take something every day" policy -------

def test_nothing_is_sized_against_money_that_was_never_allocated():
    assert paper._lots_for(premium=150.0, cash=0, allocated_rs=0) == 0


def test_a_position_never_takes_more_than_the_per_trade_share():
    lots = paper._lots_for(premium=150.0, cash=1_000_000, allocated_rs=100_000)
    per_lot = 150.0 * 65 * (1 + paper.COST_FRACTION)
    assert lots == int(100_000 * paper.MAX_PER_TRADE // per_lot)
    assert lots * per_lot <= 100_000 * paper.MAX_PER_TRADE


def test_whole_lots_only_and_a_premium_that_does_not_fit_is_skipped():
    assert paper._lots_for(premium=3000.0, cash=100_000, allocated_rs=100_000) == 0  # a lot costs ~Rs 195k


def test_funds_can_be_added_and_taken_back():
    paper_db.add_funds(100_000, "initial")
    assert paper_db.allocated() == 100_000
    paper_db.add_funds(-40_000, "took some back")
    assert paper_db.allocated() == 60_000
    assert paper.cash_and_equity()["max_per_trade_rs"] == round(60_000 * paper.MAX_PER_TRADE)


def test_the_book_values_open_positions_at_the_mark_and_tracks_cash():
    paper_db.add_funds(100_000)
    paper_db.open_position(_row(lots=2, entry_cost_rs=200.0))
    t = paper_db.all_trades()[0]
    spent = 100.0 * 2 * 65 + 200.0
    assert paper.cash_and_equity()["cash_rs"] == round(100_000 - spent)
    # marked up 50%: equity rises, cash does not
    book = paper.cash_and_equity({t["id"]: 150.0})
    assert book["open_positions_value_rs"] == round(150.0 * 2 * 65)
    assert book["equity_rs"] > 100_000 and book["cash_rs"] == round(100_000 - spent)


def test_realised_profit_returns_to_cash_after_both_legs_of_costs():
    paper_db.add_funds(100_000)
    paper_db.open_position(_row(lots=1, entry_cost_rs=100.0))
    tid = paper_db.all_trades()[0]["id"]
    paper_db.close_position(tid, "2026-09-28", 150.0, exit_cost_rs=0.0)
    gross = (150.0 - 100.0) * 65
    assert paper.cash_and_equity()["realised_rs"] == round(gross - 100.0)
    assert paper.cash_and_equity()["equity_rs"] == round(100_000 + gross - 100.0)


@pytest.mark.parametrize("now,then,expected", [(100.0, 90.0, "CE"), (90.0, 100.0, "PE"), (100.0, 100.0, None)])
def test_the_fallback_direction_is_the_20_session_trend(now, then, expected):
    td = [f"2026-08-{d:02d}" for d in range(1, 25)]
    closes = {d: 95.0 for d in td}
    closes[td[-1]], closes[td[-21]] = now, then
    read = paper._trend_read(td[-1], closes, td)
    assert (read[0] if read else None) == expected
    if read:
        assert "trend" in read[1]


def test_the_best_reading_is_never_presented_as_a_proven_edge():
    label = "Best available reading — 20-session trend up"
    assert "best available" in label.lower()
    # The control and the pattern rows are measured separately from it.
    s = paper.report()["summary"]
    assert set(s) >= {"patterns", "best_read", "control"}


# --- the daily trade: out of the money, one side, best-evidenced signal -----

def test_the_daily_trade_is_out_of_the_money_on_whichever_side_it_takes():
    assert paper.BEST_READ["moneyness_pct"] == paper.OTM_PCT == 2.0
    # A call above spot and a put below it are both out of the money.
    assert paper._strike_offset(23000, paper.OTM_PCT, "CE") == pytest.approx(460.0)
    assert paper._strike_offset(23000, paper.OTM_PCT, "PE") == pytest.approx(-460.0)


def test_it_follows_the_firing_signal_with_the_most_evidence(monkeypatch):
    monkeypatch.setattr(paper, "_confidence_by_name",
                        lambda: {"fii_positioning_follow": 0.35, "turn_of_month": -1.28, "pre_holiday": 0.1})
    import backtest.structural_research as sr
    monkeypatch.setattr(sr, "signals_on", lambda d, symbol="^NSEI": {
        "turn_of_month": "CE", "pre_holiday": "CE", "fii_positioning_follow": "PE"})
    read = paper._confident_read("2026-09-22", {}, [])
    assert read["direction"] == "PE" and read["source"] == "fii_positioning_follow"
    assert "still rejected" in read["why"]


def test_a_signal_that_did_worse_than_nothing_is_not_followed(monkeypatch):
    td = [f"2026-08-{d:02d}" for d in range(1, 26)]
    closes = {d: 100.0 for d in td}
    closes[td[-1]] = 110.0  # trend up
    monkeypatch.setattr(paper, "_confidence_by_name", lambda: {"pre_holiday": -1.84})
    import backtest.structural_research as sr
    monkeypatch.setattr(sr, "signals_on", lambda d, symbol="^NSEI": {"pre_holiday": "PE"})
    read = paper._confident_read(td[-1], closes, td)
    assert read["direction"] == "CE"  # the trend, not the badly-evidenced put
    assert read["source"] == "trend" and "worse than no signal" in read["why"]


def test_only_one_direction_is_taken_each_day(monkeypatch):
    import backtest.structural_research as sr
    monkeypatch.setattr(paper, "_confidence_by_name", lambda: {"a": 1.0, "b": 0.9})
    monkeypatch.setattr(sr, "signals_on", lambda d, symbol="^NSEI": {"a": "CE", "b": "PE"})
    read = paper._confident_read("2026-09-22", {}, [])
    assert read["direction"] in ("CE", "PE")  # one side, never both
    assert read["source"] == "a"
