"""Watches the two services and restarts one that has stopped answering.

launchd's KeepAlive covers a process that dies. It does not cover the worse
case: a process that is still alive and no longer answering — a wedged event
loop, a request stuck on a socket, a Next server that survived an OOM. From
the outside that looks like a dashboard that spins forever.

So: ask both services a cheap question every few minutes. One failure is
ignored (a cold start after a rebuild can take 15 seconds). Two in a row and
the service is restarted and a notification says so, because a restart that
nobody notices hides a problem that keeps coming back.

    cd api && .venv/bin/python scripts/health_watch.py
    cd api && .venv/bin/python scripts/health_watch.py --once --dry-run
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

API_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = API_DIR / "data" / "health_watch.json"
LOG_PATH = API_DIR / "data" / "health_watch.log"

SERVICES = {
    # The deep check opens a file: plain /health answered through a
    # file-descriptor exhaustion that failed every real endpoint.
    "com.niftycopilot.api": "http://127.0.0.1:8000/health/deep",
    "com.niftycopilot.web": "http://127.0.0.1:3000",
}
TIMEOUT = 20
FAILURES_BEFORE_RESTART = 2


def answering(url: str, timeout: int = TIMEOUT) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 500          # a 404 still means the server is alive
    except Exception:
        return False


def should_restart(consecutive_failures: int) -> bool:
    """One miss is a cold start; two is a service that is not coming back."""
    return consecutive_failures >= FAILURES_BEFORE_RESTART


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


def log(message: str) -> None:
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify(message: str) -> None:
    safe = message.replace('"', "'")[:220]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "NIFTY Copilot"'],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def restart(label: str) -> bool:
    domain = f"gui/{os.getuid()}"
    done = subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report, never restart")
    ap.add_argument("--once", action="store_true", help="kept for symmetry; a run is always one pass")
    a = ap.parse_args()

    state = load_state()
    unhealthy = []
    for label, url in SERVICES.items():
        ok = answering(url)
        fails = 0 if ok else int(state.get(label, 0)) + 1
        state[label] = fails
        if not ok:
            unhealthy.append(label)
            if should_restart(fails) and not a.dry_run:
                restarted = restart(label)
                log(f"{label}: no answer from {url} ({fails} in a row) — "
                    + ("restarted" if restarted else "RESTART FAILED"))
                notify(f"{label.split('.')[-1]} stopped answering and was restarted.")
                state[label] = 0
            else:
                log(f"{label}: no answer from {url} ({fails} in a row)"
                    + (" — dry run" if a.dry_run else ", watching"))
    state["checked_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    if not unhealthy:
        print("both services answering", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
