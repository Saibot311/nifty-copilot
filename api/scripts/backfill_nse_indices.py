"""Backfills NSE's daily all-index report into api/data/nse_indices.db.

    cd api && .venv/bin/python scripts/backfill_nse_indices.py              # 2017-06 to today
    cd api && .venv/bin/python scripts/backfill_nse_indices.py --recent     # last 10 days (nightly)
    cd api && .venv/bin/python scripts/backfill_nse_indices.py --fill-gaps  # sessions with no report (nightly)

A session (a day the index bar archive shows the index traded) whose report
could not be fetched is a failure: it is left unrecorded, counted in the last
line, and asked for again by --fill-gaps every night until it arrives. On 22
Sep 2026 a minute without network cost 117 sessions of the full run, which
still ended "done: 2191 days saved"; nothing asked for them again.
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.bar_archive import index_trading_days  # noqa: E402
from market_data.nse_indices import fetch_day  # noqa: E402
from storage.nse_index_db import START, fetched, save_day, sessions_missing  # noqa: E402

RECENT_DAYS = 7


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--recent", action="store_true")
    p.add_argument("--fill-gaps", action="store_true", help="only index sessions since 2017-06 with no report")
    p.add_argument("--delay", type=float, default=0.3)
    a = p.parse_args()
    today = date.today()
    sessions, _ = index_trading_days()
    if a.fill_gaps:
        days = [date.fromisoformat(d) for d in sessions_missing(sessions, START.isoformat())]
    else:
        first = today - timedelta(days=10) if a.recent else START
        have = fetched()
        days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
        # Weekends are skipped unless the Zerodha archive shows a special
        # session there (Budget day, Muhurat).
        days = [d for d in days if d.isoformat() not in have
                and (a.recent or d.weekday() < 5 or d.isoformat() in sessions)]
    saved, failed = 0, []
    for d in days:
        try:
            rows = fetch_day(d)
        except Exception as e:
            print(f"{d}: FAILED — {type(e).__name__}: {e}", flush=True)
            rows = None
        if rows:
            save_day(d.isoformat(), rows)
            saved += 1
        elif d.isoformat() in sessions:
            failed.append(d)
        time.sleep(a.delay)
        if d.day == 1:
            print(f"{d}: progress, {saved} days saved", flush=True)
    print(f"--- done: {saved} days saved; {len(failed)} sessions failed"
          + (f" ({failed[0]} to {failed[-1]}) — --fill-gaps asks for them again" if failed else ""), flush=True)
    # A recent miss is worth an alarm. An old one NSE never publishes would
    # fail the nightly job forever and teach everyone to ignore it; the
    # audit's coverage check (0.9) is what shows those.
    return 1 if any((today - d).days <= RECENT_DAYS for d in failed) else 0


if __name__ == "__main__":
    sys.exit(main())
