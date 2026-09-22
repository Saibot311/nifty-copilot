"""Structural hypotheses for an option BUYER — beyond textbook chart patterns.

The 26 patterns asked "does a price shape pay an option buyer?" and the
answer on 2024-26 data was no. These ask whether anything about the market's
*structure* does: how options are priced against what the index delivers,
who holds what, the calendar, and how a session treats its own opening gap.

Every trade is a BUY — a call or a put, sold back later. Nothing here writes
options (the user trades only as a buyer).

Order matters, as with the IV test. The six hypotheses below, their single
option setup and their verdict rule were written into this file before any
of them had been computed. They are not to be edited after a result exists;
a changed idea is a new test with a new name, and it raises the bar.
"""

import json
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from market_data.bar_archive import index_trading_days
from stats.multiple_comparisons import required_t
from storage.participant_oi_db import load as load_participant_oi

from .hypothesis_log import log_run
from .pattern_options import LOT_SIZE, OPTIONS_START, SPLIT_DATE, _baseline, _dev, _holdout, _run, _rupees, _summarise
from .strategies import load_daily_data
from .walkforward import holdout_verdict


# --- fixed before any result was computed; do not edit after seeing one ------
PREREGISTERED = {
    "registered": "2026-09-22, before any of these six hypotheses had been computed",
    "already_seen": (
        "Before registering, these results were known: the 26 patterns' option verdicts (all REJECTED), "
        "the IV filter test (not adopted), options priced above subsequently realised volatility on 71% of "
        "days since 2018, global cues' R-squared by year, expiry-day footprint studies, and participant "
        "positioning summaries (share of days each group was net long; median option-buyer share). None of "
        "these is a conditional return for any hypothesis below."),
    "trade": (
        "Buy one at-the-money option (the strike nearest spot at the entry close), on the nearest expiry at "
        "least 7 calendar days after entry, with open interest of at least 1,000 at entry. Bought at the "
        "close of the session after the signal day; sold at the close a fixed number of sessions later. "
        "The options cost model is applied (about 3.3% of premium per round trip). Result in rupees per "
        "lot at today's lot size of 65. One setup per hypothesis: nothing is chosen from a grid."),
    "overlap": "Once a trade is open, further signals are ignored until it closes, across both legs.",
    "periods": (
        "Development: trades that exit before 2024-01-01. Holdout: trades entered on or after 2024-01-01. "
        "Trades straddling the split are dropped."),
    "baseline": (
        "Buying the same option (same type, at the money, same expiry rule, same hold) on a fixed schedule "
        "— every hold+1 sessions — with no signal, over the same period. For a hypothesis with a call leg "
        "and a put leg, each leg's baseline is weighted by that leg's share of the signal trades."),
    "verdict": (
        "The project's ladder (walkforward.holdout_verdict): profitable in both periods, better than the "
        "baseline in both periods, then a holdout t above the bar, then at least 15 holdout trades for "
        "APPROVED. t is Welch's, with the weighted baseline's variance for two-leg hypotheses. The bar is "
        "the Bonferroni line for 26 hypotheses judged on the holdout (19 patterns, the IV filter, these "
        "six) from Student's t at the hypothesis's own holdout trades minus one."),
    "hypotheses": {
        "cheap_volatility_trend": {
            "family": "volatility pricing",
            "signal": (
                "30-day at-the-money implied volatility at the signal-day close is below NIFTY's realised "
                "volatility over the 21 sessions ending that day (root mean square of daily log returns, "
                "annualised by sqrt(252)). Direction: NIFTY's 20-session return ending that day — above zero "
                "buy a call, below zero buy a put."),
            "hold_sessions": 5,
            "why": (
                "An option buyer's standing headwind is that implied volatility usually exceeds what the "
                "index then delivers. On days options are priced below what the market has recently been "
                "delivering, that headwind should be smallest; the recent trend picks the side."),
        },
        "fii_positioning_follow": {
            "family": "positioning",
            "signal": (
                "FII index-futures long share — long contracts / (long + short) in NSE's participant-wise "
                "open interest for the signal day — ranked against the 250 sessions ending that day "
                "(needs a full 250). At or above the 90th percentile buy a call; at or below the 10th buy a put."),
            "hold_sessions": 5,
            "why": ("Foreign institutions are the largest informed participant in index futures; an extreme "
                    "in their positioning may carry information the price has not absorbed."),
        },
        "retail_positioning_fade": {
            "family": "positioning",
            "signal": (
                "The same measure for Client (mostly individuals). At or above the 90th percentile buy a put; "
                "at or below the 10th buy a call."),
            "hold_sessions": 5,
            "why": ("Derivatives are zero-sum before costs and SEBI finds most individuals lose, so an extreme "
                    "in retail positioning may mark the side to be against. Largely the mirror of the FII test "
                    "(the four groups net to zero), so the two are correlated; Bonferroni is conservative about that."),
        },
        "turn_of_month": {
            "family": "calendar",
            "signal": ("The third-last session of each calendar month, so the call is bought at the close of the "
                       "second-last session and sold at the close of the second session of the next month."),
            "hold_sessions": 3,
            "why": ("The turn-of-the-month effect (Ariel 1987; Lakonishok and Smidt 1988), usually attributed to "
                    "month-start flows — in India, SIP debits cluster in the first days of the month."),
        },
        "pre_holiday": {
            "family": "calendar",
            "signal": ("The third session before a weekday exchange holiday, so the call is bought at the close two "
                       "sessions before the holiday and sold at the close of the last session before it. A holiday "
                       "is a weekday with no NIFTY session; NSE publishes these a year ahead, so the date is known "
                       "in advance and this uses no future information."),
            "hold_sessions": 1,
            "why": "The pre-holiday effect (Ariel 1990; Kim and Park 1994).",
        },
        "absorbed_gap": {
            "family": "overnight vs intraday",
            "signal": (
                "NIFTY opens at least 0.75% below the previous close and closes above its own open: buy a call. "
                "Opens at least 0.75% above the previous close and closes below its open: buy a put."),
            "hold_sessions": 3,
            "why": ("A large gap that the session then pushes back against suggests the gap overshot — the "
                    "overnight move priced news the day's trading did not accept."),
        },
    },
    "if_passed": ("A candidate for the recommendation gate, shown as such. Wiring it in is a separate, stated step."),
    "if_failed": "It stays in the record as a rejected hypothesis, and it still counts toward the bar.",
}
TESTS_IN_FAMILY = 26
MIN_HOLDOUT_TRADES = 15
MIN_DTE = 7
# -----------------------------------------------------------------------------

