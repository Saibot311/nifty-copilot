"""Backfill the local index-bar archive from Kite. Resumable: re-running
picks up from the last stored bar, so it doubles as the daily top-up.

    python scripts/backfill_bars.py                   # 15m NIFTY, from 2015
    python scripts/backfill_bars.py --timeframe 1d    # daily NIFTY, from 1990
    python scripts/backfill_bars.py --symbol ^INDIAVIX --timeframe 15m

Requires an active Zerodha session (log in via /api/zerodha/login).
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.bar_archive import archive_summary, last_timestamp, save_bars  # noqa: E402
from market_data.kite_session import KiteNotLoggedIn  # noqa: E402
from market_data.zerodha_provider import ZerodhaProvider  # noqa: E402

# Kite returns nothing before these; starting earlier only costs empty requests.
EARLIEST = {"15m": date(2015, 1, 1), "1d": date(1990, 1, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="^NSEI")
    ap.add_argument("--timeframe", default="15m", choices=sorted(EARLIEST) + ["5m", "1m", "1h", "30m"])
    args = ap.parse_args()

    last = last_timestamp(args.symbol, args.timeframe)
    start = datetime.fromisoformat(last).date() if last else EARLIEST.get(args.timeframe, date(2015, 1, 1))
    end = date.today()
    print(f"{args.symbol} {args.timeframe}: fetching {start} -> {end}" + (" (resuming)" if last else ""))

    provider = ZerodhaProvider()
    total = 0
    chunk_start = start
    try:
        while chunk_start <= end:
            chunk_end = min(date(chunk_start.year, 12, 31), end)
            candles = provider.get_ohlc(args.symbol, args.timeframe, chunk_start, chunk_end)
            written = save_bars(args.symbol, args.timeframe, candles, source="kite")
            skipped = len(candles) - written
            total += written
            print(f"  {chunk_start.year}: {written:6d} bars" + (f" ({skipped} provisional skipped)" if skipped else ""))
            chunk_start = chunk_end + timedelta(days=1)
    except KiteNotLoggedIn as e:
        print(f"Stopped: {e}. Progress so far is saved; log in and re-run to resume.")
        return 1

    print(f"Done: {total} bars written.")
    for row in archive_summary():
        print(f"  {row['symbol']:>10} {row['interval']:>3}: {row['bars']:7d} bars, {row['days']} days, {row['first']} -> {row['last']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
