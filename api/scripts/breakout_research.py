"""Run the pre-registered afternoon-breakout study (backtest/breakout_research.py)
and save data/breakout_research.json. Confirmation is 2015-17, never used
before; 2018-26 is where the idea came from.

    python scripts/breakout_research.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from backtest.breakout_research import PREREG_HASH, run_breakout_research  # noqa: E402


def line(name, p):
    if not p.get("num_trades"):
        return f"  {name:13} no trades"
    return (f"  {name:13} {p['num_trades']:4d} trades | option {p['mean_pct']:+7.2f}%/trade (median {p['median_pct']:+.2f}%, "
            f"win {p['win_rate']}%) vs baseline {p['baseline_mean_pct']:+.2f}% | t {p['t_vs_baseline']} | "
            f"index {p['index_points_total']:+.0f} pts ({p['index_points_mean']:+.1f}/trade, win {p['index_win_rate']}%)")


def main() -> int:
    out = run_breakout_research()
    print(f"prereg {PREREG_HASH} · {out['tests_in_family']} hypotheses in the family")
    for h in out["hypotheses"]:
        print(f"\n{h['verdict']:9} {h['label']}\n  {h['reason']}")
        print(line("confirmation", h["confirmation"]) + "   <- 2015-17, the one look")
        print(line("discovery", h["discovery"]))
        for k, p in h["discovery_split"].items():
            print(line(f"  {k}", p))
        print(f"  confirmation bar t >= {h['required_t']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
