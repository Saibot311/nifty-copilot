"""Score the day-ahead forecasts whose sessions have closed, then forecast
the next session if it has not opened. Nightly (scripts/daily_job.py).

    cd api && .venv/bin/python scripts/day_forecast.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from briefing.day_forecast import run_day_forecast  # noqa: E402

if __name__ == "__main__":
    w = run_day_forecast()
    print(f"scored: {', '.join(w['scored']) or 'none'}; forecast written for: {w['forecast'] or 'none (already written, or the session has opened)'}")
