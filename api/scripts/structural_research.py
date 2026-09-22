"""Run the six pre-registered structural hypotheses for an option buyer and
save the result (api/data/structural_research.json).

    cd api && .venv/bin/python scripts/structural_research.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.structural_research import RESEARCH_PATH, run_structural_research  # noqa: E402


def main() -> None:
    out = run_structural_research()
    RESEARCH_PATH.write_text(json.dumps(out, indent=2, default=str))
    for h in out["hypotheses"]:
        d, ho = h["development"], h["holdout"]
        print(f"{h['status']:11} {h['name']:26} dev {d.get('num_trades', 0):>3} tr Rs{d.get('avg_profit_per_lot_rs')}"
              f" (base {d['baseline_avg_profit_per_lot_rs']})  holdout {ho.get('num_trades', 0):>3} tr "
              f"Rs{ho.get('avg_profit_per_lot_rs')} (base {ho['baseline_avg_profit_per_lot_rs']}) "
              f"t={ho['t']} bar={h['required_t']}")
        print(f"{'':12}{h['reason']}")
    print(json.dumps(out["descriptions"], indent=1)[:1500])


if __name__ == "__main__":
    main()
