"""Write a missed day-ahead forecast after a Kite login, before the open.

The forecast reads the day's close from the Kite bar archive, which the
nightly job only tops up while the login is current. When it has lapsed
(5 Oct 2026), the next session gets no forecast until someone runs the
steps by hand. A login from the dashboard starts this (main.zerodha_callback):
if the next session has no forecast, has not opened, and the nightly job is
not running, it fetches the daily bars and runs the forecast. Otherwise it
does nothing.

    cd api && .venv/bin/python scripts/forecast_catchup.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

API = Path(__file__).parent.parent
sys.path.insert(0, str(API))

from briefing.day_forecast import forecast_status, job_running, load_inputs, needs_catch_up  # noqa: E402
from market_data.kite_session import IST  # noqa: E402
from market_data.nse_holidays import trading_holidays  # noqa: E402

if __name__ == "__main__":
    now = datetime.now(IST)
    holidays, _known = trading_holidays()
    st = forecast_status(now, None, load_inputs(now.date()), holidays)
    if not needs_catch_up(st, now, job_running(API / "data" / "daily_job.log")):
        print(f"nothing to catch up (due {st['due']}, stale {st['stale']})")
        sys.exit(0)
    subprocess.run([sys.executable, "scripts/backfill_bars.py", "--timeframe", "1d"], cwd=API, check=False)
    sys.exit(subprocess.run([sys.executable, "scripts/day_forecast.py"], cwd=API).returncode)
