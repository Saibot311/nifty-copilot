#!/usr/bin/env python3
"""Run the sentinel's checks: --mode fast from the watchdog every ten
minutes, --mode deep from the nightly job after the audit. Writes the last
result to data/sentinel.json and, once a day at or after 08:30, sends the
digest (sentinel/alerts.py).

    cd api && .venv/bin/python scripts/sentinel_run.py --mode fast
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.kite_session import IST  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "sentinel.json"


def all_checks() -> list:
    from sentinel.checks_data import data_checks
    from sentinel.checks_feeds import feed_checks
    from sentinel.checks_machine import machine_checks
    return machine_checks() + data_checks() + feed_checks()


def send_digest_if_due(now: datetime) -> None:
    from sentinel import alerts, core
    from storage import incidents_db
    try:
        state = json.loads(core.STATE_PATH.read_text())
    except (OSError, ValueError):
        state = {}
    if not alerts.digest_due(now, state):
        return
    alerts.send("Daily check", alerts.digest_text(incidents_db.open_incidents()))
    state["digest_on"] = now.date().isoformat()
    core.STATE_PATH.write_text(json.dumps(state, indent=1))


def main(argv: list[str] | None = None) -> int:
    from sentinel import core
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("fast", "deep"), default="fast")
    a = ap.parse_args(argv)
    now = datetime.now(IST)
    result = core.run(a.mode, all_checks(), now)
    if a.mode == "fast":
        send_digest_if_due(now)
    OUT.write_text(json.dumps({"checked_at": now.isoformat(timespec="seconds"), "mode": a.mode, **result}, indent=1))
    print(f"sentinel {a.mode}: {result['checked']} checks, failing: {', '.join(result['failing']) or 'none'}"
          + (f"; opened {', '.join(result['opened'])}" if result["opened"] else "")
          + (f"; resolved {', '.join(result['resolved'])}" if result["resolved"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
