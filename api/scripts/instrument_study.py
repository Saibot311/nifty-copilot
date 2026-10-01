"""Run the pipeline's Phase 1 — which option a buyer should hold — and save it.

    cd api && .venv/bin/python scripts/instrument_study.py
    cd api && .venv/bin/python scripts/instrument_study.py --measured-spreads

Development data only (entries 2019-02-14 to 2023); see backtest/instrument_study.py.

--measured-spreads re-runs the grid with the real half-spreads recorded in
option_snapshots.db (backtest/spread_model) in place of the assumed 1.5% of
premium, and adds the result to instrument_study.json as `with_measured_spreads`,
leaving every other key as it was. It reads only local files: spot is NSE's own
close from the local index archive.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.instrument_study import RESULT_PATH, run_instrument_study  # noqa: E402


def print_cells(cells: list[dict]) -> None:
    print(f"{'expiry':8s} {'moneyness':9s} hold {'trades':>6s} {'carry pts/session':>18s} {'net %':>7s} {'cost %':>7s} {'median %':>8s} {'dte':>5s}")
    for c in cells:
        if "carry_pts_per_session" in c:
            print(f"{c['expiry']:8s} {c['moneyness']:9s} {c['hold']:4d} {c['trades']:6d} {c['carry_pts_per_session']:18.2f} "
                  f"{c['net_pct']:7.2f} {c['cost_pct']:7.2f} {c['median_net_pct']:8.2f} {c['days_to_expiry']:5.1f}")


def local_spots() -> dict[str, float]:
    """NIFTY's daily close from NSE's own report in the local archive, before
    2024 only — no network."""
    from backtest.pattern_options import SPLIT_DATE
    from market_data.nse_indices import load_archive
    df = load_archive("NIFTY")
    return {str(ts.date()): float(c) for ts, c in df["close"].dropna().items() if str(ts.date()) < SPLIT_DATE}


def caveat(sessions: list[str], basis: str, spot_then: tuple[float, float], spot_now: float | None) -> str:
    n = len(sessions)
    level = (f" (NIFTY was {spot_then[0]:,.0f} to {spot_then[1]:,.0f} in 2019-23, {spot_now:,.0f} when measured)"
             if spot_now else "")
    text = (f"Spreads measured in 2026 applied to 2019-23 history: weekly options were thinner then, so their real "
            f"spreads were probably wider than these. Each is charged in index points as measured{level}. "
            f"Measured on {n} session{'' if n == 1 else 's'} only ({', '.join(sessions)}).")
    if basis != "close":
        text += (" No snapshot between 14:30 and 15:30 yet, so these are medians over the part of the session "
                 "recorded, not the closing spread Phase 1 trades at.")
    return text


def measured_spreads() -> None:
    from backtest.options_engine import OptionsCostModel
    from backtest.spread_model import SpreadCostModel, half_spreads, measure_spreads
    measured = measure_spreads()
    basis, window, sessions = "close", measured["window"], measured["close_sessions"]
    spreads = half_spreads(measured)
    if spreads is None:
        basis, window, sessions = "all_day", "all day, no 14:30-15:30 snapshot yet", measured["sessions"]
        spreads = half_spreads(measured, "all_day")
    if spreads is None:
        missing = [f"{b['expiry']} {b['moneyness']}" for b in measured["buckets"] if b["all_day_n"] == 0]
        sys.exit(f"No measured spread yet for: {', '.join(missing)}. Nothing written.")
    study = json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else None
    if study is None:
        sys.exit(f"{RESULT_PATH} does not exist: run without --measured-spreads first. Nothing written.")

    print(f"{'expiry':8s} {'moneyness':9s} {'half-spread pts':>15s} {'% of mid':>9s} {'n':>5s}   "
          f"{'all-day pts':>11s} {'% of mid':>9s} {'n':>5s}")
    for b in measured["buckets"]:
        f = lambda v, w, d: f"{v:{w}.{d}f}" if v is not None else f"{'-':>{w}s}"  # noqa: E731
        print(f"{b['expiry']:8s} {b['moneyness']:9s} {f(b['half_spread_pts'], 15, 2)} {f(b['half_spread_pct'], 9, 2)} "
              f"{b['n']:5d}   {f(b['all_day_half_spread_pts'], 11, 2)} {f(b['all_day_half_spread_pct'], 9, 2)} "
              f"{b['all_day_n']:5d}")
    print(f"\nbasis: {window}; sessions: {', '.join(sessions)}\n")

    t0 = time.time()
    spots = local_spots()
    r = run_instrument_study(spot_by_day=spots, costs=OptionsCostModel(premium_slippage_pct=0.0),
                             sensitivity=False,
                             costs_for=lambda choice, label: SpreadCostModel(half_spread_pts=spreads[(choice, label)]))
    then = [v for d, v in spots.items() if r["period"]["from"] <= d <= r["period"]["to"]]
    study["with_measured_spreads"] = {
        "measured": measured["buckets"],
        "basis": basis,
        "sessions": sessions,
        "window": window,
        "cells": r["cells"],
        "choices": r["choices"],
        "costs": r["costs"] + " and each kind of contract's measured half-spread in points each way",
        "spot": "NSE's own daily close from the local index archive",
        "caveat": caveat(sessions, basis, (min(then), max(then)), measured["spot"]),
    }
    RESULT_PATH.write_text(json.dumps(study, indent=2))
    print(f"{r['period']['sessions']} sessions ({time.time() - t0:.0f}s) -> {RESULT_PATH} [with_measured_spreads]\n")
    print_cells(r["cells"])
    print("\nchoices:", json.dumps(r["choices"]))
    print("caveat:", study["with_measured_spreads"]["caveat"])


def main() -> None:
    t0 = time.time()
    r = run_instrument_study()
    previous = json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else {}
    if "with_measured_spreads" in previous:
        r["with_measured_spreads"] = previous["with_measured_spreads"]   # a re-run keeps the measured result
    RESULT_PATH.write_text(json.dumps(r, indent=2))
    print(f"{r['period']['sessions']} sessions, {r['period']['from']} to {r['period']['to']} "
          f"({time.time() - t0:.0f}s) -> {RESULT_PATH}\n")
    print_cells(r["cells"])
    print("\nchoices:", json.dumps(r["choices"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--measured-spreads", action="store_true",
                    help="re-run with the half-spreads measured in option_snapshots.db and add them to the result")
    if ap.parse_args().measured_spreads:
        measured_spreads()
    else:
        main()
