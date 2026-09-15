"""Phase 9: a real Strategy Playbook — persistent history of every
validation verdict, not a live recomputation that overwrites itself on
every page load.

Same pattern as options_db.py (SQLite, a plain module-level connect()).
Before this, evaluate_strategy()'s output only ever existed for the
duration of one API response; nothing recorded what a strategy's status
was yesterday to compare against today. That's the actual gap Phase 9
was supposed to close.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "strategy_status.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_status_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy      TEXT NOT NULL,
    label         TEXT NOT NULL,
    checked_at    TEXT NOT NULL,
    status        TEXT NOT NULL,
    reason        TEXT NOT NULL,
    num_trades    INTEGER,
    expectancy_pct REAL,
    profit_factor REAL,
    folds_positive INTEGER,
    folds_total    INTEGER,
    params_json   TEXT NOT NULL,
    full_result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_status_strategy ON strategy_status_history(strategy);
CREATE INDEX IF NOT EXISTS idx_strategy_status_checked_at ON strategy_status_history(checked_at);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def record_evaluation(evaluation: dict, params: dict, db_path: Path | None = None) -> int:
    """Persists one evaluate_strategy() result as a permanent row. Returns
    the new row's id."""
    init_db(db_path)
    wf = evaluation.get("walk_forward", {})
    ho = evaluation.get("holdout", {})
    holdout_metrics = ho.get("holdout", {}).get("metrics", {})

    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO strategy_status_history
               (strategy, label, checked_at, status, reason, num_trades, expectancy_pct,
                profit_factor, folds_positive, folds_total, params_json, full_result_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                evaluation["strategy"],
                evaluation.get("label", evaluation["strategy"]),
                datetime.now(timezone.utc).isoformat(),
                evaluation["final_status"],
                evaluation["final_reason"],
                holdout_metrics.get("num_trades"),
                holdout_metrics.get("expectancy_pct"),
                holdout_metrics.get("profit_factor"),
                wf.get("folds_with_positive_expectancy"),
                wf.get("folds_with_any_trades"),
                json.dumps(params),
                json.dumps(evaluation, default=str),
            ),
        )
        return cur.lastrowid


def latest_status(strategy: str, db_path: Path | None = None) -> dict | None:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM strategy_status_history WHERE strategy = ?
               ORDER BY checked_at DESC LIMIT 1""",
            (strategy,),
        ).fetchone()
        return dict(row) if row else None


def history(strategy: str, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, strategy, label, checked_at, status, reason, num_trades,
                      expectancy_pct, profit_factor, folds_positive, folds_total
               FROM strategy_status_history WHERE strategy = ?
               ORDER BY checked_at DESC LIMIT ?""",
            (strategy, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def playbook(db_path: Path | None = None) -> list[dict]:
    """The latest known status for every strategy that has ever been
    evaluated — the actual Strategy Playbook view."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT h.* FROM strategy_status_history h
               INNER JOIN (
                   SELECT strategy, MAX(checked_at) AS max_checked_at
                   FROM strategy_status_history GROUP BY strategy
               ) latest ON h.strategy = latest.strategy AND h.checked_at = latest.max_checked_at
               ORDER BY h.expectancy_pct DESC"""
        ).fetchall()
        return [
            {k: v for k, v in dict(r).items() if k != "full_result_json"}
            for r in rows
        ]
