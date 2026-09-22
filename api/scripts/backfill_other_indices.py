"""Backfills option archives for BANKNIFTY and MIDCPNIFTY (NSE) and SENSEX
(BSE), each into its own SQLite file with the NIFTY archive's schema.

    cd api && .venv/bin/python scripts/backfill_other_indices.py            # everything missing
    cd api && .venv/bin/python scripts/backfill_other_indices.py --recent   # last 10 days (nightly)

Why these: the same patterns, judged on more underlyings, give each verdict
more trades without adding a single new idea to test. They are correlated
with NIFTY, so the replication treats a shared date as one observation.

NSE's file for a day holds every underlying, so one download serves both
NSE indices. A day is marked done for an underlying once its file has been
read — with zero rows if that index had no options then (MIDCPNIFTY before
January 2022) — so a rerun resumes rather than refetching. A session whose
file is missing is left unmarked and retried.

BSE's archive begins in January 2024; earlier dates are not requested.
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.bar_archive import index_trading_days  # noqa: E402
from market_data.nse_bhavcopy import fetch_bse_option_bars, fetch_option_bars_multi  # noqa: E402
from storage.options_db import db_path_for, init_db, is_day_ingested, save_day  # noqa: E402

NSE_SYMBOLS = ("BANKNIFTY", "MIDCPNIFTY")
START = date(2018, 1, 1)
BSE_START = date(2024, 1, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recent", action="store_true", help="only the last 10 calendar days")
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--no-bse", action="store_true")
    parser.add_argument("--start", type=date.fromisoformat, help="first day (default 2018-01-01)")
    parser.add_argument("--end", type=date.fromisoformat, help="last day (default today)")
    args = parser.parse_args()

    for u in (*NSE_SYMBOLS, "SENSEX"):
        init_db(db_path_for(u))
    sessions, archived_to = index_trading_days()
    today = args.end or date.today()
    first = today - timedelta(days=10) if args.recent else (args.start or START)
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    days = [d for d in days if d.weekday() < 5 or d.isoformat() in sessions]

    saved = {u: 0 for u in (*NSE_SYMBOLS, "SENSEX")}
    missing: list[str] = []
    for d in days:
        iso = d.isoformat()
        todo = [u for u in NSE_SYMBOLS if not is_day_ingested(iso, db_path_for(u))]
        if todo:
            try:
                by_sym = fetch_option_bars_multi(d, tuple(todo))
            except Exception as e:
                print(f"{iso}: NSE FAILED — {type(e).__name__}: {e}", flush=True)
                by_sym = None
            if by_sym:
                for u in todo:
                    save_day(iso, by_sym.get(u, []), db_path_for(u), confirmed_holiday=True)
                    saved[u] += bool(by_sym.get(u))
            elif by_sym == {} and archived_to and iso <= archived_to and iso not in sessions:
                for u in todo:  # a holiday the index confirms
                    save_day(iso, [], db_path_for(u), confirmed_holiday=True)
            elif iso in sessions:
                missing.append(f"{iso} NSE")
            time.sleep(args.delay)

        if not args.no_bse and d >= BSE_START and not is_day_ingested(iso, db_path_for("SENSEX")):
            try:
                bars = fetch_bse_option_bars(d)
            except Exception as e:
                print(f"{iso}: BSE FAILED — {type(e).__name__}: {e}", flush=True)
                bars = None
            if bars is not None:
                save_day(iso, bars, db_path_for("SENSEX"), confirmed_holiday=True)
                saved["SENSEX"] += bool(bars)
            elif archived_to and iso <= archived_to and iso not in sessions:
                save_day(iso, [], db_path_for("SENSEX"), confirmed_holiday=True)
            elif iso in sessions:
                missing.append(f"{iso} BSE")
            time.sleep(args.delay)

        if d.day == 1 and not args.recent:
            print(f"{iso}: progress — days with rows saved this run {saved}", flush=True)

    print(f"--- done: days with rows saved {saved}; sessions with no file yet: {len(missing)}", flush=True)
    for m in missing[-10:]:
        print(f"  missing {m}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
