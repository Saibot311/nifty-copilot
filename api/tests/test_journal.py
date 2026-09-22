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
    e = {"decision": "TOOK", "entry_premium": 100.0, "exit_premium": 130.0, "quantity": 65}
    p = journal.pnl(e)
    assert p["gross_rs"] == 1950
    assert p["costs_rs"] == round(journal.COST_FRACTION * 100 * 65)
    assert p["net_rs"] == p["gross_rs"] - p["costs_rs"]


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
