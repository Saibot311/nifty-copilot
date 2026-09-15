"""Backfills the local NIFTY options archive from NSE's F&O bhavcopy.

Run:  .venv/bin/python3 scripts/backfill_options.py --start 2021-01-01 --end 2026-09-15

Resumable: days already recorded in ingested_days are skipped, so an
interrupted run continues where it left off. Deliberately paced with a
delay between requests — this hits a public exchange archive a few
thousand times, and hammering it would be both rude and a good way to get
blocked.
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.nse_bhavcopy import fetch_option_bars  # noqa: E402
from storage import archive_stats, init_db, is_day_ingested, save_day  # noqa: E402


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=parse_day, required=True)
    parser.add_argument("--end", type=parse_day, default=date.today())
    parser.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    parser.add_argument("--symbol", default="NIFTY")
    args = parser.parse_args()

    init_db()

    day = args.start
    fetched = skipped = failed = 0
    total_rows = 0

    while day <= args.end:
        iso = day.isoformat()

        # Weekends are never trading days — skip without spending a request.
        if day.weekday() >= 5 or is_day_ingested(iso):
            skipped += 1
            day += timedelta(days=1)
            continue

        try:
            bars = fetch_option_bars(day, symbol=args.symbol)
            rows = save_day(iso, bars)
            total_rows += rows
            fetched += 1
            if rows:
                print(f"{iso}: {rows} bars", flush=True)
        except Exception as e:
            failed += 1
            print(f"{iso}: FAILED — {type(e).__name__}: {e}", flush=True)

        time.sleep(args.delay)
        day += timedelta(days=1)

    stats = archive_stats()
    print("\n--- backfill complete ---", flush=True)
    print(f"days fetched: {fetched}, skipped: {skipped}, failed: {failed}", flush=True)
    print(f"rows added this run: {total_rows}", flush=True)
    print(f"archive now: {stats}", flush=True)


if __name__ == "__main__":
    main()
