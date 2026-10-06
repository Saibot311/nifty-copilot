"""Rebuild the breakout levels' record from every session since 2015, and
score the forward record's breaks whose session is over. Nightly
(scripts/daily_job.py), after the bars and the options archive are in.

    cd api && .venv/bin/python scripts/breakout_levels.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from briefing.breakout_levels import run_nightly  # noqa: E402

if __name__ == "__main__":
    r = run_nightly()
    print(f"record: {r['breaks']} breaks over {r['sessions']} sessions; forward breaks scored: "
          f"{', '.join(r['scored']) or 'none'}")
