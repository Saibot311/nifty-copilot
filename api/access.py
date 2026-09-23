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
# because neither reveals anything.
OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/api/access/check"}


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


def _presented(request: Request) -> str | None:
    return request.headers.get(HEADER) or request.query_params.get("token") or request.cookies.get("copilot_token")


class TokenGate(BaseHTTPMiddleware):
    """Local requests pass. Everything else needs the token."""

    async def dispatch(self, request: Request, call_next):
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
