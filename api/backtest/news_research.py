"""Does the tone of news coverage pay an option BUYER?

The 26 chart patterns said no. The six structural hypotheses said no. This
asks a different question: whether how the press is *writing* about the
Indian market carries anything a call or a put could be bought on.

It is testable at all only because GDELT has monitored world news since 2015
and gives away a daily tone series (market_data/gdelt.py). No free source
has dated Indian market *headlines* back to 2018, so the headline archive in
storage/news_db.py can only run forward — but tone can be backtested on the
same 2018-2023 development and 2024-26 holdout split as everything else,
which is what makes this a real test rather than a promise of one.

THE LOOK-AHEAD RULE, which matters more here than anywhere else in the
project. GDELT buckets by UTC day. A UTC day ends at 05:29 IST the next
morning — before the next Indian session opens at 09:15 — so a completed
UTC day's tone is fully known before the session that trades on it. Signals
are therefore read off UTC day D and entered at the close of the first
Indian session after D, exactly the convention every other signal here uses.
Tone from the session being traded is never used.

The reason that rule is not optional: a large part of any day's Indian market
coverage is *about that day's move*. "Sensex sinks 800 points" is negative
tone caused by the fall. Tone on day D is partly a mirror of day D's return,
so a test that used it to explain day D would be measuring its own reflection
and would look wonderful.

Order matters, as with the other files. The five hypotheses below, their
single option setup and their verdict rule were written into this file before
any of them had been computed. They are not to be edited after a result
exists; a changed idea is a new test with a new name, and it raises the bar
for every other test in the project.
"""

import hashlib
import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from stats.bootstrap import difference_ci, mean_ci
from stats.multiple_comparisons import required_t
from storage import news_tone_db
from market_data.gdelt import QUERY_SET

from .hypothesis_log import log_run
from .pattern_options import (LOT_SIZE, MIN_HOLDOUT_TRADES, OPTIONS_START, SPLIT_DATE,
                              _baseline, _dev, _holdout, _rupees, _run, _summarise)
from .strategies import load_daily_data
from .structural_research import non_overlapping, weighted_welch
from .walkforward import holdout_verdict

RESEARCH_PATH = Path(__file__).parent.parent / "data" / "news_research.json"
MIN_DTE = 7
# Every hypothesis judged on the holdout across the project: 19 patterns,
# the IV filter, the six structural, and these five.
TESTS_IN_FAMILY = 31
# Percentile cut for "unusually" high or low, measured against a trailing
# year of tone so the threshold is one that was knowable at the time.
EXTREME_PCT = 10
TRAILING_DAYS = 252


