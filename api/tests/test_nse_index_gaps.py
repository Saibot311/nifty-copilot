"""A download that fails has to be retried, and a hole has to be seen.

On 22 Sep 2026 the one-off backfill of NSE's all-index report lost its
network for about a minute. Name resolution failed instantly, so the loop
logged FAILED and raced on through six months of dates — 2025-09-22 to
2026-03-11, 117 sessions — and finished with "done: 2191 days saved". The
failed days were rightly left unrecorded, but only a full rerun would have
asked for them again; the nightly job looks back ten days. The replication
read BANKNIFTY and Midcap Select from that archive for five nights before
anyone noticed.
"""

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import pytest

import storage.nse_index_db as ndb
from audit import FAIL, PASS, WARN
from audit.checks_data import judge_index_coverage
from market_data.nse_indices import IndexDay

spec = importlib.util.spec_from_file_location(
    "backfill_nse_indices", Path(__file__).parent.parent / "scripts" / "backfill_nse_indices.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)


def _weekdays(first: str, last: str) -> list[str]:
    d, end, out = date.fromisoformat(first), date.fromisoformat(last), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


SESSIONS = _weekdays("2025-08-01", "2026-04-30")
HOLE = [d for d in SESSIONS if "2025-09-22" <= d <= "2026-03-11"]


def _rows(day: str, close: float = 100.0) -> list[IndexDay]:
    return [IndexDay("Nifty 50", day, close, close, close, close),
            IndexDay("India VIX", day, 12.0, 12.0, 12.0, 12.0)]


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "nse_indices.db"
    monkeypatch.setattr(ndb, "DB_PATH", path)
    for d in SESSIONS:
        if d not in HOLE:
            ndb.save_day(d, _rows(d), path)
    return path


def _table(path: Path) -> list[tuple]:
    with ndb.connect(path) as conn:
        return [tuple(r) for r in conn.execute("SELECT * FROM index_daily ORDER BY index_name, trade_date")]


def test_the_archive_names_every_session_it_is_missing(db):
    assert ndb.sessions_missing(set(SESSIONS), "2025-08-01", db) == HOLE
    assert ndb.sessions_missing(set(SESSIONS), "2026-03-12", db) == []


def test_fill_gaps_asks_for_exactly_the_missing_sessions_and_leaves_the_rest(db, monkeypatch, capsys):
    before = _table(db)
    asked = []
    monkeypatch.setattr(bf, "index_trading_days", lambda: (set(SESSIONS), SESSIONS[-1]))
    monkeypatch.setattr(bf, "fetch_day", lambda day: asked.append(day.isoformat()) or _rows(day.isoformat(), 5.0))
    monkeypatch.setattr("sys.argv", ["backfill_nse_indices.py", "--fill-gaps", "--delay", "0"])
    assert bf.main() == 0
    assert asked == HOLE
    after = _table(db)
    assert [r for r in after if r[1] not in HOLE] == before  # nothing that was there is rewritten
    assert len(after) == 2 * len(SESSIONS)
    assert ndb.sessions_missing(set(SESSIONS), "2025-08-01", db) == []
    assert f"{len(HOLE)} days saved; 0 sessions failed" in capsys.readouterr().out


def test_a_failed_session_is_counted_not_hidden(db, monkeypatch, capsys):
    def offline(day):
        raise ConnectionError("Failed to resolve 'archives.nseindia.com'")
    monkeypatch.setattr(bf, "index_trading_days", lambda: (set(SESSIONS), SESSIONS[-1]))
    monkeypatch.setattr(bf, "fetch_day", offline)
    monkeypatch.setattr("sys.argv", ["backfill_nse_indices.py", "--fill-gaps", "--delay", "0"])
    assert bf.main() == 0  # old sessions: retried every night, not an alarm every night
    out = capsys.readouterr().out
    assert f"0 days saved; {len(HOLE)} sessions failed" in out
    assert "--fill-gaps" in out.splitlines()[-1]
    assert ndb.sessions_missing(set(SESSIONS), "2025-08-01", db) == HOLE


def test_a_recent_session_that_fails_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(ndb, "DB_PATH", tmp_path / "nse_indices.db")
    yesterday = date.today() - timedelta(days=1)
    monkeypatch.setattr(bf, "index_trading_days", lambda: ({yesterday.isoformat()}, yesterday.isoformat()))
    monkeypatch.setattr(bf, "fetch_day", lambda day: None)
    monkeypatch.setattr("sys.argv", ["backfill_nse_indices.py", "--fill-gaps", "--delay", "0"])
    assert bf.main() == 1


def test_a_multi_month_hole_fails_the_audit():
    r = judge_index_coverage(SESSIONS, HOLE, date(2026, 9, 27))
    assert r.status == FAIL
    assert r.evidence["longest_run"] == {"first": "2025-09-22", "last": "2026-03-11", "sessions": len(HOLE)}


def test_one_old_session_missing_is_a_warning_and_none_is_a_pass():
    assert judge_index_coverage(SESSIONS, ["2025-10-01"], date(2026, 9, 27)).status == WARN
    assert judge_index_coverage(SESSIONS, [], date(2026, 9, 27)).status == PASS


def test_a_recent_missing_session_fails_the_audit():
    assert judge_index_coverage(SESSIONS, ["2026-04-29"], date(2026, 5, 1)).status == FAIL


def test_the_nightly_job_fills_gaps_even_when_the_recent_pass_fails():
    spec = importlib.util.spec_from_file_location("daily_job", Path(__file__).parents[1] / "scripts" / "daily_job.py")
    job = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(job)
    ran = []
    job.run_script = lambda *args: ran.append(args) or "--recent" not in args
    assert job.step_nse_indices() is False
    assert ran == [("scripts/backfill_nse_indices.py", "--recent"), ("scripts/backfill_nse_indices.py", "--fill-gaps")]
