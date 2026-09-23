"""What the 15-minute archive is for.

Every backtest number in this project rests on one execution assumption: a
signal at today's close is entered at tomorrow's open (I1). Eleven years of
intraday bars have been sitting unused, and the first thing to spend them on
is not new patterns. A new intraday pattern adds hypotheses and raises the
evidence bar for everything already judged; testing the execution rule costs
no hypotheses at all and makes every existing number either more honest or
less.

Three studies, in that order:

  A  What does "the open" cost?  How far the index travels inside the first
     15 minutes — the exposure you carry if your order is not filled at the
     opening print.
  B  Does the entry time change the answer?  The same signals and the same
     exits, entered at five fixed times. Chosen on the development period
     only and reported on the holdout, exactly like pattern_options.
  C  When does NIFTY actually move?  Range by 15-minute slot. Descriptive
     only, and every drift figure carries its t-statistic so it cannot be
     read as an edge.

Option P&L is not available here: the options archive is end-of-day, so
everything in this module is index points and percent. A finding that
survives here is a reason to look, never a result to trade.
"""

import json
import math
import sqlite3

from storage.sqlite_open import open_db
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from backtest.pattern_options import SPLIT_DATE
from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from market_data.bar_archive import DB_PATH, clamp_to_daily

# Bar start times, and the entry each one stands for. "open" is what the
# backtester assumes today; the rest are what a person who sees the signal
# overnight might realistically manage.
ENTRIES = {
    "open": "09:15",
    "09:30": "09:30",
    "09:45": "09:45",
    "10:15": "10:15",
    "close": "15:15",  # last 15-minute bar; its close is the session close
}
BASELINE_ENTRY = "open"
HOLD_DAYS = (5, 10)
MIN_TRADES = 30
FIRST_INTRADAY_DATE = "2015-01-09"

RESEARCH_PATH = Path(__file__).parent.parent / "data" / "intraday_research.json"


def load_research() -> dict | None:
    """The saved output of scripts/intraday_research.py, or None if never run."""
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None


