"""Backfills the local NIFTY options archive from NSE's F&O bhavcopy.

    python scripts/backfill_options.py --start 2021-01-01 --end 2026-09-15
    python scripts/backfill_options.py --fill-gaps     # every session since 2018 with no data

Resumable: days already recorded in ingested_days are skipped, so an
interrupted run continues where it left off. Deliberately paced with a
delay between requests — this hits a public exchange archive a few
thousand times, and hammering it would be both rude and a good way to get
blocked.

Which days count as sessions comes from the index bar archive, not from the
calendar. That is what lets a missing bhavcopy be told apart:
  * the index traded that day  -> the download failed; leave it unrecorded
                                  so the next run retries it
  * the archive covers the day
    and the index did not trade -> a holiday; record it so it is not
                                  requested again
  * the archive does not reach
    that far yet               -> unknown; leave it unrecorded
Weekends are skipped unless the index shows a session (Budget days, Muhurat).
"""

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.bar_archive import index_trading_days  # noqa: E402
from market_data.nse_bhavcopy import fetch_option_bars  # noqa: E402
from storage import archive_stats, connect, init_db, is_day_ingested, save_day  # noqa: E402

OPTIONS_START = date(2018, 1, 1)
RECENT_DAYS = 7


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def sessions_missing_data(sessions: set[str]) -> list[date]:
    """Sessions since OPTIONS_START that have no option rows at all."""
    with connect() as conn:
        have = {r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM option_bars")}
    return sorted(date.fromisoformat(d) for d in sessions
                  if d >= OPTIONS_START.isoformat() and d not in have)


def fetch_day(day: date, sessions: set[str], archived_to: str | None, symbol: str) -> str:
    """'saved' | 'holiday' | 'failed' | 'unknown' | 'skipped'."""
    iso = day.isoformat()
    is_session = iso in sessions
    if day.weekday() >= 5 and not is_session:
        return "skipped"
    bars = fetch_option_bars(day, symbol=symbol)
    if bars:
        save_day(iso, bars)
        return "saved"
    if is_session:
        return "failed"
    if archived_to and iso <= archived_to:
        save_day(iso, [], confirmed_holiday=True)
        return "holiday"
    return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=parse_day)
    parser.add_argument("--end", type=parse_day, default=date.today())
    parser.add_argument("--fill-gaps", action="store_true",
                        help="fetch only index sessions since 2018 that have no option data")
    parser.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    parser.add_argument("--symbol", default="NIFTY")
    args = parser.parse_args()
    if not args.start and not args.fill_gaps:
        parser.error("give --start, or --fill-gaps")

    init_db()
    sessions, archived_to = index_trading_days()

    if args.fill_gaps:
        days = sessions_missing_data(sessions)
    else:
        days, d = [], args.start
        while d <= args.end:
            days.append(d)
            d += timedelta(days=1)

    counts: dict[str, int] = {}
    total_rows = 0
    recent_failures = []
    for day in days:
        iso = day.isoformat()
        if not args.fill_gaps and is_day_ingested(iso):
            counts["already"] = counts.get("already", 0) + 1
            continue
        try:
            outcome = fetch_day(day, sessions, archived_to, args.symbol)
        except Exception as e:
            outcome = "failed"
            print(f"{iso}: FAILED — {type(e).__name__}: {e}", flush=True)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome == "saved":
            with connect() as conn:
                total_rows += conn.execute("SELECT COUNT(*) FROM option_bars WHERE trade_date=?", (iso,)).fetchone()[0]
            print(f"{iso}: saved", flush=True)
        elif outcome == "failed":
            print(f"{iso}: index traded but no bhavcopy — will retry next run", flush=True)
            if (date.today() - day).days <= RECENT_DAYS:
                recent_failures.append(iso)
        if outcome != "skipped":
            time.sleep(args.delay)

    print("\n--- backfill complete ---", flush=True)
    print(f"days considered: {len(days)}; " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())), flush=True)
    print(f"rows for the days saved this run: {total_rows}", flush=True)
    print(f"archive now: {archive_stats()}", flush=True)
    # A recent miss is probably transient and worth an alarm. An old one that
    # keeps missing (2021-03-30 has no file on NSE's archive at all) is
    # retried quietly — failing the nightly job for it forever would teach
    # everyone to ignore the failure.
    return 1 if recent_failures else 0


if __name__ == "__main__":
    sys.exit(main())
