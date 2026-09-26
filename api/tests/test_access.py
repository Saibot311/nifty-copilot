"""Who may talk to the API. The dashboard holds a broker session, a personal
journal and a paper book: this Mac gets in, anything else needs the token,
and the token is never handed to a remote caller."""

import hmac

import pytest

import access


class _Req:
    """The pieces of a request the gate looks at."""

    def __init__(self, host="127.0.0.1", path="/api/paper", headers=None, params=None, cookies=None):
        self.client = type("C", (), {"host": host})()
        self.url = type("U", (), {"path": path})()
        self.headers = headers or {}
        self.query_params = params or {}
        self.cookies = cookies or {}
        self.method = "GET"


def test_this_mac_is_admitted_and_anything_else_is_not():
    assert access.is_local(_Req(host="127.0.0.1"))
    assert access.is_local(_Req(host="::1"))
    assert not access.is_local(_Req(host="192.168.1.42"))
    assert not access.is_local(_Req(host="10.0.0.9"))


def test_a_token_is_long_enough_to_be_worth_having(tmp_path, monkeypatch):
    monkeypatch.setattr(access, "ENV_PATH", tmp_path / ".env")
    (tmp_path / ".env").write_text("OTHER=1\n")
    monkeypatch.delenv(access.TOKEN_KEY, raising=False)
    first = access.ensure_token()
    assert len(first) >= 24
    assert access.ensure_token() == first          # created once, never rotated by accident
    assert (tmp_path / ".env").stat().st_mode & 0o777 == 0o600


def test_the_token_is_compared_without_leaking_its_length(monkeypatch):
    # hmac.compare_digest, not ==: the gate must not answer faster for a
    # wrong first character than for a wrong last one.
    import inspect
    assert "compare_digest" in inspect.getsource(access.TokenGate)
    assert hmac.compare_digest("abc", "abc")


@pytest.mark.parametrize("path", sorted(access.OPEN_PATHS))
def test_the_open_paths_reveal_nothing(path):
    # /health and the pairing *check* must work unpaired, so a phone can be
    # told what is wrong. None of them returns data or the token.
    assert path in {"/health", "/api/access/check"}


def test_pairing_is_refused_to_everyone_but_this_mac():
    import inspect

    import main
    source = inspect.getsource(main.access_pairing)
    assert "is_local" in source and "403" in source
    assert "is_local" in inspect.getsource(main.access_rotate)


# --- a web page in this Mac's browser is also "this Mac" ----------------------

def _call_gate(method="GET", host="127.0.0.1:8000", origin=None, path="/api/paper", client="127.0.0.1",
               query="", extra_headers=()):
    """Run a request through the real middleware and return the status."""
    import asyncio

    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    headers = [(b"host", host.encode())] + ([(b"origin", origin.encode())] if origin else [])
    headers += [(k.encode(), v.encode()) for k, v in extra_headers]
    scope = {"type": "http", "method": method, "path": path, "headers": headers, "query_string": query.encode(),
             "client": (client, 5555), "server": ("127.0.0.1", 8000), "scheme": "http", "root_path": ""}
    gate = access.TokenGate(app=None, allowed_origins=["http://localhost:3000", "http://127.0.0.1:3000"])

    async def call_next(req):
        return PlainTextResponse("handled")

    return asyncio.run(gate.dispatch(Request(scope), call_next)).status_code


def test_a_forged_host_is_refused(monkeypatch):
    """DNS rebinding: a page on attacker.example re-pointed at 127.0.0.1 is
    "this Mac" by address. The API answered it — pairing token included."""
    monkeypatch.delenv("DASHBOARD_HOSTS", raising=False)
    monkeypatch.setattr(access, "ENV_PATH", access.Path("/nonexistent/.env"))
    assert _call_gate(host="attacker.example:8000") == 400
    assert _call_gate(path="/api/access/pairing", host="attacker.example") == 400
    assert _call_gate(host="127.0.0.1:8000") == 200
    assert _call_gate(host="localhost:8000") == 200
    assert _call_gate(host="[::1]:8000") == 200


def test_the_phones_address_is_a_known_host(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOSTS", "192.168.1.20")
    assert access.host_allowed("192.168.1.20:8000") and not access.host_allowed("192.168.1.21:8000")


def test_another_site_cannot_change_anything(monkeypatch):
    """Any page open in this Mac's browser could POST here as "this Mac" —
    rotating the pairing token, which locks the phone out."""
    monkeypatch.delenv("DASHBOARD_HOSTS", raising=False)
    monkeypatch.setattr(access, "ENV_PATH", access.Path("/nonexistent/.env"))
    assert _call_gate("POST", origin="https://evil.example", path="/api/access/rotate") == 403
    assert _call_gate("DELETE", origin="https://evil.example", path="/api/journal/1") == 403
    assert _call_gate("POST", origin="http://localhost:3000", path="/api/access/rotate") == 200
    assert _call_gate("POST", origin=None, path="/api/journal") == 200   # curl, scripts: no Origin
    assert _call_gate("GET", origin="https://evil.example") == 200       # reads are CORS's job


def test_the_broker_user_id_is_not_handed_out(monkeypatch, tmp_path):
    import json

    import main
    from storage import login_log_db
    monkeypatch.setattr(login_log_db, "DB_PATH", tmp_path / "login.db")
    monkeypatch.setattr(main.kite_session, "session_status",
                        lambda: {"configured": {}, "logged_in": True, "user_id": "ZZ9999", "issued_at": "2026-09-24T10:15:00+05:30"})
    out = json.dumps(main.zerodha_status())
    assert "ZZ9999" not in out and "user_id" not in out


# --- the token never rides in a URL ---------------------------------------------

TOKEN = "t0ken-abcdefghijklmnopqrstuvwx"


@pytest.fixture
def phone(monkeypatch):
    monkeypatch.setenv("DASHBOARD_HOSTS", "192.168.1.20")
    monkeypatch.setenv(access.TOKEN_KEY, TOKEN)
    return dict(host="192.168.1.20:8000", client="192.168.1.30")


def test_a_token_in_the_url_is_not_accepted(phone):
    """A URL is written to server logs, browser history and Referer headers;
    the header and the HttpOnly cookie are not."""
    assert _call_gate(query=f"token={TOKEN}", **phone) == 401
    assert _call_gate(extra_headers=[("x-copilot-token", TOKEN)], **phone) == 200
    assert _call_gate(extra_headers=[("cookie", f"copilot_token={TOKEN}")], **phone) == 200
    assert _call_gate(extra_headers=[("cookie", "copilot_token=wrong")], **phone) == 401


def test_the_check_says_whether_the_cookie_works(phone):
    """The page asks, and once the cookie is known to work it deletes the copy
    of the token it kept where page scripts can read it."""
    assert access.cookie_ok(_Req(host="192.168.1.30", cookies={"copilot_token": TOKEN}))
    assert not access.cookie_ok(_Req(host="192.168.1.30", cookies={"copilot_token": "wrong"}))
    assert not access.cookie_ok(_Req(host="192.168.1.30"))


def test_the_phone_may_send_its_cookie_across_ports():
    """The page is served on :3000 and the API on :8000: the browser sends the
    cookie only if the API allows credentials, for named origins only."""
    import main
    cors = next(m for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert cors.kwargs["allow_credentials"] is True and "*" not in cors.kwargs["allow_origins"]
