"""Kite Connect login + daily access-token handling.

Kite access tokens are not long-lived: every token expires at ~6:00 AM IST
the next day, so a human has to log in through Zerodha once per trading
day. Flow:

  1. /api/zerodha/login     -> redirect to Kite's login page
  2. user logs in on zerodha.com (password + 2FA stay on Zerodha's site)
  3. Kite redirects to /api/zerodha/callback?request_token=...
  4. we exchange request_token + API secret for an access_token and save it
     to data/kite_session.json (gitignored), stamped with when it was issued.

The API secret is read from api/.env (gitignored) and never logged,
returned from an endpoint, or written anywhere else.
"""

import hmac
import json
import os
import secrets
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from kiteconnect import KiteConnect

API_DIR = Path(__file__).parent.parent
ENV_PATH = API_DIR / ".env"
SESSION_PATH = API_DIR / "data" / "kite_session.json"
# The one-time value a login started here carries through Kite and back. Kept
# in a file (mode 600), not memory: the morning login check can start a login
# while the API is down.
STATE_PATH = API_DIR / "data" / "kite_login_state.json"
STATE_TTL = timedelta(minutes=15)

IST = timezone(timedelta(hours=5, minutes=30))
TOKEN_RESET = time(6, 0)  # Kite invalidates all access tokens around 6 AM IST


class KiteNotConfigured(RuntimeError):
    pass


class KiteNotLoggedIn(RuntimeError):
    pass


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'") or None
    return None


def api_key() -> str:
    key = _env("KITE_API_KEY")
    if not key:
        raise KiteNotConfigured("KITE_API_KEY missing from api/.env")
    return key


def _api_secret() -> str:
    secret = _env("KITE_API_SECRET")
    if not secret:
        raise KiteNotConfigured("KITE_API_SECRET missing from api/.env")
    return secret


def login_url() -> str:
    """Kite's login page, carrying a fresh one-time state that Kite hands back
    on the redirect (its documented `redirect_params`). Without it, any page
    could send the browser to the callback with a request token of its own
    and bind the dashboard to another Kite session."""
    state = secrets.token_urlsafe(18)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"state": state, "at": datetime.now(IST).isoformat()}))
    STATE_PATH.chmod(0o600)
    return KiteConnect(api_key=api_key()).login_url() + "&redirect_params=" + quote(f"state={state}", safe="")


def check_state(state: str | None, now: datetime | None = None) -> bool:
    """Was this login started here, recently? A state works once."""
    if not state or not STATE_PATH.exists():
        return False
    try:
        saved = json.loads(STATE_PATH.read_text())
        fresh = (now or datetime.now(IST)) - datetime.fromisoformat(saved["at"]) <= STATE_TTL
        ok = fresh and hmac.compare_digest(str(saved["state"]), state)
    except (ValueError, KeyError, TypeError):
        return False
    if ok:
        STATE_PATH.unlink(missing_ok=True)
    return ok


def complete_login(request_token: str) -> dict:
    kite = KiteConnect(api_key=api_key())
    data = kite.generate_session(request_token, api_secret=_api_secret())
    session = {
        "access_token": data["access_token"],
        "user_id": data.get("user_id"),
        "issued_at": datetime.now(IST).isoformat(),
    }
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(session))
    SESSION_PATH.chmod(0o600)
    return {"user_id": session["user_id"], "issued_at": session["issued_at"]}


def _last_reset(now: datetime) -> datetime:
    reset_today = datetime.combine(now.date(), TOKEN_RESET, tzinfo=IST)
    return reset_today if now >= reset_today else reset_today - timedelta(days=1)


def session_status() -> dict:
    configured = {"api_key": bool(_env("KITE_API_KEY")), "api_secret": bool(_env("KITE_API_SECRET"))}
    if not SESSION_PATH.exists():
        return {"configured": configured, "logged_in": False, "reason": "no session yet — log in"}
    session = json.loads(SESSION_PATH.read_text())
    issued = datetime.fromisoformat(session["issued_at"])
    now = datetime.now(IST)
    if issued < _last_reset(now):
        return {
            "configured": configured,
            "logged_in": False,
            "reason": f"token issued {issued:%d-%b %H:%M} IST expired at the 6 AM reset — log in again",
        }
    return {"configured": configured, "logged_in": True, "user_id": session.get("user_id"), "issued_at": session["issued_at"]}


def authenticated_client() -> KiteConnect:
    status = session_status()
    if not status["logged_in"]:
        raise KiteNotLoggedIn(status["reason"])
    kite = KiteConnect(api_key=api_key())
    kite.set_access_token(json.loads(SESSION_PATH.read_text())["access_token"])
    return kite
