"""Run the intraday studies and save them for the API to serve.

    python scripts/intraday_research.py

Takes a couple of minutes: 2,880 sessions of 15-minute bars, every daily
strategy's signals, five entry times, two holding periods.

These studies test the system's execution assumption. They add no new
hypotheses about edge, so they do not raise the evidence bar for any
pattern — which is exactly why they were the first thing to spend the
intraday archive on.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.intraday import RESEARCH_PATH, run_intraday_research  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    r = run_intraday_research()
    RESEARCH_PATH.write_text(json.dumps(r, indent=2))
    print(f"{r['sessions']} sessions, {r['from']} to {r['to']}, in {time.time() - t0:.0f}s -> {RESEARCH_PATH}\n")

    oc = r["opening_cost"]["first_bar_drift_pct"]
    print("A. the opening print")
    print(f"   {oc['mean']:+.4f}% by 09:30, t={oc['t_stat']}  "
          f"(dev {oc['dev_mean']:+.4f} t={oc['dev_t']} | holdout {oc['holdout_mean']:+.4f} t={oc['holdout_t']})")
    print(f"   stable: {r['opening_cost']['stable']}  years agreeing: {r['opening_cost']['years_agreeing_with_the_mean']}")
    print(f"   noise added by being 15 minutes late: {oc['std']:.4f}% per entry\n")

    print("B. entry time")
    for hold, block in r["entry_timing"].items():
        v = block["holdout_verdict"]
        print(f"   {hold}: {v['verdict']}")
        print(f"      {v.get('detail', '')}")
    print()

    tod = r["time_of_day"]
    print("C. when the index moves")
    print(f"   busiest 15 minutes: {tod['busiest_slot']}")
    print(f"   slots whose drift clears |t|>2: {tod['slots_with_drift_t_over_2'] or 'none'}"
          "  (25 slots tested at once — expect a couple by chance)")
