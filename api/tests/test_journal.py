"""Phase 13, the trade journal. What must hold: profit is computed, never
typed; costs are the backtests' own; the system's verdict is looked up, not
restated by the user; and "followed" means what it says."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import briefing.journal as journal
import main
from storage import journal_db


@pytest.fixture(autouse=True)
def tmp_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(journal_db, "DB_PATH", tmp_path / "journal.db")
    monkeypatch.setattr(journal, "all_recommendations", lambda: [
        {"as_of": "2026-09-18", "action": "NO_TRADE"}, {"as_of": "2026-09-21", "action": "CONSIDER_CALL"}])
    monkeypatch.setattr(main, "system_action_for", journal.system_action_for)


def test_profit_is_computed_after_the_backtests_cost_model():
    from backtest.options_engine import OptionsCostModel
    e = {"decision": "TOOK", "trade_date": "2026-03-31", "exit_date": "2026-04-01",
         "entry_premium": 100.0, "exit_premium": 130.0, "quantity": 65}
    p = journal.pnl(e)
    assert p["gross_rs"] == 1950
    # Each leg on its own premium and day: the buy on 100 under the old STT,
    # the sale on 130 under the Finance Act 2026's.
    m = OptionsCostModel()
    assert p["costs_rs"] == round(m.buy_cost_rs(100, 65, "2026-03-31") + m.sell_cost_rs(130, 65, "2026-04-01"))
    assert p["net_rs"] == p["gross_rs"] - p["costs_rs"]


def test_a_small_ticket_pays_the_flat_brokerage_in_full():
    """A lot of a Rs 6.80 option is a Rs 442 ticket; Rs 20 an order each way,
    with GST, is over a tenth of it before anything else."""
    e = {"decision": "TOOK", "trade_date": "2026-09-23", "exit_date": "2026-09-25",
         "entry_premium": 6.8, "exit_premium": 6.8, "quantity": 65}
    assert journal.pnl(e)["costs_rs"] >= 2 * 20 * 1.18


def test_a_trade_closed_without_an_exit_date_is_sold_on_its_own_session():
    e = {"decision": "TOOK", "trade_date": "2026-09-23", "entry_premium": 100.0, "exit_premium": 130.0,
         "quantity": 65}
    assert journal.pnl(e) == journal.pnl({**e, "exit_date": "2026-09-23"})


def test_the_note_states_the_rates_it_charged():
    note = journal.report()["note"]
    assert "₹20 an order" in note and "0.15% STT" in note


def test_an_open_or_skipped_entry_has_no_profit():
    assert journal.pnl({"decision": "TOOK", "entry_premium": 100.0, "exit_premium": None, "quantity": 65}) is None
    assert journal.pnl({"decision": "SKIPPED"}) is None


@pytest.mark.parametrize("system,decision,opt,expected", [
    ("NO_TRADE", "SKIPPED", None, True), ("NO_TRADE", "WAITED", None, True), ("NO_TRADE", "TOOK", "CE", False),
    ("CONSIDER_CALL", "TOOK", "CE", True), ("CONSIDER_CALL", "TOOK", "PE", False),
    ("CONSIDER_CALL", "SKIPPED", None, False), (None, "TOOK", "CE", None)])
def test_followed_means_matching_the_verdict(system, decision, opt, expected):
    assert journal.followed({"system_action": system, "decision": decision, "option_type": opt}) is expected


def _add(**kw):
    return main.journal_add(main.JournalEntry(**kw))


def test_the_api_looks_up_the_verdict_rather_than_trusting_the_user():
    # "system_action" is not a field the user can send; it is looked up.
    assert "system_action" not in main.JournalEntry.model_fields
    _add(trade_date="2026-09-18", decision="SKIPPED")
    rows = main.journal()["entries"]
    assert rows[0]["system_action"] == "NO_TRADE" and rows[0]["followed_system"] is True


def test_a_taken_trade_needs_its_details_and_can_be_closed():
    with pytest.raises(HTTPException) as e:
        _add(trade_date="2026-09-21", decision="TOOK")
    assert e.value.status_code == 422
    entry_id = _add(trade_date="2026-09-21", decision="TOOK", underlying="NIFTY", option_type="CE", strike=23400,
                    expiry="2026-09-29", quantity=65, entry_premium=120)["id"]
    main.journal_close(entry_id, main.JournalClose(exit_premium=150, exit_date="2026-09-23"))
    s = main.journal()["summary"]
    assert s["closed_trades"] == 1 and s["followed_system"]["trades"] == 1 and s["net_rs"] > 0


def test_bad_input_is_refused():
    with pytest.raises(ValidationError):
        main.JournalEntry(trade_date="yesterday", decision="SKIPPED")
    with pytest.raises(ValidationError):
        main.JournalEntry(trade_date="2026-09-18", decision="SOLD")
    with pytest.raises(ValidationError):
        main.JournalEntry(trade_date="2026-09-18", decision="TOOK", quantity=-5)
    with pytest.raises(HTTPException):
        main.journal_close(999, main.JournalClose(exit_premium=1, exit_date="2026-09-23"))


def test_a_decision_logged_before_the_evening_verdict_is_matched_up_later(monkeypatch):
    # Logged at 13:00; the forward log writes that session's verdict at 19:30.
    # The row must not stay blank once the verdict exists.
    monkeypatch.setattr(journal, "all_recommendations", lambda: [])
    _add(trade_date="2026-09-23", decision="SKIPPED")
    assert main.journal()["entries"][0]["system_action"] is None

    monkeypatch.setattr(journal, "all_recommendations",
                        lambda: [{"as_of": "2026-09-23", "action": "NO_TRADE"}])
    row = main.journal()["entries"][0]
    assert row["system_action"] == "NO_TRADE" and row["followed_system"] is True


def test_a_closed_trade_cannot_be_closed_again_over_its_exit():
    """The API answers "No open trade with that id" — but the store closed
    any TOOK row, so a repeated or mistaken close silently replaced the exit
    price of a trade that was already finished."""
    entry_id = journal_db.add({"trade_date": "2026-09-23", "decision": "TOOK", "underlying": "NIFTY",
                               "option_type": "CE", "strike": 23900.0, "expiry": "2026-09-29", "quantity": 65,
                               "entry_premium": 6.8, "system_action": "NO_TRADE"})
    assert journal_db.close(entry_id, 9.5, "2026-09-25") is True
    assert journal_db.close(entry_id, 0.5, "2026-09-26") is False
    row = [e for e in journal_db.all_entries() if e["id"] == entry_id][0]
    assert row["exit_premium"] == 9.5 and row["exit_date"] == "2026-09-25"


# --- open positions: the facts to decide an exit on, and the user's own plan ----

from datetime import datetime  # noqa: E402

from backtest.options_engine import OptionsCostModel  # noqa: E402
from market_data.kite_session import IST  # noqa: E402

TRADE = {"id": 7, "decision": "TOOK", "trade_date": "2026-09-28", "underlying": "NIFTY", "option_type": "CE",
         "strike": 23000.0, "expiry": "2026-10-06", "quantity": 65, "entry_premium": 100.0,
         "stop_premium": None, "target_premium": None}
NOON = datetime(2026, 9, 30, 12, 0, tzinfo=IST)


def test_an_old_journal_gains_the_plan_columns_with_every_row_kept(tmp_path):
    """journal.db cannot be rebuilt: the new columns are added, never a new table."""
    import sqlite3
    path = tmp_path / "old.db"
    old_schema = journal_db.SCHEMA
    conn = sqlite3.connect(path)
    conn.executescript(old_schema)
    conn.execute("INSERT INTO journal (created_at, trade_date, decision) VALUES ('x', '2026-09-22', 'SKIPPED')")
    conn.commit(); conn.close()
    rows = journal_db.all_entries(path)
    assert len(rows) == 1 and rows[0]["trade_date"] == "2026-09-22"
    assert {"stop_premium", "target_premium", "exit_kind"} <= set(rows[0])


def test_a_sale_after_expiry_or_before_the_buy_is_refused():
    """28 Sep 2026: a contract expiring on the 29th was recorded as sold on the 30th."""
    entry_id = _add(trade_date="2026-09-28", decision="TOOK", underlying="NIFTY", option_type="PE", strike=22400,
                    expiry="2026-09-29", quantity=65, entry_premium=6.1)["id"]
    for day in ("2026-09-30", "2026-09-27"):
        with pytest.raises(HTTPException) as e:
            main.journal_close(entry_id, main.JournalClose(exit_premium=0.8, exit_date=day))
        assert e.value.status_code == 422
    main.journal_close(entry_id, main.JournalClose(exit_premium=0.8, exit_date="2026-09-29"))  # expiry day is fine


def test_an_expiry_before_the_session_is_refused():
    with pytest.raises(HTTPException) as e:
        _add(trade_date="2026-09-28", decision="TOOK", underlying="NIFTY", option_type="CE", strike=23000,
             expiry="2026-09-22", quantity=65, entry_premium=10)
    assert e.value.status_code == 422


def test_a_trade_held_to_expiry_settles_at_the_index_close_and_pays_exercise_stt_not_a_sale(monkeypatch):
    monkeypatch.setattr(journal, "index_close", lambda underlying, on: 23062.5)
    entry_id = _add(trade_date="2026-01-02", decision="TOOK", underlying="NIFTY", option_type="CE", strike=23000,
                    expiry="2026-01-06", quantity=65, entry_premium=40)["id"]
    out = main.journal_settle(entry_id)
    assert out == {"ok": True, "exit_premium": 62.5, "exit_date": "2026-01-06"}
    row = [e for e in main.journal()["entries"] if e["id"] == entry_id][0]
    m = OptionsCostModel()
    exercise = 62.5 * 65 * 0.00125          # 0.125% of intrinsic value until 2026-03-31
    assert row["exit_kind"] == "settled"
    assert row["pnl"]["costs_rs"] == round(m.buy_cost_rs(40, 65, "2026-01-02") + exercise)


def test_settlement_is_refused_before_expiry_and_when_the_close_is_missing(monkeypatch):
    with pytest.raises(ValueError):
        journal.settlement(TRADE, NOON)
    monkeypatch.setattr(journal, "index_close", lambda underlying, on: None)
    with pytest.raises(LookupError):
        journal.settlement(TRADE, datetime(2026, 10, 6, 16, 0, tzinfo=IST))


def test_the_position_now_is_worked_out_from_the_price_and_the_index():
    p = journal.position_now(TRADE, 120.0, 23050.0, NOON, "Kite", "2026-09-30T12:00+05:30")
    m = OptionsCostModel()
    buy = m.buy_cost_rs(100, 65, "2026-09-28")
    assert p["pnl_now"]["net_rs"] == round(20 * 65 - buy - m.sell_cost_rs(120, 65, "2026-09-30"))
    assert p["intrinsic"] == 50 and p["time_value"] == 70
    assert p["if_unchanged_at_expiry"]["net_rs"] == round((50 - 100) * 65 - buy - 50 * 65 * 0.0015)
    assert p["breakeven_index"] == round(23000 + 100 + buy / 65, 2)
    assert 0 < p["decay_per_day_rs"] < 70 * 65                  # a day's decay, less than all the time value
    assert 3 < p["implied_vol_pct"] < 60
    assert p["days_to_expiry"] == 6 and not p["expired"] and not p["expires_today"]


def test_consider_exiting_appears_only_against_the_users_own_stop_or_target():
    words = " ".join(journal.position_now(TRADE, 120.0, 23050.0, NOON)["lines"]).lower()
    assert "consider" not in words
    for banned in ("should", "recommend", "sell now", "buy now", "you must"):
        assert banned not in words
    stopped = journal.position_now({**TRADE, "stop_premium": 90.0, "target_premium": 200.0}, 85.0, 23000.0, NOON)
    assert stopped["plan"]["state"] == "stop" and stopped["lines"][0].startswith("Consider exiting")
    hit = journal.position_now({**TRADE, "stop_premium": 90.0, "target_premium": 200.0}, 210.0, 23150.0, NOON)
    assert hit["plan"]["state"] == "target"


def test_expiry_day_and_after_are_said_as_they_are():
    today = journal.position_now(TRADE, 60.0, 23050.0, datetime(2026, 10, 6, 11, 0, tzinfo=IST))
    assert today["expires_today"] and any("expires today" in s for s in today["lines"])
    after = journal.position_now(TRADE, None, None, datetime(2026, 10, 7, 9, 0, tzinfo=IST))
    assert after["expired"] and any("expired" in s for s in after["lines"])


def test_the_plan_is_only_for_open_trades_and_the_stop_sits_below_the_target():
    entry_id = _add(trade_date="2026-09-28", decision="TOOK", underlying="NIFTY", option_type="CE", strike=23000,
                    expiry="2026-10-06", quantity=65, entry_premium=100)["id"]
    with pytest.raises(HTTPException):
        main.journal_plan(entry_id, main.JournalPlan(stop_premium=150, target_premium=120))
    main.journal_plan(entry_id, main.JournalPlan(stop_premium=80, target_premium=150))
    assert journal_db.get(entry_id)["stop_premium"] == 80
    main.journal_close(entry_id, main.JournalClose(exit_premium=130, exit_date="2026-09-30"))
    with pytest.raises(HTTPException) as e:
        main.journal_plan(entry_id, main.JournalPlan(stop_premium=90))
    assert e.value.status_code == 404


def test_following_counts_decisions_so_staying_out_is_not_hidden():
    _add(trade_date="2026-09-18", decision="SKIPPED")                        # followed NO_TRADE: made Rs 0
    entry_id = _add(trade_date="2026-09-18", decision="TOOK", underlying="NIFTY", option_type="PE", strike=22400,
                    expiry="2026-09-29", quantity=65, entry_premium=6.1)["id"]
    main.journal_close(entry_id, main.JournalClose(exit_premium=2.0, exit_date="2026-09-23"))
    s = main.journal()["summary"]
    assert s["followed_system"] == {"decisions": 1, "trades": 0, "net_rs": 0, "avg_rs": None}
    assert s["overrode_system"]["decisions"] == 1 and s["overrode_system"]["trades"] == 1


def test_a_trade_says_how_many_lots_it_was():
    _add(trade_date="2026-09-23", decision="TOOK", underlying="NIFTY", option_type="CE", strike=23900,
         expiry="2026-09-29", quantity=195, entry_premium=3.3)
    row = main.journal()["entries"][0]
    assert row["lot_size"] == 65 and row["lots"] == 3


def test_without_kite_an_open_trade_is_priced_at_its_last_close_with_the_index_at_that_close(monkeypatch):
    monkeypatch.setattr(journal, "archive_mark", lambda e: (41.5, "2026-09-29"))
    asked = []
    monkeypatch.setattr(journal, "index_close", lambda underlying, on: asked.append(on) or 22800.0)
    _add(trade_date="2026-09-28", decision="TOOK", underlying="NIFTY", option_type="PE", strike=22800,
         expiry="2026-10-06", quantity=65, entry_premium=60)
    p = journal.report(live=None, now=NOON)["entries"][0]["position"]
    assert p["mark"] == 41.5 and p["mark_source"] == "close of 2026-09-29" and asked == ["2026-09-29"]


def test_the_tick_prices_journal_trades_on_the_same_single_kite_call(monkeypatch):
    import briefing.paper as paper
    import market_data.kite_quotes as kq
    entry_id = _add(trade_date="2026-09-28", decision="TOOK", underlying="NIFTY", option_type="CE", strike=23000,
                    expiry="2026-10-06", quantity=65, entry_premium=100)["id"]
    calls = []
    monkeypatch.setattr(paper.paper_db, "open_trades", lambda: [])
    monkeypatch.setattr(paper, "cash_and_equity", lambda marks=None: {})
    monkeypatch.setattr(kq, "option_tokens", lambda contracts: {c["id"]: 111 for c in contracts})

    def ltp(tokens, index="NSE:NIFTY 50", extra=()):
        calls.append((tuple(tokens), extra))
        return {"index": 23050.0, "by_key": {}, "by_token": {111: 120.0}, "source": "Kite", "quote_at": "t"}
    monkeypatch.setattr(kq, "last_prices", ltp)
    live = paper.live_marks()["journal_live"]
    assert len(calls) == 1 and live["marks"] == {entry_id: 120.0} and live["spots"]["NIFTY"] == 23050.0
    assert journal.positions(live, NOON)[str(entry_id)]["pnl_now"]["gross_rs"] == 1300


def test_without_the_index_close_the_level_comes_from_the_same_sessions_option_prices(tmp_path, monkeypatch):
    """29 Sep 2026: the network was down at the evening job, so neither Kite's
    daily bars nor NSE's index report had the 29th's close. That day's option
    file had it, by put-call parity."""
    import sqlite3
    db = tmp_path / "nifty_options.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE option_bars (trade_date TEXT, expiry_date TEXT, strike REAL, option_type TEXT, "
                 "close REAL, contracts REAL)")
    rows = [("2026-09-29", "2026-10-06", 22700.0, "CE", 90.0, 10), ("2026-09-29", "2026-10-06", 22700.0, "PE", 111.5, 10),
            ("2026-09-29", "2026-10-06", 22600.0, "CE", 150.0, 10), ("2026-09-29", "2026-10-06", 22600.0, "PE", 70.0, 10)]
    conn.executemany("INSERT INTO option_bars VALUES (?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()
    monkeypatch.setattr(journal, "_DATA", tmp_path)
    e = {**TRADE, "option_type": "PE", "strike": 22700.0}
    assert journal.archive_forward(e, "2026-09-29") == 22678.5          # 22700 + 90 - 111.5, the closest pair