RESEARCH_PATH = Path(__file__).parent.parent / "data" / "structural_research.json"

LABELS = {
    "cheap_volatility_trend": "Cheap options, follow the trend",
    "fii_positioning_follow": "Follow FII futures positioning",
    "retail_positioning_fade": "Fade retail futures positioning",
    "turn_of_month": "Turn of the month",
    "pre_holiday": "Day before a holiday",
    "absorbed_gap": "Opening gap pushed back",
}

RV_WINDOW = 21
TREND_WINDOW = 20
OI_WINDOW = 250
OI_HIGH, OI_LOW = 90, 10
GAP_PCT = 0.75


# --- signals: each returns [(signal_date, "CE"|"PE")], using data up to that date only

def cheap_volatility_trend(df: pd.DataFrame, iv: pd.Series) -> list[tuple[str, str]]:
    close = df["close"]
    r = np.log(close / close.shift(1))
    rv = np.sqrt(252 * (r ** 2).rolling(RV_WINDOW, min_periods=RV_WINDOW).mean())
    trend = close / close.shift(TREND_WINDOW) - 1
    out = []
    for ts in df.index:
        d = str(ts.date())
        v, realised, tr = iv.get(d), rv.get(ts), trend.get(ts)
        if v is None or pd.isna(v) or pd.isna(realised) or pd.isna(tr) or tr == 0:
            continue
        if v < realised:
            out.append((d, "CE" if tr > 0 else "PE"))
    return out


def trailing_percentile(s: pd.Series, window: int = OI_WINDOW) -> pd.Series:
    """Each day ranked against itself and the window-1 days before it — never after."""
    return s.rolling(window, min_periods=window).apply(lambda w: (w <= w[-1]).mean() * 100, raw=True)


def long_share(rows: list[dict], participant: str) -> pd.Series:
    by_day = {r["trade_date"]: r for r in rows if r["participant"] == participant}
    s = {d: r["fut_idx_long"] / (r["fut_idx_long"] + r["fut_idx_short"])
         for d, r in by_day.items() if (r["fut_idx_long"] + r["fut_idx_short"]) > 0}
    return pd.Series(s).sort_index()


