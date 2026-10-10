"""Kronos's hindcast forecast (briefing/kronos_forecast.py).

    cd api && .venv/bin/python scripts/kronos_hindcast.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from briefing.kronos_forecast import run_hindcast  # noqa: E402

if __name__ == "__main__":
    out = run_hindcast()
    print({k: v for k, v in out.items() if k != "rows"} if isinstance(out, dict) else out)
