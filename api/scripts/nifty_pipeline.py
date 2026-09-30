"""Run the pipeline's Phase 2 — five pre-registered hypotheses — once, and save it.

    cd api && .venv/bin/python scripts/nifty_pipeline.py

Each run appends to backtest/hypothesis_log.jsonl; see backtest/nifty_pipeline.py.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.nifty_pipeline import RESEARCH_PATH, run_nifty_pipeline  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    r = run_nifty_pipeline()
    print(f"prereg {r['prereg_hash']}, {r['tests_in_family']} in the family ({time.time() - t0:.0f}s) -> {RESEARCH_PATH}\n")
    print(f"{'hypothesis':28s} {'period':12s} {'trades':>6s} {'mean %':>8s} {'base %':>8s} {'t':>6s}")
    for h in r["hypotheses"]:
        for p in ("development", "holdout"):
            v = h[p]
            t = v.get("t_vs_baseline")
            print(f"{h['label']:28s} {p:12s} {v.get('num_trades', 0):6d} {v.get('mean_pct', float('nan')):8.2f} "
                  f"{v['baseline_mean_pct'] if v['baseline_mean_pct'] is not None else float('nan'):8.2f} "
                  f"{t if t is not None else float('nan'):6.2f}")
        print(f"  -> {h['verdict']} (bar t >= {h['required_t']}): {h['reason']}\n")
