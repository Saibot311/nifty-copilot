"""Phase 9 persistence: verdicts must survive as history, not just exist
for the duration of one API response."""

from storage.strategy_status_db import history, latest_status, playbook, record_evaluation


def _fake_evaluation(strategy="test_strategy", status="CONDITIONAL", expectancy=0.5):
    return {
        "strategy": strategy,
        "label": strategy.replace("_", " ").title(),
        "final_status": status,
        "final_reason": "test reason",
        "walk_forward": {"folds_with_positive_expectancy": 3, "folds_with_any_trades": 5},
        "holdout": {
            "holdout": {"metrics": {"num_trades": 20, "expectancy_pct": expectancy, "profit_factor": 1.2}}
        },
    }


def test_record_and_retrieve_latest_status(tmp_path):
    db = tmp_path / "test.db"
    record_evaluation(_fake_evaluation(), params={"hold_days": 10}, db_path=db)

    latest = latest_status("test_strategy", db_path=db)
    assert latest is not None
    assert latest["status"] == "CONDITIONAL"
    assert latest["expectancy_pct"] == 0.5


def test_history_returns_most_recent_first(tmp_path):
    db = tmp_path / "test.db"
    record_evaluation(_fake_evaluation(status="REJECTED", expectancy=-0.5), params={}, db_path=db)
    record_evaluation(_fake_evaluation(status="CONDITIONAL", expectancy=0.5), params={}, db_path=db)

    rows = history("test_strategy", db_path=db)
    assert len(rows) == 2
    assert rows[0]["status"] == "CONDITIONAL"  # most recent write comes first
    assert rows[1]["status"] == "REJECTED"


def test_playbook_shows_only_latest_per_strategy(tmp_path):
    db = tmp_path / "test.db"
    record_evaluation(_fake_evaluation("strategy_a", "REJECTED", -1.0), params={}, db_path=db)
    record_evaluation(_fake_evaluation("strategy_a", "CONDITIONAL", 0.5), params={}, db_path=db)
    record_evaluation(_fake_evaluation("strategy_b", "APPROVED", 1.5), params={}, db_path=db)

    board = playbook(db_path=db)
    strategies = {row["strategy"]: row for row in board}
    assert len(strategies) == 2
    assert strategies["strategy_a"]["status"] == "CONDITIONAL"  # latest, not the first write


def test_unknown_strategy_has_no_status(tmp_path):
    db = tmp_path / "test.db"
    assert latest_status("never_evaluated", db_path=db) is None
    assert history("never_evaluated", db_path=db) == []
