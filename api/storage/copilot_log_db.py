"""Every copilot answer, and what the guards made of it.

Until now a review was computed, used once to decide whether to show the
answer, and thrown away with the response. So nobody could say how often a
guard fires, on what, or whether a wording change helped — the 42 labelled
cases in scripts/check_guards.py were all synthetic, written by the same
hand that wrote the questions.

This is the copilot's version of the forward log: a record made at the time,
before anyone knows whether it was right. It is what turns "the guard seems
fine" into something with a track record, and every flagged answer here is a
candidate labelled case.

Unlike the forward log, rows may be deleted — they contain the questions the
user typed, and it is their machine. Nothing here feeds a verdict.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "copilot_log.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS copilot_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at   TEXT NOT NULL,
    as_of_close   TEXT,
    kind          TEXT NOT NULL,   -- explain | ask
    method        TEXT NOT NULL DEFAULT 'gemini',  -- gemini | composed
    question      TEXT NOT NULL,
    route         TEXT,
    drafts        INTEGER NOT NULL,
    outcome       TEXT NOT NULL,   -- shown | withheld | declined | shadow
    reason        TEXT,
    bad_numbers_json  TEXT NOT NULL DEFAULT '[]',
    unsupported_json  TEXT NOT NULL DEFAULT '[]',
    scores_json       TEXT NOT NULL DEFAULT '{}',
    grades_json       TEXT NOT NULL DEFAULT '{}',
    answer        TEXT
);
CREATE INDEX IF NOT EXISTS copilot_log_time ON copilot_log (recorded_at);
"""

# Order matters: these are splatted into the INSERT in this order.
_JSON_COLUMNS = {"bad_numbers": "bad_numbers_json", "unsupported": "unsupported_json",
                 "scores": "scores_json", "grades": "grades_json"}
_DEFAULTS: dict = {"bad_numbers": [], "unsupported": [], "scores": {}, "grades": {}}


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS leaves an existing table alone, so a new
    column has to be added by hand. Rows written before the deterministic
    explainer existed were all from the model."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(copilot_log)")}
    if "method" not in have:
        conn.execute("ALTER TABLE copilot_log ADD COLUMN method TEXT NOT NULL DEFAULT 'gemini'")


def record(entry: dict, db_path: Path | None = None) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO copilot_log
               (recorded_at, as_of_close, kind, method, question, route, drafts, outcome, reason,
                bad_numbers_json, unsupported_json, scores_json, grades_json, answer)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                entry.get("as_of_close"), entry["kind"], entry.get("method", "gemini"),
                entry["question"], entry.get("route"),
                int(entry.get("drafts", 1)), entry["outcome"], entry.get("reason"),
                *(json.dumps(entry.get(k) or _DEFAULTS[k]) for k in _JSON_COLUMNS),
                entry.get("answer"),
            ),
        )
        return int(cur.lastrowid or 0)


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    for key, col in _JSON_COLUMNS.items():
        d[key] = json.loads(d.pop(col))
    return d


def recent(limit: int = 50, db_path: Path | None = None) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM copilot_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def summary(db_path: Path | None = None) -> dict:
    rows = recent(limit=10_000, db_path=db_path)
    if not rows:
        return {"answers": 0, "note": "No copilot answers recorded yet."}

    shown = [r for r in rows if r["outcome"] == "shown"]
    graded = [r for r in shown if r["grades"]]
    withheld = [r for r in rows if r["outcome"] == "withheld"]

    def mean(vals):
        return round(sum(vals) / len(vals), 2) if vals else None

    def grades_for(method: str) -> dict | None:
        # Shadow rows count here and nowhere else: the comparison is the
        # whole reason the deterministic explainer runs.
        got = [r for r in rows if r["method"] == method and r["grades"]]
        if not got:
            return None
        return {"answers": len(got),
                **{k: mean([r["grades"][k] for r in got if k in r["grades"]]) for k in ("honesty", "clarity")}}

    return {
        "answers": len(rows),
        "first": rows[-1]["recorded_at"][:10],
        "shown": len(shown),
        "withheld": len(withheld),
        "declined_off_topic": sum(1 for r in rows if r["outcome"] == "declined"),
        "needed_a_retry": sum(1 for r in shown if r["drafts"] > 1),
        "withheld_reasons": _counts(r["reason"] for r in withheld),
        "by_route": _counts(r["route"] for r in rows if r["route"]),
        "grades": {k: mean([r["grades"][k] for r in graded if k in r["grades"]])
                   for k in ("honesty", "clarity")} if graded else None,
        # Gemini writes one, Python composes another, the same judge grades
        # both. Whether to drop the model is decided on this, not on taste.
        "grades_by_method": {m: grades_for(m) for m in ("gemini", "composed")},
        "shadow_runs": sum(1 for r in rows if r["outcome"] == "shadow"),
        # Should always be zero. The composed explanation is built from the
        # same data the guards check against, so a block means a template
        # says something the data does not support, or a guard is wrong.
        "composed_blocked": sum(1 for r in rows if r["method"] == "composed" and r["reason"]),
        # The point of keeping this: real answers a guard objected to are
        # worth more as labelled cases than any I could invent.
        "flagged_for_review": [
            {"at": r["recorded_at"][:16], "question": r["question"][:80],
             "reason": r["reason"], "unsupported": [u.get("claim") for u in r["unsupported"]]}
            for r in withheld[:20]
        ],
        "note": (
            "A record of what the guards did, made at the time. Withheld answers are the useful ones: "
            "each is a candidate case for scripts/check_guards.py, where the wording is tuned."
        ),
    }


def _counts(values) -> dict:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
