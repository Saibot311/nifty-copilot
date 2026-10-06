"""Score the day-ahead forecasts whose sessions have closed, then forecast
the next session if it has not opened. Nightly (scripts/daily_job.py).

Exits 1 when the next session still has no forecast and has not opened —
its close or IV is not in yet — so the job tries again at its end.

    cd api && .venv/bin/python scripts/day_forecast.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from briefing.day_forecast import forecast_status, load_inputs, run_day_forecast  # noqa: E402
from market_data.kite_session import IST  # noqa: E402
from market_data.nse_holidays import trading_holidays  # noqa: E402

if __name__ == "__main__":
    now = datetime.now(IST)
    inputs = load_inputs(now.date())
    if inputs.get("filled_from_nse"):
        print(f"closes from NSE's report (not in the Kite archive): {', '.join(inputs['filled_from_nse'])}")
    w = run_day_forecast(now, inputs=inputs)
    print(f"scored: {', '.join(w['scored']) or 'none'}; forecast written for: {w['forecast'] or 'none'}")
    holidays, _known = trading_holidays()
    st = forecast_status(now, None, inputs, holidays)
    if st["stale"]:
        print(f"no forecast for {st['due']}: " + "; ".join(st["reasons"]))
        sys.exit(1)
