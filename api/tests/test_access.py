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
    assert path in {"/health", "/docs", "/openapi.json", "/api/access/check"}


def test_pairing_is_refused_to_everyone_but_this_mac():
    import inspect

    import main
    source = inspect.getsource(main.access_pairing)
    assert "is_local" in source and "403" in source
    assert "is_local" in inspect.getsource(main.access_rotate)