# --- fixed before any result was computed; do not edit after seeing one ------
PREREGISTERED = {
    "registered": "2026-09-24, before any of these five hypotheses had been computed",
    "data": (
        "GDELT Doc API daily average tone for the frozen query "
        f"'{QUERY_SET}', 2018-01-01 onward. Tone is a property of the coverage, not of the market: "
        "roughly positive minus negative language across every matching article that UTC day."),
    "already_seen": (
        "Before registering, these results were known: the 26 patterns' option verdicts (all REJECTED), the six "
        "structural hypotheses (all REJECTED), the 22 replications on other indices (all REJECTED), and that "
        "GDELT returns a full daily tone series for every month sampled from 2018 to 2026 with values ranging "
        "about -3.7 to +2.0. No conditional return, and no relationship between tone and any NIFTY move, had "
        "been computed for any hypothesis below."),
    "alignment": (
        "A signal is read off a completed UTC day D and entered at the close of the first Indian session after D. "
        "A UTC day ends at 05:29 IST, before the next session opens, so nothing uses information from the session "
        "it trades. Tone from the session being traded is never used."),
    "trade": (
        "Buy one at-the-money option (the strike nearest spot at the entry close), on the nearest expiry at least "
        "7 calendar days after entry, with open interest of at least 1,000 at entry. Sold at the close a fixed "
        "number of sessions later. The options cost model is applied (about 3.3% of premium per round trip). "
        "Result in rupees per lot at today's lot size of 65. One setup per hypothesis: nothing is chosen from a "
        "grid, and no hypothesis gets a second hold length."),
    "thresholds": (
        f"'Unusually high' and 'unusually low' mean the top or bottom {EXTREME_PCT}% of the trailing "
        f"{TRAILING_DAYS} UTC days of tone, computed from days strictly before the signal day. A fixed number "
        "would have been chosen with hindsight; a trailing percentile is one the day itself could have known."),
    "overlap": "Once a trade is open, further signals are ignored until it closes, across both legs.",
    "periods": (
        "Development: trades that exit before 2024-01-01. Holdout: trades entered on or after 2024-01-01. "
        "Trades straddling the split are dropped."),
    "baseline": (
        "Buying the same at-the-money option on a fixed schedule — every hold+1 sessions — with no signal, over "
        "the same period. For a hypothesis with both legs, each leg's baseline is weighted by that leg's share "
        "of the signal trades."),
    "verdict": (
        "The project's ladder (walkforward.holdout_verdict): profitable in both periods, better than the baseline "
        "in both periods, then a holdout t above the bar, then at least 15 holdout trades for APPROVED. t is "
        f"Welch's. The bar is the Bonferroni line for {TESTS_IN_FAMILY} hypotheses judged on the holdout from "
        "Student's t at the hypothesis's own holdout trades minus one."),
    "hypotheses": {
        "tone_capitulation": {
            "family": "sentiment extreme",
            "leg": "CE",
            "hold_sessions": 5,
            "signal": (
                "The 20-day mean of daily tone, ending on UTC day D, is in the bottom 10% of its trailing 252-day "
                "distribution. Buy a call."),
            "why": (
                "Sustained bleak coverage is the closest thing a news series has to capitulation. If pessimism "
                "overshoots what then happens, a call bought into it is the buyer's side of that gap."),
        },
        "tone_euphoria": {
            "family": "sentiment extreme",
            "leg": "PE",
            "hold_sessions": 5,
            "signal": (
                "The 20-day mean of daily tone, ending on UTC day D, is in the top 10% of its trailing 252-day "
                "distribution. Buy a put."),
            "why": (
                "The mirror of capitulation, and the one an option buyer is usually punished for: if uniformly "
                "positive coverage marks a crowded tape, a put is the cheap side. If it does not, this fails and "
                "says the trend is worth more than the mood."),
        },
        "tone_shock_down": {
            "family": "sentiment change",
            "leg": "PE",
            "hold_sessions": 3,
            "signal": (
                "The one-day change in tone from UTC day D-1 to D is in the bottom 10% of its trailing 252-day "
                "distribution. Buy a put."),
            "why": (
                "A level says how the market is usually written about; a sharp change says something happened. "
                "A collapse in tone over a single day is news arriving, and news arriving is when an option "
                "buyer's volatility is worth paying for."),
        },
        "tone_shock_up": {
            "family": "sentiment change",
            "leg": "CE",
            "hold_sessions": 3,
            "signal": (
                "The one-day change in tone from UTC day D-1 to D is in the top 10% of its trailing 252-day "
                "distribution. Buy a call."),
            "why": "The other side of the same idea, registered so that a one-sided result cannot be mistaken for a general one.",
        },
        "tone_price_divergence": {
            "family": "news against price",
            "leg": "CE",
            "hold_sessions": 5,
            "signal": (
                "Tone on UTC day D is above its own 20-day mean while NIFTY's return over the 5 sessions ending "
                "on or before D is negative. Buy a call."),
            "why": (
                "The one case where tone might carry something price does not already show: the press turning "
                "constructive while the index is still falling. If coverage leads, this is where it would show; "
                "if it merely describes, this fails like the rest."),
        },
    },
}

LABELS = {
    "tone_capitulation": "Bleak coverage (call)",
    "tone_euphoria": "Glowing coverage (put)",
    "tone_shock_down": "Tone collapses in a day (put)",
    "tone_shock_up": "Tone jumps in a day (call)",
    "tone_price_divergence": "Press turns up while price falls (call)",
}

PREREG_HASH = hashlib.sha256(
    json.dumps(PREREGISTERED, sort_keys=True).encode("utf-8")).hexdigest()[:16]


# --- the tone series ---------------------------------------------------------

def load_tone() -> pd.Series:
    """Daily tone by UTC date, oldest first. Empty if never backfilled."""
    rows = news_tone_db.series(QUERY_SET)
    dates = [d for d in sorted(rows) if rows[d]["tone"] is not None]
    if not dates:
        return pd.Series(dtype=float)
    return pd.Series([float(rows[d]["tone"]) for d in dates], index=dates, dtype=float)


