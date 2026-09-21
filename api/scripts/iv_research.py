"""Implied volatility: the daily series, a description of every pattern's
trades, and the one pre-registered filter test. See backtest/iv_research.py.

    python scripts/iv_research.py

The series is incremental — only days not yet in data/iv.db are computed —
so the nightly run is quick. The test is re-run on the full history each
time; its hypothesis and threshold are fixed and are not tuned.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.iv_research import RESEARCH_PATH, run_iv_research  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    r = run_iv_research()
    RESEARCH_PATH.write_text(json.dumps(r, indent=2, default=str))
    s, v, t = r["series"], r["vix_check"], r["preregistered_test"]
    print(f"{s['days']} days, {s['first']} to {s['last']} ({s['added_this_run']} new) in {time.time() - t0:.0f}s")
    print(f"today: 30-day IV {s['latest']['iv_30d_pct']}%, {s['latest']['percentile_1y']}th percentile of the past year")
    print(f"vs India VIX: correlation {v.get('level_correlation')} — {v.get('verdict')}\n")
    print("pre-registered test:", t["verdict"])
    print("  ", t["detail"])
    for period in ("development", "holdout"):
        x = t[period]
        print(f"   {period:11} low-IV days {x['n_low']:3} avg Rs {x.get('mean_low')}   high-IV days {x['n_high']:3} "
              f"avg Rs {x.get('mean_high')}   t={x['t']} (df {x['df']}, bar {x['bar']})")
