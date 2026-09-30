"""Run the pipeline's Phase 1 — which option a buyer should hold — and save it.

    cd api && .venv/bin/python scripts/instrument_study.py

Development data only (entries 2019-02-14 to 2023); see backtest/instrument_study.py.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.instrument_study import RESULT_PATH, run_instrument_study  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    r = run_instrument_study()
    RESULT_PATH.write_text(json.dumps(r, indent=2))
    print(f"{r['period']['sessions']} sessions, {r['period']['from']} to {r['period']['to']} "
          f"({time.time() - t0:.0f}s) -> {RESULT_PATH}\n")
    print(f"{'expiry':8s} {'moneyness':9s} hold {'trades':>6s} {'carry pts/session':>18s} {'net %':>7s} {'cost %':>7s} {'median %':>8s} {'dte':>5s}")
    for c in r["cells"]:
        if "carry_pts_per_session" in c:
            print(f"{c['expiry']:8s} {c['moneyness']:9s} {c['hold']:4d} {c['trades']:6d} {c['carry_pts_per_session']:18.2f} "
                  f"{c['net_pct']:7.2f} {c['cost_pct']:7.2f} {c['median_net_pct']:8.2f} {c['days_to_expiry']:5.1f}")
    print("\nchoices:", json.dumps(r["choices"]))