def _trailing_extreme(series: pd.Series, side: str, pct: int = EXTREME_PCT,
                      trailing: int = TRAILING_DAYS) -> list[str]:
    """Dates whose value is beyond the `pct` percentile of the `trailing`
    values *strictly before* that date.

    Strictly before, so the day never helps set the threshold it is then
    judged against — the small version of the same mistake as testing on
    the data a rule was chosen from.
    """
    series = series.dropna()
    if len(series) <= trailing:
        return []
    values, index, out = series.to_numpy(), list(series.index), []
    import numpy as np

    for i in range(trailing, len(values)):
        window = values[i - trailing:i]
        threshold = float(np.percentile(window, pct if side == "low" else 100 - pct))
        v = float(values[i])
        if (side == "low" and v <= threshold) or (side == "high" and v >= threshold):
            out.append(index[i])
    return out


def all_signals(symbol: str = "^NSEI") -> dict[str, list[tuple[str, str]]]:
    """Every hypothesis's signal dates, as (Indian session date, CE|PE).

    A signal date is a *session*: the trade enters at the close of the one
    after it, which is where the look-ahead rule is satisfied. A UTC day
    that is not a trading session is dropped rather than shifted, because
    shifting it would invent a signal on a day the rule did not fire.
    """
    tone = load_tone()
    if tone.empty:
        return {name: [] for name in PREREGISTERED["hypotheses"]}

    df, _ = load_daily_data(symbol, 7000)
    sessions = {str(d.date()) for d in df.index}
    closes = pd.Series(df["close"].to_numpy(), index=[str(d.date()) for d in df.index], dtype=float)

    mean20 = tone.rolling(20).mean()
    change = tone.diff()

    def on_sessions(dates: list[str], leg: str) -> list[tuple[str, str]]:
        return [(d, leg) for d in dates if d in sessions]

    # Divergence: tone above its own 20-day mean while the index has been
    # falling over the 5 sessions ending on or before that day.
    ret5 = closes.pct_change(5)
    divergence = []
    for d in tone.index:
        if d not in sessions or pd.isna(mean20.get(d, float("nan"))):
            continue
        r = ret5.get(d)
        if r is not None and not pd.isna(r) and r < 0 and tone[d] > mean20[d]:
            divergence.append(d)

    return {
        "tone_capitulation": on_sessions(_trailing_extreme(mean20, "low"), "CE"),
        "tone_euphoria": on_sessions(_trailing_extreme(mean20, "high"), "PE"),
        "tone_shock_down": on_sessions(_trailing_extreme(change, "low"), "PE"),
        "tone_shock_up": on_sessions(_trailing_extreme(change, "high"), "CE"),
        "tone_price_divergence": [(d, "CE") for d in divergence],
    }


# --- testing -----------------------------------------------------------------

def _period(trades_by_leg: dict, ctx, period_days: list[str], hold: int, pick) -> dict:
    trades = {k: pick(v) for k, v in trades_by_leg.items()}
    rupees = [_rupees(t) for v in trades.values() for t in v]
    legs = []
    for kind, ts in trades.items():
        base = _baseline(ctx, period_days, kind, 0.0, MIN_DTE, hold)
        legs.append((len(ts), base["rupees"]))
    t, base_mean = weighted_welch(rupees, legs)
    summary = _summarise([x for v in trades.values() for x in v])
    summary["by_leg"] = {k: len(v) for k, v in trades.items()}
    summary["ci_95"] = mean_ci(rupees)
    summary["edge_ci_95"] = difference_ci(rupees, legs[0][1]) if len(legs) == 1 else None
    return {"summary": summary, "rupees": rupees, "t": t,
            "baseline_avg_profit_per_lot_rs": round(base_mean) if base_mean is not None else None}


