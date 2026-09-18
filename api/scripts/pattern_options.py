"""Compute pattern -> option research and save it for the API to serve.

    python scripts/pattern_options.py

Takes a few minutes (~1,170 option backtests on real NSE contract prices).
Re-run after topping up the options archive.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.pattern_options import run_pattern_options  # noqa: E402

OUT = Path(__file__).parent.parent / "data" / "pattern_options.json"

if __name__ == "__main__":
    t0 = time.time()
    result = run_pattern_options()
    OUT.write_text(json.dumps(result, indent=2))
    print(f"{result['configs_tested_total']} option setups tested in {time.time() - t0:.0f}s -> {OUT}\n")
    for p in result["patterns"]:
        opt = p.get("suggested_option", {}).get("description", "-")
        h = p.get("holdout", {})
        print(f"{p['status']:11s} {p['label']:40s} {p['forms_per_year']:5.1f}/yr  {opt}")
        if h:
            print(f"{'':12s}holdout: {h.get('num_trades')} trades, win {h.get('win_rate')}, avg {h.get('avg_return_pct')}% "
                  f"(Rs {h.get('avg_profit_per_lot_rs')}/lot) vs no-signal {p['baseline']['holdout_avg_return_pct']}%, t={p.get('holdout_t_stat')}")
