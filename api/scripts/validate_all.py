"""Run Phase 8 walk-forward validation over every registered strategy and
record each verdict in the Phase 9 playbook.

    python scripts/validate_all.py            # only strategies never validated
    python scripts/validate_all.py --all      # re-validate everything (adds history rows)

Uses the same settings as /api/validation/{name} defaults, so every verdict
in the playbook is comparable.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.strategies import STRATEGY_REGISTRY  # noqa: E402
from backtest.walkforward import evaluate_strategy  # noqa: E402
from storage import record_strategy_evaluation, strategy_latest_status  # noqa: E402

SETTINGS = {"symbol": "^NSEI", "days": 7000, "hold_days": 10, "n_folds": 5, "train_frac": 0.7}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-validate strategies that already have a verdict")
    args = ap.parse_args()

    names = [n for n in STRATEGY_REGISTRY if args.all or strategy_latest_status(n) is None]
    print(f"Validating {len(names)} of {len(STRATEGY_REGISTRY)} strategies with {SETTINGS}\n")

    failures = []
    for i, name in enumerate(names, 1):
        t0 = time.time()
        try:
            result = evaluate_strategy(strategy_name=name, **SETTINGS)
        except Exception as e:
            failures.append((name, str(e)))
            print(f"[{i:2d}/{len(names)}] {name:32s} ERROR: {e}")
            continue
        record_strategy_evaluation(result, params=SETTINGS)
        wf = result.get("walk_forward", {})
        ho = result.get("holdout", {}).get("holdout", {}).get("metrics", {})
        print(
            f"[{i:2d}/{len(names)}] {result.get('label', name):32s} {result['final_status']:11s} "
            f"folds+ {wf.get('folds_with_positive_expectancy')}/{wf.get('folds_with_any_trades')}  "
            f"holdout {ho.get('num_trades')}t {ho.get('expectancy_pct')}%  ({time.time() - t0:.0f}s)"
        )

    print(f"\nDone. {len(names) - len(failures)} recorded, {len(failures)} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
