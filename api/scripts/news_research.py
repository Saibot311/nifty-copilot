#!/usr/bin/env python3
"""Run the pre-registered news-tone hypotheses and save the result.

    ./api/.venv/bin/python api/scripts/news_research.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.news_research import RESEARCH_PATH, run_news_research


def main() -> int:
    out = run_news_research()
    RESEARCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_PATH.write_text(json.dumps(out, indent=2, default=str))

    cov = out.get("coverage") or {}
    print(f"tone archive: {cov.get('days')} days, {cov.get('first')} .. {cov.get('last')}")
    print(f"pre-registration {out.get('prereg_hash')} — {out.get('tested')} hypotheses, "
          f"{out.get('approved')} approved\n")
    for h in out.get("hypotheses", []):
        hol = h["holdout"]
        print(f"  {h['status']:12} {h['label']:38} "
              f"holdout {hol.get('num_trades', 0):3d} trades, "
              f"Rs {hol.get('avg_profit_per_lot_rs', 0):>7,}/lot vs "
              f"{hol.get('baseline_avg_profit_per_lot_rs') or 0:>7,} baseline, "
              f"t={hol.get('t')} (bar {h.get('required_t')})")
    print(f"\nsaved to {RESEARCH_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