def positioning(rows: list[dict], participant: str, high_side: str) -> list[tuple[str, str]]:
    pct = trailing_percentile(long_share(rows, participant))
    low_side = "PE" if high_side == "CE" else "CE"
    return [(d, high_side if p >= OI_HIGH else low_side) for d, p in pct.items()
            if not pd.isna(p) and (p >= OI_HIGH or p <= OI_LOW)]


def turn_of_month(td: list[str]) -> list[tuple[str, str]]:
    """The third-last session of every month whose last session is known.
    The month still in progress is excluded: its last session hasn't happened."""
    months: dict[str, list[str]] = {}
    for d in td:
        months.setdefault(d[:7], []).append(d)
    last_month = td[-1][:7]
    return [(days[-3], "CE") for m, days in months.items() if m != last_month and len(days) >= 3]


def weekday_holidays(sessions: set[str], start: str, end: str) -> list[str]:
    d, stop, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= stop:
        if d.weekday() < 5 and d.isoformat() not in sessions:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def pre_holiday(td: list[str], holidays: list[str]) -> list[tuple[str, str]]:
    out = set()
    for h in holidays:
        before = [i for i, d in enumerate(td) if d < h]
        if len(before) < 3:
            continue
        out.add(td[before[-1] - 2])
    return [(d, "CE") for d in sorted(out)]


def absorbed_gap(df: pd.DataFrame) -> list[tuple[str, str]]:
    gap = (df["open"] / df["close"].shift(1) - 1) * 100
    out = []
    for ts, g in gap.items():
        if pd.isna(g):
            continue
        o, c = df.at[ts, "open"], df.at[ts, "close"]
        if g <= -GAP_PCT and c > o:
            out.append((str(ts.date()), "CE"))
        elif g >= GAP_PCT and c < o:
            out.append((str(ts.date()), "PE"))
    return out


# --- testing -----------------------------------------------------------------

def non_overlapping(signals: list[tuple[str, str]], td: list[str], hold: int) -> list[tuple[str, str]]:
    idx = {d: i for i, d in enumerate(td)}
    out, next_ok = [], -1
    for d, kind in sorted(s for s in signals if s[0] in idx):
        i = idx[d]
        if i >= next_ok:
            out.append((d, kind))
            next_ok = i + hold + 1
    return out


def weighted_welch(signal: list[float], legs: list[tuple[int, list[float]]]) -> tuple[float | None, float | None]:
    """t of the signal trades against a baseline built from each leg's
    no-signal trades, leg weighted by its share of the signal trades.
    One leg reduces to Welch's t. Returns (t, weighted baseline mean)."""
    legs = [(n, b) for n, b in legs if n > 0]
    total = sum(n for n, _ in legs)
    if len(signal) < 2 or not legs or any(len(b) < 2 for _, b in legs):
        return None, None
    base_mean = sum(n / total * statistics.mean(b) for n, b in legs)
    base_var = sum((n / total) ** 2 * statistics.variance(b) / len(b) for n, b in legs)
    se = math.sqrt(statistics.variance(signal) / len(signal) + base_var)
    if se == 0:
        return None, base_mean
    return round((statistics.mean(signal) - base_mean) / se, 2), base_mean


def _period(trades_by_leg: dict, ctx, period_days: list[str], hold: int, pick) -> dict:
    trades = {k: pick(v) for k, v in trades_by_leg.items()}
    rupees = [_rupees(t) for v in trades.values() for t in v]
    legs = []
    for kind, ts in trades.items():
        base = _baseline(ctx, period_days, kind, 0.0, MIN_DTE, hold)
        legs.append((len(ts), base["rupees"]))
    t, base_mean = weighted_welch(rupees, legs)
    summary = _summarise([t_ for v in trades.values() for t_ in v])
    summary["by_leg"] = {k: len(v) for k, v in trades.items()}
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
        dev["baseline_avg_profit_per_lot_rs"] if dev["baseline_avg_profit_per_lot_rs"] is not None else 0,
        hol["baseline_avg_profit_per_lot_rs"] if hol["baseline_avg_profit_per_lot_rs"] is not None else 0,
        n, MIN_HOLDOUT_TRADES, "long", hol["t"], min_t=bar,
        baseline_label="buying the same at-the-money option with no signal", unit="₹")
    log_run(f"structural_{name}", {"hold": hold, "atm": True, "min_dte": MIN_DTE, "prereg": PREREG_HASH},
            "^NSEI", 0, {"num_trades": n, "expectancy_pct": hol["summary"].get("avg_return_pct")})
    return {
        "name": name, "label": LABELS[name], "family": spec["family"], "signal": spec["signal"], "why": spec["why"], "hold_sessions": hold,
        "signals_since_2018": len(signals), "trades_taken": len(taken),
        "signals_per_year": round(len(signals) / max((pd.Timestamp(td[-1]) - pd.Timestamp(OPTIONS_START)).days / 365.25, 1e-9), 1),
        "development": {**dev["summary"], "baseline_avg_profit_per_lot_rs": dev["baseline_avg_profit_per_lot_rs"], "t": dev["t"]},
        "holdout": {**hol["summary"], "baseline_avg_profit_per_lot_rs": hol["baseline_avg_profit_per_lot_rs"], "t": hol["t"]},
        "required_t": bar, "status": status, "reason": reason,
    }


