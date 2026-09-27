"""Run the five pre-registered course strategies (backtest/course_strategies.py)
and save data/course_research.json. The rules are frozen by hash; this only
runs them.

    python scripts/course_strategies.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from backtest.course_strategies import PREREG_HASH, run_course_research  # noqa: E402


def main() -> int:
    t0 = time.time()
    out = run_course_research()
    print(f"prereg {PREREG_HASH} · {out['tests_in_family']} hypotheses in the family · {time.time() - t0:.0f}s")
    for h in out["hypotheses"]:
        dev, hold = h["development"], h["holdout"]
        print(f"\n{h['verdict']:9} {h['label']}")
        print(f"  {h['reason']}")
        for name, p in (("development", dev), ("holdout", hold)):
            if not p.get("num_trades"):
                print(f"  {name:11} no trades")
                continue
            print(f"  {name:11} {p['num_trades']:4d} trades | option {p['mean_pct']:+7.2f}%/trade (median {p['median_pct']:+.2f}%, "
                  f"win {p['win_rate']}%) vs baseline {p['baseline_mean_pct']:+.2f}% | t {p['t_vs_baseline']} "
                  f"| index {p['index_points_total']:+.0f} pts ({p['index_points_mean']:+.1f}/trade, win {p['index_win_rate']}%)")
        print(f"  holdout bar t >= {h['required_t']}")
        if "course_window" in h:
            w = h["course_window"]
            print(f"  course's own window {w['from']}..{w['to']}: {w['trades']} trades, {w['points']:+.0f} pts, win {w['win_rate']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
