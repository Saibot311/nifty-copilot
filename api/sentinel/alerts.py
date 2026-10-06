"""One place that tells the owner. To the phone through ntfy when
NTFY_TOPIC is set in api/.env (NTFY_SERVER, default https://ntfy.sh), and
always to the Mac as a notification. A failed send returns False and is
never raised: an alert must not break what it reports on.

The topic is a password in effect — anyone who knows it reads the alerts —
so it is never logged, returned by the API or committed."""

import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta

from market_data.kite_session import _env

REMIND_AFTER = timedelta(hours=6)
DIGEST_AT = (8, 30)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def local_notify(message: str) -> None:
    """A macOS notification; nothing elsewhere."""
    if sys.platform != "darwin":
        return
    safe = message.replace('"', "'")[:220]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "NIFTY Copilot"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def _post(url: str, body: str, headers: dict) -> bool:
    try:
        req = urllib.request.Request(url, data=body.encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def send(title: str, body: str, priority: str = "default", post=None, local=None) -> bool:
    """True when the phone was reached; the Mac is told either way."""
    (local or local_notify)(f"{title}: {body}")
    topic = _env("NTFY_TOPIC")
    if not topic:
        return False
    server = (_env("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    headers = {"Title": title.encode("ascii", "replace").decode(), "Priority": priority}
    return bool((post or _post)(f"{server}/{topic}", body, headers))


def due(incident: dict, now: datetime) -> str | None:
    """'open' when no alert was sent yet, 'reminder' six hours after the last, else None."""
    last = incident.get("last_alert_at")
    if not last:
        return "open"
    return "reminder" if now - datetime.fromisoformat(last) >= REMIND_AFTER else None


def digest_due(now: datetime, state: dict) -> bool:
    return (now.hour, now.minute) >= DIGEST_AT and state.get("digest_on") != now.date().isoformat()


def digest_text(open_: list[dict]) -> str:
    if not open_:
        return "All checks passing."
    parts = []
    for i in open_:
        t = datetime.fromisoformat(i["opened_at"])
        parts.append(f"{i['summary']} (since {t:%H:%M} {t.day} {MONTHS[t.month - 1]})")
    return f"{len(open_)} open: " + "; ".join(parts)
