"""Kronos's daily forecast (briefing/kronos_forecast.py).

    cd api && .venv/bin/python scripts/kronos_daily.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from briefing.kronos_forecast import run_daily  # noqa: E402

if __name__ == "__main__":
    out = run_daily()
    print({k: v for k, v in out.items() if k != "rows"} if isinstance(out, dict) else out)
