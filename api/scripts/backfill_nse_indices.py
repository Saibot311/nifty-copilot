"""Backfills NSE's daily all-index report into api/data/nse_indices.db.

    cd api && .venv/bin/python scripts/backfill_nse_indices.py            # 2017-06 to today
    cd api && .venv/bin/python scripts/backfill_nse_indices.py --recent   # last 10 days (nightly)
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.bar_archive import index_trading_days  # noqa: E402
from market_data.nse_indices import fetch_day  # noqa: E402
from storage.nse_index_db import fetched, save_day  # noqa: E402

START = date(2017, 6, 1)  # enough warm-up before the 2018 options history


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--recent", action="store_true")
    p.add_argument("--delay", type=float, default=0.3)
    a = p.parse_args()
    today = date.today()
    first = today - timedelta(days=10) if a.recent else START
    have = fetched()
    sessions, _ = index_trading_days()
    saved = 0
    for i in range((today - first).days + 1):
        d = first + timedelta(days=i)
        if d.isoformat() in have or (d.weekday() >= 5 and not a.recent and d.isoformat() not in sessions):
            # Weekends are skipped unless the Zerodha archive shows a special
            # session there (Budget day, Muhurat).
            continue
        try:
            rows = fetch_day(d)
        except Exception as e:
            print(f"{d}: FAILED — {type(e).__name__}: {e}", flush=True)
            rows = None
        if rows:
            save_day(d.isoformat(), rows)
            saved += 1
        time.sleep(a.delay)
        if d.day == 1:
            print(f"{d}: progress, {saved} days saved", flush=True)
    print(f"--- done: {saved} days saved", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
