"""Replicate every judged pattern, and three structural tests, on BANKNIFTY,
SENSEX and Midcap Select alongside NIFTY (backtest/replication.py).

    cd api && .venv/bin/python scripts/replication.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.replication import RESEARCH_PATH, run_replication  # noqa: E402


def main() -> None:
    out = run_replication()
    RESEARCH_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(f"coverage: {out['coverage']}; tests counted {out['tests_counted']}")
    for h in out["hypotheses"]:
        p = h["pooled"]
        print(f"{h['status']:11} {h['label'][:36]:36} holdout {p['holdout_dates']:>3} dates "
              f"{p['holdout_avg_pct']}% vs {p['baseline_holdout_avg_pct']}%  t={p['holdout_t']} bar={p['required_t']}  "
              f"indices beating baseline {h['indices_beating_baseline_in_holdout']}/{h['indices_with_holdout_trades']}")


if __name__ == "__main__":
    main()
