"""Run the four registered order-flow rules forward on the option snapshots.

    cd api && .venv/bin/python scripts/orderflow_forward.py

Nightly (scripts/daily_job.py). Each rule waits until its registered minimums
are met, is then judged once, and is logged to the hypothesis log that once.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.orderflow_registry import RESULT_PATH, run_orderflow_forward  # noqa: E402

if __name__ == "__main__":
    r = run_orderflow_forward()
    for h in r["hypotheses"]:
        if h["status"] == "judged":
            print(f"{h['label']}: {h['verdict']} — {h['reason']}")
        else:
            print(f"{h['label']}: waiting — {h['sessions']} of {h['min_sessions']} sessions, "
                  f"{h['counted_trades']} of {h['min_trades']} counted trades ({h['recorded']} recorded)")
    print(f"-> {RESULT_PATH}")
