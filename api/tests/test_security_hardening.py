"""The four remaining findings from the 2026-09-26 security audit, each held
shut by a test: the paid Copilot question is rate-limited, a page on another
site cannot make this API do anything, the API's own map is not handed to the
Wi-Fi, and a Kite login token never reaches the log."""

import logging
from datetime import datetime, timedelta

import pytest

import access
from tests.test_access import _call_gate

TOKEN = "t0ken-abcdefghijklmnopqrstuvwx"


@pytest.fixture
def phone(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOSTS", "192.168.1.20")
    monkeypatch.setenv(access.TOKEN_KEY, TOKEN)
    return dict(host="192.168.1.20:8000", client="192.168.1.30")


# --- 2. the paid question has a ceiling ------------------------------------------

def test_the_paid_question_is_limited_per_minute_and_per_day():
    from ratelimit import Budget
    t0 = datetime(2026, 9, 28, 10, 0)
    b = Budget(per_minute=3, per_day=5)
    assert [b.take(t0 + timedelta(seconds=i)) for i in range(4)] == [None, None, None, 58]   # 4th: wait 58s
    assert b.take(t0 + timedelta(seconds=61)) is None and b.take(t0 + timedelta(seconds=62)) is None
    wait = b.take(t0 + timedelta(minutes=5))                                                  # 6th today
    assert wait is not None and wait > 3600
    assert b.take(t0 + timedelta(days=1, seconds=1)) is None                                  # a new day


def test_the_endpoint_answers_429_with_retry_after(monkeypatch):
    import main
    from fastapi import HTTPException
    monkeypatch.setattr(main, "COPILOT_BUDGET", type("B", (), {"take": lambda self, now=None: 42})())
    with pytest.raises(HTTPException) as e:
        main.copilot_ask(main.CopilotQuestion(question="why"))
    assert e.value.status_code == 429 and e.value.headers["Retry-After"] == "42"


# --- 3. a page on another site cannot use this API -------------------------------

def test_a_request_the_browser_marks_cross_site_is_refused(monkeypatch):
    """A page elsewhere, open in this Mac's browser, is "this Mac" to the API:
    GETs to /api/news or /api/strategy_fit spent paid calls on its behalf."""
    monkeypatch.delenv("DASHBOARD_HOSTS", raising=False)
    monkeypatch.setattr(access, "ENV_PATH", access.Path("/nonexistent/.env"))
    cross = [("sec-fetch-site", "cross-site")]
    assert _call_gate(path="/api/news", extra_headers=cross) == 403
    assert _call_gate(path="/api/news", extra_headers=[("sec-fetch-site", "same-site")]) == 200   # :3000 -> :8000
    assert _call_gate(path="/api/news", extra_headers=[("sec-fetch-site", "none")]) == 200        # typed in
    assert _call_gate(path="/api/news") == 200                                                   # server render, curl
    # Kite's redirect back is cross-site by nature; its one-time state guards it.
    assert _call_gate(path="/api/zerodha/callback", extra_headers=cross) == 200


def test_the_kite_login_carries_a_one_time_state(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, unquote, urlparse

    from market_data import kite_session as ks
    monkeypatch.setattr(ks, "STATE_PATH", tmp_path / "kite_login_state.json")
    monkeypatch.setattr(ks, "api_key", lambda: "k3y")
    url = ks.login_url()
    state = parse_qs(unquote(parse_qs(urlparse(url).query)["redirect_params"][0]))["state"][0]
    assert (tmp_path / "kite_login_state.json").stat().st_mode & 0o777 == 0o600
    assert not ks.check_state("forged") and not ks.check_state(None)
    assert ks.check_state(state)
    assert not ks.check_state(state)                                   # used once


def test_a_stale_login_state_is_refused(tmp_path, monkeypatch):
    from urllib.parse import parse_qs, unquote, urlparse

    from market_data import kite_session as ks
    monkeypatch.setattr(ks, "STATE_PATH", tmp_path / "kite_login_state.json")
    monkeypatch.setattr(ks, "api_key", lambda: "k3y")
    state = parse_qs(unquote(parse_qs(urlparse(ks.login_url()).query)["redirect_params"][0]))["state"][0]
    later = datetime.now(ks.IST) + ks.STATE_TTL + timedelta(seconds=1)
    assert not ks.check_state(state, now=later)


def test_the_callback_refuses_a_login_it_did_not_start(monkeypatch):
    import main
    from fastapi import HTTPException
    monkeypatch.setattr(main.kite_session, "check_state", lambda s: False)
    monkeypatch.setattr(main.kite_session, "complete_login",
                        lambda t: pytest.fail("a forged login must not reach Kite"))
    with pytest.raises(HTTPException) as e:
        main.zerodha_callback(request_token="rt", status="success", state="forged")
    assert e.value.status_code == 400


# --- 4. the API's map stays on the Mac --------------------------------------------

def test_the_api_docs_need_the_token_off_the_mac(phone):
    for path in ("/docs", "/openapi.json"):
        assert _call_gate(path=path, **phone) == 401
        assert _call_gate(path=path, extra_headers=[("x-copilot-token", TOKEN)], **phone) == 200
    assert _call_gate(path="/docs") == 200                               # on the Mac


# --- 5. no token reaches the log ---------------------------------------------------

def test_tokens_are_blanked_in_the_request_log():
    import main
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:5", "GET", "/api/zerodha/callback?request_token=abc123&status=success",
                             "1.1", 307), None)
    assert main.RedactTokens().filter(rec) is True
    line = rec.getMessage()
    assert "abc123" not in line and "request_token=<redacted>" in line and "status=success" in line
    assert any(isinstance(f, main.RedactTokens) for f in logging.getLogger("uvicorn.access").filters)