# --- descriptions (no hypotheses) ---------------------------------------------

def overnight_vs_intraday(df: pd.DataFrame, since: str = "2015-01-01") -> dict:
    """Where NIFTY's move happened: previous close to open, or open to close."""
    x = df[df.index >= since]
    on = np.log(x["open"] / x["close"].shift(1)).dropna()
    intra = np.log(x["close"] / x["open"]).loc[on.index]
    years = {}
    for y in sorted({ts.year for ts in on.index}):
        m = on.index.year == y
        years[str(y)] = {"overnight_pct": round(100 * (math.exp(on[m].sum()) - 1), 1),
                         "intraday_pct": round(100 * (math.exp(intra[m].sum()) - 1), 1)}
    return {"since": str(on.index[0].date()), "sessions": len(on),
            "overnight_total_pct": round(100 * (math.exp(on.sum()) - 1), 1),
            "intraday_total_pct": round(100 * (math.exp(intra.sum()) - 1), 1),
            "overnight_up_share": round(float((on > 0).mean()), 3),
            "intraday_up_share": round(float((intra > 0).mean()), 3),
            "by_year": years,
            "note": ("Compounded index moves, before costs. An option bought and sold at closes holds both parts; "
                     "the options archive has no opening premiums, so the overnight part alone cannot be bought "
                     "in this data.")}


def run_structural_research(symbol: str = "^NSEI") -> dict:
    from .iv_research import load_series
    df, _ = load_daily_data(symbol, 7000)
    td = [str(d.date()) for d in df.index]
    ctx = (df, pd.Series(df["close"].values, index=td), td)

    iv = load_series()
    iv30 = iv["iv_30d"] if not iv.empty else pd.Series(dtype=float)  # a fraction, like realised vol
    sessions, archive_last = index_trading_days(symbol)
    holidays = weekday_holidays(sessions, OPTIONS_START, archive_last) if archive_last else []
    oi = load_participant_oi()

    signals = {
        "cheap_volatility_trend": cheap_volatility_trend(df, iv30),
        "fii_positioning_follow": positioning(oi, "FII", "CE"),
        "retail_positioning_fade": positioning(oi, "Client", "PE"),
        "turn_of_month": turn_of_month(td),
        "pre_holiday": pre_holiday(td, holidays),
        "absorbed_gap": absorbed_gap(df),
    }
    results = [test_hypothesis(name, sigs, ctx) for name, sigs in signals.items()]
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "preregistered": PREREGISTERED, "prereg_hash": PREREG_HASH,
        "period": {"start": OPTIONS_START, "split": SPLIT_DATE, "end": td[-1]},
        "lot_size": LOT_SIZE, "tests_in_family": TESTS_IN_FAMILY,
        "hypotheses": results,
        "descriptions": {"overnight_vs_intraday": overnight_vs_intraday(df),
                         "weekday_holidays_used": len(holidays)},
    }


def load_structural_research() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None


PREREG_HASH = "6f8cf90f4c351b4a"


def holdout_tests_judged(pattern_research: dict | None) -> int:
    """How many hypotheses have had their one look at the 2024-26 holdout —
    the count the evidence bar is corrected for (I5). Every pattern with
    holdout trades, the pre-registered IV filter, and these six once run.
    A new family of tests raises the bar for all of them, patterns included."""
    patterns = sum(1 for p in (pattern_research or {}).get("patterns", []) if (p.get("holdout") or {}).get("num_trades"))
    from .iv_research import load_iv_research
    iv = 1 if load_iv_research() else 0
    structural = len((load_structural_research() or {}).get("hypotheses", []))
    return patterns + iv + structural