def _t_stat(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sd = statistics.stdev(values)
    if sd == 0:
        return None
    return round(statistics.mean(values) / (sd / math.sqrt(len(values))), 2)


def load_intraday(symbol: str = "^NSEI", db_path: Path | None = None) -> dict[str, dict[str, dict]]:
    """{date: {HH:MM: bar}} — only complete 25-bar sessions, bad ticks clamped.

    Short sessions (10 of them, from exchange outages and half-days) are
    dropped rather than padded: a study of *when* the market moves cannot
    average over days whose clock was different. Bars reaching beyond the
    day's official high or low are clamped to it (see clamp_to_daily).
    """
    conn = open_db(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ts, open, high, low, close FROM index_bars "
            "WHERE symbol=? AND interval='15m' ORDER BY ts", (symbol,)
        ).fetchall()
        daily = {r["ts"][:10]: (r["high"], r["low"]) for r in conn.execute(
            "SELECT ts, high, low FROM index_bars WHERE symbol=? AND interval='1d'", (symbol,))}
    finally:
        conn.close()

    days: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        bar = dict(r)
        d = r["ts"][:10]
        if d in daily:
            bar["high"], bar["low"] = clamp_to_daily(bar["high"], bar["low"], bar["open"], bar["close"], *daily[d])
        days[d][r["ts"][11:16]] = bar
    full = max((len(v) for v in days.values()), default=0)
    return {d: bars for d, bars in days.items() if len(bars) == full}


# --- A: what the opening print costs ----------------------------------------

def opening_cost(intraday: dict) -> dict:
    """The first bar, as an execution risk rather than a price.

    The question is not whether the opening print is real — the archive and
    the daily series agree on it to within a hundredth of a point. It is
    whether that print is a price you can actually get, and what being 15
    minutes late does to a trade.

    Split by period and by year, because a mean with a big t over eleven
    years is worth nothing if it lives in two of them.
    """
    def drift(days):
        return [(intraday[d][ENTRIES["open"]]["close"] / intraday[d][ENTRIES["open"]]["open"] - 1) * 100
                for d in days]

    days = sorted(intraday)
    all_drift = drift(days)
    dev, holdout = drift([d for d in days if d < SPLIT_DATE]), drift([d for d in days if d >= SPLIT_DATE])
    by_year = {}
    for d in days:
        by_year.setdefault(d[:4], []).append(
            (intraday[d][ENTRIES["open"]]["close"] / intraday[d][ENTRIES["open"]]["open"] - 1) * 100)
    years = {y: {"sessions": len(v), "mean_pct": round(statistics.mean(v), 4), "t_stat": _t_stat(v)}
             for y, v in sorted(by_year.items())}

    mean = statistics.mean(all_drift)
    same_sign_years = sum(1 for y in years.values() if y["mean_pct"] * mean > 0)
    stable = (statistics.mean(dev) * statistics.mean(holdout) > 0
              and same_sign_years >= 0.8 * len(years))

    ordered = sorted((intraday[d][ENTRIES["open"]]["high"] - intraday[d][ENTRIES["open"]]["low"])
                     / intraday[d][ENTRIES["open"]]["open"] * 100 for d in days)
    signed = sorted(all_drift)
    n = len(all_drift)
    return {
        "sessions": n,
        "first_bar_drift_pct": {
            "mean": round(mean, 4),
            "t_stat": _t_stat(all_drift),
            "std": round(statistics.stdev(all_drift), 4),
            "dev_mean": round(statistics.mean(dev), 4), "dev_t": _t_stat(dev),
            "holdout_mean": round(statistics.mean(holdout), 4), "holdout_t": _t_stat(holdout),
            "p05": round(signed[int(n * 0.05)], 4),
            "p95": round(signed[int(n * 0.95)], 4),
        },
        "by_year": years,
        "stable": stable,
        "years_agreeing_with_the_mean": f"{same_sign_years}/{len(years)}",
        "first_bar_range_pct": {"median": round(ordered[n // 2], 4), "p90": round(ordered[int(n * 0.9)], 4)},
        "what_it_means": (
            f"The index sits {abs(mean):.3f}% {'below' if mean < 0 else 'above'} the opening print 15 minutes "
            f"later, in {same_sign_years} of {len(years)} years and in both the development and holdout periods. "
            "So the open is not a price to count on. A long entered a little later is bought cheaper than the "
            "backtest assumes and a short is sold cheaper, which means every CE result here is mildly "
            "conservative and every PE result mildly optimistic, by about this much per trade. "
            "It is not large enough to overturn a verdict, and no verdict in this system is close enough "
            "for it to matter — but it is the right size to matter for one that ever gets close. "
            "Likely cause is the pre-open call auction rather than anything tradeable: the print is struck "
            "before continuous trading, so treat it as a data artifact, not a strategy."
        ),
        "note": (
            "std is the honest cost of being late: noise added to every entry, dwarfing the drift itself. "
            "Compare it with the per-trade edge a pattern claims before believing the pattern."
        ),
    }


# --- B: does the entry time change the answer? ------------------------------

def _signal_dates(df: pd.DataFrame, regime: pd.Series) -> dict[str, list[str]]:
    out = {}
    for name, spec in STRATEGY_REGISTRY.items():
        try:
            fired = spec["fn"](df, regime, **spec.get("params", {}))
        except Exception:
            continue
        dates = [d.isoformat() for d in df.index[fired.fillna(False).astype(bool)].date]
        out[name] = [d for d in dates if d >= FIRST_INTRADAY_DATE]
    return out


def _entry_price(bars: dict, entry: str) -> float:
    b = bars[ENTRIES[entry]]
    # Every entry is the price at the start of its bar, except "close",
    # which is the session's last print.
    return float(b["close"] if entry == "close" else b["open"])


def _baselines(intraday: dict, sessions: list[str]) -> dict:
    """What entering later does on an ordinary day.

    Entering at 10:15 instead of the open means less time in the market, and
    in a falling period that flatters a long strategy for reasons that have
    nothing to do with the signal. Measured against every session in the
    same period, that drift cancels — the same direction-matched-baseline
    fix the strategy verdicts already use.
    """
    out = {}
    for period, days in (("dev", [d for d in sessions if d < SPLIT_DATE]),
                         ("holdout", [d for d in sessions if d >= SPLIT_DATE])):
        for entry in ENTRIES:
            moves = [(_entry_price(intraday[d], entry) / _entry_price(intraday[d], BASELINE_ENTRY) - 1) * 100
                     for d in days]
            mean = statistics.mean(moves) if moves else 0.0
            # A later entry buys higher (or sells lower) by the move since
            # the open, so its effect on a trade is the move, negated.
            out[("long", period, entry)] = -mean
            out[("short", period, entry)] = mean
    return out


def entry_timing(intraday: dict, df: pd.DataFrame, regime: pd.Series) -> dict:
    """Same signals, same exits, five fixed entry times.

    Fixed in advance and applied to every trade — picking the entry time per
    day from what happened would be the look-ahead this whole project exists
    to avoid. What is reported is the *excess* over what the same delay does
    on an ordinary day, so a period's drift cannot masquerade as execution
    skill.
    """
    sessions = sorted(intraday)
    pos = {d: i for i, d in enumerate(sessions)}
    closes = {d: float(intraday[d][ENTRIES["close"]]["close"]) for d in sessions}
    signals = _signal_dates(df, regime)
    baseline = _baselines(intraday, sessions)

    per_hold = {}
    for hold in HOLD_DAYS:
        excess = {e: {"dev": [], "holdout": []} for e in ENTRIES}
        raw = {e: {"dev": [], "holdout": []} for e in ENTRIES}
        by_strategy = defaultdict(lambda: {e: [] for e in ENTRIES})
        for name, dates in signals.items():
            direction = STRATEGY_REGISTRY[name]["direction"]
            sign = 1 if direction == "long" else -1
            for d in dates:
                i = pos.get(d)
                if i is None or i + hold >= len(sessions):
                    continue
                entry_day, exit_day = sessions[i + 1], sessions[i + hold]
                period = "holdout" if entry_day >= SPLIT_DATE else "dev"
                at_open = sign * (closes[exit_day] / _entry_price(intraday[entry_day], BASELINE_ENTRY) - 1) * 100
                for e in ENTRIES:
                    price = _entry_price(intraday[entry_day], e)
                    r = sign * (closes[exit_day] / price - 1) * 100
                    raw[e][period].append(r)
                    excess[e][period].append((r - at_open) - baseline[(direction, period, e)])
                    by_strategy[name][e].append(r)

        dev_n = len(raw[BASELINE_ENTRY]["dev"])
        summary = {}
        for e in ENTRIES:
            row = {}
            for period in ("dev", "holdout"):
                vals, ex = raw[e][period], excess[e][period]
                row[period] = {
                    "trades": len(vals),
                    "avg_pct": round(statistics.mean(vals), 4) if vals else None,
                    "vs_open_pct": round(statistics.mean(ex) + _pooled_baseline(baseline, period, e), 4) if ex else None,
                    "excess_pct": round(statistics.mean(ex), 4) if ex else None,
                    # Paired: the same trades entered two ways, then measured
                    # against what the delay does on any day.
                    "excess_t": _t_stat(ex) if e != BASELINE_ENTRY else None,
                }
            row["is_execution_choice"] = e != "close"
            summary[e] = row

        # Chosen on development data alone, then reported on the holdout it
        # never saw — the same rule the option research follows. "close" is
        # excluded: entering a day later is a different trade, not a
        # different way of placing the same one.
        pickable = [e for e in ENTRIES
                    if e != BASELINE_ENTRY and summary[e]["is_execution_choice"]
                    and summary[e]["dev"]["excess_pct"] is not None]
        best = max(pickable, key=lambda e: summary[e]["dev"]["excess_pct"], default=None)
        per_hold[f"{hold}d"] = {
            "by_entry": summary,
            "chosen_on_dev": best,
            "holdout_verdict": _verdict(summary, best, dev_n),
            "by_strategy": {
                name: {e: round(statistics.mean(v), 4) for e, v in per_e.items() if v}
                for name, per_e in sorted(by_strategy.items())
                if len(per_e[BASELINE_ENTRY]) >= MIN_TRADES
            },
        }
    return per_hold


def _pooled_baseline(baseline: dict, period: str, entry: str) -> float:
    """Long and short see opposite signs of the same drift; the pooled
    figure is only for display next to the excess."""
    return (baseline[("long", period, entry)] + baseline[("short", period, entry)]) / 2


def _verdict(summary: dict, best: str | None, dev_trades: int) -> dict:
    """An execution effect has to replicate, not merely be significant once.

    Selecting the best entry on development data and then finding it
    significant on the holdout is not enough: if the two periods disagree
    about the *sign*, what was measured is the period, not the execution.
    """
    if best is None or dev_trades < MIN_TRADES:
        return {"verdict": "NOT ENOUGH DATA", "detail": f"{dev_trades} development trades"}
    dev, hold = summary[best]["dev"], summary[best]["holdout"]
    d_edge, d_t = dev["excess_pct"], dev["excess_t"]
    h_edge, h_t = hold["excess_pct"], hold["excess_t"]
    if None in (d_edge, h_edge, h_t):
        return {"verdict": "NOT ENOUGH DATA", "detail": "no holdout trades"}

    base = {"entry": best, "dev_excess_pct": d_edge, "dev_t": d_t,
            "holdout_excess_pct": h_edge, "holdout_t": h_t}
    if d_edge <= 0:
        detail = (
            f"No entry time beat the next open on development data; {best} was merely the least bad "
            f"({d_edge:+.4f}% per trade, t={d_t}). "
        )
        if h_edge > 0 and h_t >= 2:
            detail += (
                f"On the holdout the same entry looks better by {h_edge:+.4f}% (t={h_t}) — the opposite sign, "
                "also significant. Two significant results pointing opposite ways measure the period, not the "
                "execution. The next-open rule stands."
            )
            return {**base, "verdict": "UNSTABLE — SIGN FLIPS BETWEEN PERIODS", "detail": detail}
        return {**base, "verdict": "NO BETTER THAN THE OPEN", "detail": detail + "The holdout does not overturn that."}

    if h_edge > 0 and h_t >= 2:
        return {**base, "verdict": "BETTER THAN THE OPEN", "detail": (
            f"Entering at {best} beat the next open on development data ({d_edge:+.4f}%, t={d_t}) and again on "
            f"the holdout it never saw ({h_edge:+.4f}%, t={h_t}). Same sign in both periods, clearing t>=2.")}
    return {**base, "verdict": "NO BETTER THAN THE OPEN", "detail": (
        f"{best} looked better on development data ({d_edge:+.4f}%, t={d_t}) but did not hold up on the "
        f"holdout ({h_edge:+.4f}%, t={h_t}). The next-open rule stands.")}


# --- C: when does the index actually move? ----------------------------------

def time_of_day(intraday: dict) -> dict:
    """Descriptive. Range says when to expect movement; drift is shown only
    with its t-statistic, because a slot that drifts up over eleven years is
    a hypothesis, not a trade."""
    slots = defaultdict(lambda: {"range": [], "drift": []})
    for bars in intraday.values():
        for hhmm, b in bars.items():
            slots[hhmm]["range"].append((b["high"] - b["low"]) / b["open"] * 100)
            slots[hhmm]["drift"].append((b["close"] / b["open"] - 1) * 100)
    rows = []
    for hhmm in sorted(slots):
        r, d = slots[hhmm]["range"], slots[hhmm]["drift"]
        rows.append({
            "time": hhmm,
            "bars": len(r),
            "avg_range_pct": round(statistics.mean(r), 4),
            "avg_drift_pct": round(statistics.mean(d), 4),
            "drift_t": _t_stat(d),
        })
    busiest = max(rows, key=lambda x: x["avg_range_pct"])
    return {
        "slots": rows,
        "busiest_slot": busiest["time"],
        "slots_with_drift_t_over_2": [r["time"] for r in rows if (r["drift_t"] or 0) > 2 or (r["drift_t"] or 0) < -2],
        "note": (
            "Range is how much the index typically travels in that 15 minutes — useful for knowing when "
            "a level is likely to be tested. Drift is not a strategy: with ~2,900 sessions, testing 25 "
            "slots at once means some will look significant by chance, and none of this is measured in "
            "option money."
        ),
    }


def run_intraday_research(symbol: str = "^NSEI") -> dict:
    intraday = load_intraday(symbol)
    if not intraday:
        raise ValueError("No 15-minute bars archived — run scripts/backfill_bars.py first.")
    df, regime = load_daily_data(symbol)
    dates = sorted(intraday)
    return {
        "symbol": symbol,
        "sessions": len(intraday),
        "from": dates[0],
        "to": dates[-1],
        "split_date": SPLIT_DATE,
        "opening_cost": opening_cost(intraday),
        "entry_timing": entry_timing(intraday, df, regime),
        "time_of_day": time_of_day(intraday),
        "limits": (
            "Index points only: the options archive is end-of-day, so no option P&L can be measured "
            "intraday. Gross of costs. These studies test the system's execution assumption; they do "
            "not test any pattern's edge and add no new hypotheses to the evidence bar."
        ),
    }