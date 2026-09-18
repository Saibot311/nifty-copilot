"""Kite access tokens die at ~6 AM IST daily. The session check must treat
a token as dead after the reset — not 24h after issue — or the app would
make authenticated calls with a token Kite has already revoked."""

import json
from datetime import datetime

import pytest

import market_data.kite_session as ks


def _freeze(monkeypatch, now: datetime):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(ks, "datetime", Frozen)


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    path = tmp_path / "kite_session.json"
    monkeypatch.setattr(ks, "SESSION_PATH", path)
    monkeypatch.setattr(ks, "ENV_PATH", tmp_path / ".env")
    return path


def _write(path, issued: datetime):
    path.write_text(json.dumps({"access_token": "x", "user_id": "AB1234", "issued_at": issued.isoformat()}))


def test_token_issued_this_morning_is_valid(session_file, monkeypatch):
    _write(session_file, datetime(2026, 9, 18, 9, 15, tzinfo=ks.IST))
    _freeze(monkeypatch, datetime(2026, 9, 18, 15, 0, tzinfo=ks.IST))
    assert ks.session_status()["logged_in"] is True


def test_token_expires_at_next_6am_not_24h_later(session_file, monkeypatch):
    _write(session_file, datetime(2026, 9, 18, 20, 0, tzinfo=ks.IST))  # issued 8 PM
    _freeze(monkeypatch, datetime(2026, 9, 19, 6, 30, tzinfo=ks.IST))  # only 10.5h later
    assert ks.session_status()["logged_in"] is False


def test_token_issued_after_midnight_survives_until_6am(session_file, monkeypatch):
    _write(session_file, datetime(2026, 9, 19, 1, 0, tzinfo=ks.IST))
    _freeze(monkeypatch, datetime(2026, 9, 19, 5, 0, tzinfo=ks.IST))
    assert ks.session_status()["logged_in"] is True


def test_no_session_file_means_not_logged_in(session_file):
    assert ks.session_status()["logged_in"] is False
    with pytest.raises(ks.KiteNotLoggedIn):
        ks.authenticated_client()
