"""Backfills NSE's participant-wise open interest (Client / DII / FII / Pro).

    python scripts/backfill_participant_oi.py                 # every session since 2019 not yet saved
    python scripts/backfill_participant_oi.py --start 2026-09-01

Sessions come from the index bar archive, so a missing file on a day the
index traded is a failure to retry, never recorded as a holiday — the lesson
from the options backfill. Paced: this is a public exchange archive.
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.bar_archive import index_trading_days  # noqa: E402
from storage.participant_oi_db import days_saved, parse, save_day  # noqa: E402

URL = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{:%d%m%Y}.csv"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2019, 1, 1))
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    sessions, _ = index_trading_days()
    have = days_saved()
    todo = sorted(d for d in sessions if d >= args.start.isoformat() and d not in have)
    saved = failed = 0
    for d in todo:
        day = date.fromisoformat(d)
        try:
            r = requests.get(URL.format(day), headers=HEADERS, timeout=30)
            rows = parse(r.text) if r.ok else []
        except requests.RequestException:
            rows = []
        if rows:
            save_day(d, rows)
            saved += 1
        else:
            failed += 1
        time.sleep(args.delay)
    print(f"sessions to fetch: {len(todo)}; saved {saved}; missing {failed} (retried next run)")
    recent_missing = [d for d in todo if d not in days_saved() and (date.today() - date.fromisoformat(d)).days <= 7]
    return 1 if recent_missing else 0


if __name__ == "__main__":
    sys.exit(main())