def test_hypothesis(name: str, signals: list[tuple[str, str]], ctx) -> dict:
    spec = PREREGISTERED["hypotheses"][name]
    hold = spec["hold_sessions"]
    df, spot, td = ctx
    signals = [s for s in signals if s[0] >= OPTIONS_START]
    taken = non_overlapping(signals, td, hold)

    trades_by_leg = {}
    for kind in ("CE", "PE"):
        dates = [d for d, k in taken if k == kind]
        if dates:
            trades_by_leg[kind] = _run(dates, ctx, kind, 0.0, MIN_DTE, hold)

    all_days = [d for d in td if d >= OPTIONS_START]
    dev = _period(trades_by_leg, ctx, [d for d in all_days if d < SPLIT_DATE], hold, _dev)
    hol = _period(trades_by_leg, ctx, [d for d in all_days if d >= SPLIT_DATE], hold, _holdout)
    n = hol["summary"]["num_trades"]
    bar = required_t(TESTS_IN_FAMILY, df=n - 1) if n >= 2 else None
    status, reason = holdout_verdict(
        dev["summary"].get("avg_profit_per_lot_rs") or 0, hol["summary"].get("avg_profit_per_lot_rs") or 0,
        dev["baseline_avg_profit_per_lot_rs"] or 0, hol["baseline_avg_profit_per_lot_rs"] or 0,
        n, MIN_HOLDOUT_TRADES, "long", hol["t"], min_t=bar,
        baseline_label="buying the same at-the-money option with no signal", unit="₹")
    log_run(f"news_{name}", {"hold": hold, "atm": True, "min_dte": MIN_DTE,
                             "query_set": QUERY_SET, "prereg": PREREG_HASH},
            "^NSEI", 0, {"num_trades": n, "expectancy_pct": hol["summary"].get("avg_return_pct")})

    years = max((pd.Timestamp(td[-1]) - pd.Timestamp(OPTIONS_START)).days / 365.25, 1e-9)
    return {
        "name": name, "label": LABELS[name], "family": spec["family"], "leg": spec["leg"],
        "signal": spec["signal"], "why": spec["why"], "hold_sessions": hold,
        "signals_since_2018": len(signals), "trades_taken": len(taken),
        "signals_per_year": round(len(signals) / years, 1),
        "development": {**dev["summary"], "baseline_avg_profit_per_lot_rs": dev["baseline_avg_profit_per_lot_rs"],
                        "t": dev["t"]},
        "holdout": {**hol["summary"], "baseline_avg_profit_per_lot_rs": hol["baseline_avg_profit_per_lot_rs"],
                    "t": hol["t"]},
        "required_t": bar, "status": status, "reason": reason,
    }


def run_news_research(symbol: str = "^NSEI") -> dict:
    tone = load_tone()
    coverage = news_tone_db.coverage(QUERY_SET)
    if tone.empty:
        return {"hypotheses": [], "coverage": coverage, "prereg_hash": PREREG_HASH,
                "preregistered": PREREGISTERED, "query_set": QUERY_SET,
                "note": "No tone archive yet — run api/scripts/backfill_news_tone.py."}

    df, _ = load_daily_data(symbol, 7000)
    td = [str(d.date()) for d in df.index]
    ctx = (df, pd.Series(df["close"].to_numpy(), index=td), td)

    signals = all_signals(symbol)
    results = [test_hypothesis(name, signals[name], ctx) for name in PREREGISTERED["hypotheses"]]
    approved = [r for r in results if r["status"] == "APPROVED"]
    return {
        "computed_at": pd.Timestamp.utcnow().isoformat(),
        "query_set": QUERY_SET,
        "coverage": coverage,
        "tone_days": int(len(tone)),
        "hypotheses": results,
        "approved": len(approved),
        "tested": len(results),
        "tests_in_family": TESTS_IN_FAMILY,
        "prereg_hash": PREREG_HASH,
        "preregistered": PREREGISTERED,
        "note": ("News tone from GDELT, a free daily series going back to 2018 — which is why this could be "
                 "backtested rather than only started forward. Tone describes the coverage, not the market. A "
                 "signal is read off a completed UTC day and entered at the close of the next Indian session, so "
                 "nothing uses the session it trades. Much of a day's market coverage is about that day's move, "
                 "which is exactly why that rule is not optional."),
    }


def load_news_research() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None


def signals_on(signal_date: str, symbol: str = "^NSEI") -> dict[str, str]:
    """Which news hypotheses fired on one session, and on which side.

    Same signal functions as the research: the paper book cannot compute a
    news signal differently from the way it was tested.
    """
    return {name: kind for name, sigs in all_signals(symbol).items()
            for d, kind in sigs if d == signal_date}
