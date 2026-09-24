#!/usr/bin/env python3
"""Backfill the daily news-tone series from GDELT, 2018 to today.

One request a year, a minute apart: GDELT still returns a point per day for
a twelve-month window, so the whole history is nine requests rather than a
hundred and five. It is free and answers 429 when pushed — and its cooldown
runs to minutes — so this is deliberately slow. About ten minutes for tone
over eight years, and the same again for volume.

Idempotent — re-running updates the days it fetched and leaves the rest, so
an interrupted run is resumed by running it again.

    ./api/.venv/bin/python api/scripts/backfill_news_tone.py            # tone
    ./api/.venv/bin/python api/scripts/backfill_news_tone.py --volume   # and volume
    ./api/.venv/bin/python api/scripts/backfill_news_tone.py --from 2024-01-01
"""

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_data.gdelt import QUERY_SET, GdeltUnavailable, fetch_window, parse_points, windows
from storage import news_tone_db

FIRST = date(2018, 1, 1)


def run(first: date, last: date, modes: tuple[str, ...], pause: float, months: int) -> int:
    failures = []
    for mode in modes:
        kind = "tone" if mode == "timelinetone" else "volume"
        save = news_tone_db.save_tone if kind == "tone" else news_tone_db.save_volume
        print(f"\n=== {kind} — {first} to {last} ===", flush=True)
        for start, end in windows(first, last, months):
            try:
                points = parse_points(fetch_window(start, end, mode=mode, pause=pause))
            except GdeltUnavailable as e:
                print(f"  {start:%Y-%m}  FAILED  {e}", flush=True)
                failures.append((kind, start))
                continue
            wrote = save(QUERY_SET, points)
            print(f"  from {start:%Y-%m}  {len(points):4d} days  ({wrote} rows written)", flush=True)
            time.sleep(pause)
        cov = news_tone_db.coverage(QUERY_SET)
        print(f"  coverage now: {cov['days']} days, {cov['first']} .. {cov['last']}", flush=True)

    if failures:
        print(f"\n{len(failures)} month(s) failed — re-run to fill them:", flush=True)
        for kind, start in failures:
            print(f"  {kind} {start:%Y-%m}", flush=True)
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="since", default=FIRST.isoformat())
    ap.add_argument("--to", dest="until", default=date.today().isoformat())
    ap.add_argument("--volume", action="store_true", help="also fetch article volume")
    ap.add_argument("--pause", type=float, default=60.0)
    ap.add_argument("--months", type=int, default=12, help="window size per request")
    a = ap.parse_args()
    modes = ("timelinetone", "timelinevol") if a.volume else ("timelinetone",)
    return run(datetime.fromisoformat(a.since).date(), datetime.fromisoformat(a.until).date(),
               modes, a.pause, a.months)


if __name__ == "__main__":
    sys.exit(main())
