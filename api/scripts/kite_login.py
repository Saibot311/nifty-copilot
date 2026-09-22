"""The daily Zerodha login, automated as far as it honestly can be.

Kite access tokens expire at ~6 AM IST. Zerodha requires a person to log in
— password and 2FA happen on their site, and this project will not keep a
broker password or a 2FA seed on disk to fake that. So this script does
everything except the login itself:

  * checks whether today already has a valid session
  * if not, on a weekday, opens the Kite login page in the browser and
    raises a macOS notification, well before the 9:15 open
  * records the outcome either way, so the days without a session (the days
    15-minute bars and live tracking are missing) are visible afterwards

    cd api && .venv/bin/python scripts/kite_login.py             # check, prompt if needed
    cd api && .venv/bin/python scripts/kite_login.py --check-only  # record only, never prompt
"""

import argparse
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.kite_session import IST, KiteNotConfigured, login_url, session_status  # noqa: E402
from storage.login_log_db import record, summary  # noqa: E402

LOGIN_PAGE = "http://127.0.0.1:8000/api/zerodha/login"


def notify(message: str) -> None:
    safe = message.replace('"', "'")[:220]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "NIFTY Copilot"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true", help="record the state; never open a browser")
    a = ap.parse_args()

    now = datetime.now(IST)
    status = session_status()

    if status["logged_in"]:
        record("LOGGED_IN", issued_at=status.get("issued_at"), user_id=status.get("user_id"))
        s = summary()
        print(f"logged in since {status['issued_at']} — {s['current_streak']} day streak", flush=True)
        return 0

    if not status["configured"]["api_key"] or not status["configured"]["api_secret"]:
        record("MISSING", note="KITE_API_KEY/SECRET missing from api/.env")
        print("Kite is not configured — see api/.env", flush=True)
        return 1

    if a.check_only or now.weekday() >= 5:
        record("MISSING", note=status.get("reason"))
        print(f"no session: {status.get('reason')}", flush=True)
        return 0

    # A weekday with no session, and it is the morning: open the page the
    # user has to complete themselves. The API server serves the redirect so
    # the callback lands back here; if it is down, go straight to Kite.
    try:
        target = LOGIN_PAGE if _api_is_up() else login_url()
    except KiteNotConfigured as e:
        record("MISSING", note=str(e))
        print(str(e), flush=True)
        return 1
    opened = webbrowser.open(target)
    record("PROMPTED", note=f"opened {'the login page' if opened else 'nothing — browser refused'} at {now:%H:%M}")
    notify("Zerodha login needed for today — the login page is open. Password and 2FA stay on Zerodha's site.")
    print(f"prompted at {now:%H:%M} IST — {target}", flush=True)
    return 0


def _api_is_up() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
