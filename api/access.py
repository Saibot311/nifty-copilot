"""Who may talk to this API.

The dashboard holds a live broker session, a personal journal and a paper
book. Deployed on this Mac it listens to 127.0.0.1 and the question does not
arise. The moment it is reachable from a phone it does: anything else on that
network can reach it too.

So: a request from this Mac is admitted as before, and a request from
anywhere else must carry a token. The token lives in api/.env (gitignored,
mode 600) and is never printed, logged or returned — the pairing page on the
Mac shows it as a QR code, which is the only place it is displayed.

This is a lock on a door, not a security system. It protects a personal
dashboard on a home network; it is not an invitation to put this on the
public internet, where it would need TLS and a great deal more thought.
"""

import hmac
import os
import secrets
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

ENV_PATH = Path(__file__).parent / ".env"
TOKEN_KEY = "DASHBOARD_TOKEN"
HEADER = "X-Copilot-Token"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
# Reachable without a token, because a phone needs them to say hello and
# because neither reveals anything. The API's docs are not among them: the
# map of every endpoint is for this Mac, not for the Wi-Fi.
OPEN_PATHS = {"/health", "/api/access/check"}
# The one path a page on another site may send the browser to: Kite's
# redirect back after login. Its one-time state (kite_session.check_state)
# guards it instead.
CROSS_SITE_PATHS = {"/api/zerodha/callback"}


def _env(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip().strip('"').strip("'") or None
    return None


def token() -> str | None:
    return _env(TOKEN_KEY)


def ensure_token() -> str:
    """Creates the token on first use. Written to api/.env at mode 600 and
    returned only to the caller on this Mac — never logged."""
    existing = token()
    if existing:
        return existing
    value = secrets.token_urlsafe(24)
    with open(ENV_PATH, "a") as f:
        f.write(f"\n{TOKEN_KEY}={value}\n")
    ENV_PATH.chmod(0o600)
    return value


def is_local(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in LOCAL_HOSTS


# The names this API answers to. A request is "this Mac" by its address, and
# a DNS-rebinding page — attacker.example re-pointed at 127.0.0.1 — has this
# Mac's address too; what it cannot fake is a Host header naming this Mac.
LOCAL_NAMES = {"127.0.0.1", "localhost", "::1", "[::1]"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in (_env("DASHBOARD_HOSTS") or "").split(",") if h.strip()}
    return LOCAL_NAMES | extra


def host_allowed(host_header: str | None) -> bool:
    if not host_header:
        return False
    h = host_header.strip().lower()
    if h.startswith("["):
        name = h.split("]", 1)[0] + "]"
    else:
        name = h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    return name in allowed_hosts()


COOKIE = "copilot_token"


def _presented(request: Request) -> str | None:
    # The header or the HttpOnly cookie — never the URL. A URL is written to
    # server logs, browser history and Referer headers.
    return request.headers.get(HEADER) or request.cookies.get(COOKIE)


def _matches(given: str | None) -> bool:
    expected = token()
    return bool(given and expected and hmac.compare_digest(given, expected))


def cookie_ok(request: Request) -> bool:
    """Does this caller's cookie alone open the door? Then the page can drop
    the copy of the token it kept where its scripts can read it."""
    return _matches(request.cookies.get(COOKIE))


class TokenGate(BaseHTTPMiddleware):
    """Local requests pass. Everything else needs the token.

    Two checks come first, because "local" is weaker than it sounds: every
    page open in this Mac's browser is local too. A request must name this
    Mac (or its paired LAN address) in its Host header, and a request that
    changes something must not come from another site's page."""

    def __init__(self, app, allowed_origins: list[str] | tuple[str, ...] = ()):
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return JSONResponse({"detail": "This dashboard answers only to its own address."}, status_code=400)
        # A page on another site, open in this Mac's browser, is "this Mac" by
        # address, and a GET needs no Origin: it could make the API fetch news
        # (and pay to judge it) or re-read strategy fit. Browsers say where a
        # request came from; the dashboard's own page is same-site (:3000 and
        # :8000 share the host), and server renders and scripts send nothing.
        if request.headers.get("sec-fetch-site") == "cross-site" and request.url.path not in CROSS_SITE_PATHS:
            return JSONResponse({"detail": "Refused: that request came from another site's page."},
                                status_code=403)
        origin = request.headers.get("origin")
        if request.method in UNSAFE_METHODS and origin and origin not in self.allowed_origins:
            return JSONResponse({"detail": "Refused: that request came from another site's page."},
                                status_code=403)
        if request.method == "OPTIONS" or is_local(request) or request.url.path in OPEN_PATHS:
            return await call_next(request)
        expected = token()
        given = _presented(request)
        # A refusal is returned, not raised: an exception out of middleware
        # never reaches FastAPI's handler and becomes an opaque 500, which
        # tells a phone nothing about what to do next.
        if not expected:
            return JSONResponse({"detail": "This dashboard answers only the Mac it runs on. "
                                           "Pair a device from there first."}, status_code=403)
        if not given or not hmac.compare_digest(given, expected):
            return JSONResponse({"detail": "Pair this device: open the dashboard on the Mac and scan the code."},
                                status_code=401)
        return await call_next(request)
