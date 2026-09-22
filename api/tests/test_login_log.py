"""The daily Zerodha login record. What must hold: a day that had a session
is never rewritten as one that didn't, the streak counts back from today,
and the record never holds anything that could log in by itself."""

import inspect
from datetime import date

import pytest

import scripts.kite_login as kite_login
from storage import login_log_db as L


@pytest.fixture
def db(tmp_path):
    return tmp_path / "login.db"


def test_a_day_that_had_a_session_is_never_downgraded(db):
    L.record("PROMPTED", today=date(2026, 9, 23), db_path=db)
    L.record("LOGGED_IN", issued_at="2026-09-23T09:12:00+05:30", user_id="X", today=date(2026, 9, 23), db_path=db)
    assert L.record("MISSING", today=date(2026, 9, 23), db_path=db) == "LOGGED_IN"
    assert L.history(db_path=db)[0]["status"] == "LOGGED_IN"


def test_one_row_per_day_and_the_latest_state_wins(db):
    L.record("MISSING", today=date(2026, 9, 22), db_path=db)
    L.record("PROMPTED", today=date(2026, 9, 22), db_path=db)
    rows = L.history(db_path=db)
    assert len(rows) == 1 and rows[0]["status"] == "PROMPTED"


def test_the_streak_counts_back_from_the_newest_day(db):
    for day, status in [(18, "LOGGED_IN"), (21, "MISSING"), (22, "LOGGED_IN"), (23, "LOGGED_IN")]:
        L.record(status, today=date(2026, 9, day), db_path=db)
    s = L.summary(db_path=db)
    assert s["current_streak"] == 2          # 23rd and 22nd; the 21st breaks it
    assert s["days_logged_in"] == 3 and s["days_without_a_session"] == 1
    assert s["last_login"] == "2026-09-23"


def test_an_unknown_status_is_refused(db):
    with pytest.raises(ValueError):
        L.record("DEFINITELY_LOGGED_IN", db_path=db)


def test_nothing_here_can_log_in_by_itself():
    """The point of the feature: it prompts a person. It must not grow a
    stored credential or a browser driver that could replay a login — so
    this reads the code, not the comments that talk about passwords."""
    import ast

    for module in (kite_login, L):
        tree = ast.parse(inspect.getsource(module))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not (imported & {"pyotp", "selenium", "playwright", "mechanize", "pyautogui"}), imported
        names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not {n for n in names if "password" in n or "totp" in n or "otp_secret" in n}


def test_the_morning_check_never_prompts_when_asked_only_to_record(monkeypatch, db):
    monkeypatch.setattr(L, "DB_PATH", db)
    monkeypatch.setattr(kite_login, "session_status", lambda: {
        "logged_in": False, "configured": {"api_key": True, "api_secret": True}, "reason": "expired"})
    opened = []
    monkeypatch.setattr(kite_login.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(kite_login, "notify", lambda msg: opened.append("notified"))
    monkeypatch.setattr(kite_login.sys, "argv", ["kite_login.py", "--check-only"])
    assert kite_login.main() == 0
    assert opened == []
    assert L.history(db_path=db)[0]["status"] == "MISSING"
