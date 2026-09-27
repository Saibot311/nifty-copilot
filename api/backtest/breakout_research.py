"""Does an afternoon move past NIFTY's morning range keep going?

An idea found by looking, not one written down first. The Trap (the course's
EURUSD strategy, adapted to NIFTY in course_strategies.py) sold a sweep of
the morning high that closed back inside, and bought the mirror; on the
2024-26 holdout it lost more than buying the same option at the same times
with no signal (t = -4.12). Read backwards: those afternoon breaks tended to
carry on. That reading was made from 2018-26 results, so 2018-26 cannot test
it — it is where it came from.

What can: 2015-17. The 5-minute archive starts in January 2015 and no study
in this project has judged anything on it. It is the one-look confirmation
period here; 2018-26 is reported as the discovery period it is. The idea has
support outside this project — intraday momentum (Gao, Han, Li & Zhou,
JFE 2018; a NIFTY 50 study of the last half hour; Zarattini, Aziz & Barbon's
2024 range-breakout work on SPY) — but those hold the index, and a bought
option pays time and costs they do not.

Two readings, both fixed before either was computed:
  H1 afternoon_breakout — the literature's version: the first afternoon
     close beyond the morning range, held to the close unless price closes
     back inside the range.
  H2 trap_reversed — the direct reverse of the rejected trade: the same
     trigger bar, the other side, the same stop and 1:3 target logic.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from quant.indicators import ema

from .course_strategies import (OptionModel, Series, _trade, baseline_sample, hm, load_bars, load_expiries,
                                run_exit, summarise)
from .hypothesis_log import log_run
from .walkforward import holdout_verdict, welch_t_stat

API_DIR = Path(__file__).parent.parent
RESEARCH_PATH = API_DIR / "data" / "breakout_research.json"

# --- fixed before any result was computed; do not edit after seeing one ------
PREREGISTERED = {
    "registered": "2026-09-27, before either hypothesis had been computed",
    "origin": (
        "Suggested by a result: the course Trap adapted to NIFTY (course_strategies.py, prereg 42e24490f0b52c4d) "
        "lost against its no-signal baseline on 2024-26 (option -5.81% vs -2.68% a trade, t -4.12, index -5.2 "
        "points a trade) and roughly matched it on 2018-23 (-2.73% vs -2.43%, t -0.48). The user asked for this "
        "idea to be researched."),
    "already_seen": (
        "The Trap's 2018-26 results above; every other course strategy's 2018-26 results; the literature named "
        "in the module docstring. The Trap's 2015-17 trades were computed and saved (course_research.json, "
        "by_year) but never printed or read. Nothing of either hypothesis below had been computed."),
    "data": ("NIFTY 50 5-minute bars (Kite archive) from 2015-01-09; India VIX daily closes (Yahoo) from 2014-12 as "
             "the volatility for the option model in every period, so all periods are priced alike; the options "
             "archive's expiry calendar from 2018, and for 2015-17 (monthly contracts only) the last Thursday of "
             "each month, moved to the session before when it was a holiday."),
    "periods": ("Confirmation (the one look, never used before): trades entered 2015-01-01 to 2017-12-31. "
                "Discovery (where the idea came from, reported, not evidence): trades entered 2018-01-01 to the "
                "archive's end, also shown split at 2024-01-01."),
    "sessions": ("Every session except an expiry session, the Trap's own days. The range is the high and low "
                 "(wicks included) of bars starting 09:15-13:10; a day whose range is under 0.09% of its low is "
                 "skipped. Entries on bars starting 13:15-15:10; anything open exits at the 15:25 bar's close."),
    "option_model": (
        "As in course_strategies.py: a call for a long, a put for a short; Black-Scholes on the index path "
        "with the previous session's India VIX close as volatility; the strike nearest spot; the nearest "
        "expiry after the entry date; the project's per-leg option costs. Index points are reported beside."),
    "baseline": ("The same option bought at each trade's clock time and held as many bars, on every other "
                 "eligible session of the same period; Welch's t against that sample."),
    "verdict": (
        "walkforward.holdout_verdict with discovery in the development seat and confirmation in the holdout "
        "seat: profitable in both, ahead of the baseline in both, a confirmation t above the Bonferroni bar "
        "for 60 hypotheses (the 58 judged plus these two) at the confirmation trades minus one, and at least "
        "15 confirmation trades."),
    "hypotheses": {
        "afternoon_breakout": {
            "label": "Afternoon break of the morning range (continuation)",
            "rules": (
                "The first 5-minute close in the entry window above the range high is a long; below the range "
                "low, a short; only the first such close in the day counts. Exit at the first later close back "
                "inside the range (at or below the high for a long, at or above the low for a short), or at "
                "the 15:25 close."),
        },
        "trap_reversed": {
            "label": "The Trap, reversed",
            "rules": (
                "The Trap's trigger unchanged: once a bar in the window trades above the range high, the first "
                "close back at or below it; the low mirrors; only the first trigger; skipped if that close is "
                "within 0.027% of the 5-minute EMA200. The trade takes the other side: long after the high is "
                "swept, short after the low. Stop beyond the last two candles' other extreme (their lower low "
                "for a long); target three times the risk."),
        },
    },
}
TESTS_IN_FAMILY = 60
MIN_CONFIRMATION_TRADES = 15
CONFIRM = (date(2015, 1, 1), date(2018, 1, 1))
DISCOVERY_START, SPLIT = date(2018, 1, 1), date(2024, 1, 1)

PREREG_HASH = "bbe333f83a7202a8"


# --- data ---------------------------------------------------------------------

def load_vix() -> dict[date, float]:
    from market_data.yfinance_provider import YFinanceProvider
    candles = YFinanceProvider().get_ohlc("^INDIAVIX", "1d", date(2014, 12, 1), date.today())
    return {date.fromisoformat(c.timestamp[:10]): c.close / 100 for c in candles if c.close}


def monthly_expiries(sessions: list[date], before: date) -> list[date]:
    """The last Thursday of each month, or the session before it when it was
    a holiday, for the months before `before`."""
    have = set(sessions)
    out = []
    months = sorted({(d.year, d.month) for d in sessions if d < before})
    for y, m in months:
        last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        thursday = last - timedelta(days=(last.weekday() - 3) % 7)
        d = thursday
        while d not in have and d.month == m:
            d -= timedelta(days=1)
        if d in have:
            out.append(d)
    return out


# --- the two -------------------------------------------------------------------

def _range(s: Series, d: date):
    b0, b1 = s.bounds[d]
    rng = [i for i in range(b0, b1 + 1) if s.hm[i] <= hm("13:10")]
    win = [i for i in range(b0, b1 + 1) if hm("13:15") <= s.hm[i] <= hm("15:10")]
    if not rng or not win or b0 < 200:
        return None
    hi, lo = s.h[rng].max(), s.l[rng].min()
    if (hi - lo) / lo * 100 < 0.09:
        return None
    return b0, b1, hi, lo, win


def afternoon_breakout(s: Series, skip: set[date]) -> list[dict]:
    trades = []
    for d in s.sessions:
        if d in skip:
            continue
        got = _range(s, d)
        if got is None:
            continue
        b0, b1, hi, lo, win = got
        for i in win:
            side = 1 if s.c[i] > hi else -1 if s.c[i] < lo else 0
            if side == 0:
                continue
            j, px, why = b1, s.c[b1], "time"
            for k in range(i + 1, b1 + 1):
                if (s.c[k] <= hi) if side > 0 else (s.c[k] >= lo):
                    j, px, why = k, s.c[k], "back inside"
                    break
            trades.append(_trade(s, i, j, side, s.c[i], px, why))
            break
    return trades


def trap_reversed(s: Series, skip: set[date]) -> list[dict]:
    e200 = ema(s.df["close"], 200).to_numpy()
    trades = []
    for d in s.sessions:
        if d in skip:
            continue
        got = _range(s, d)
        if got is None:
            continue
        b0, b1, hi, lo, win = got
        swept_hi = swept_lo = False
        for i in win:
            swept_hi |= s.h[i] > hi
            swept_lo |= s.l[i] < lo
            trap = -1 if swept_hi and s.c[i] <= hi else 1 if swept_lo and s.c[i] >= lo else 0
            if trap == 0:
                continue
            if abs(s.c[i] / e200[i] - 1) * 100 < 0.027:
                break
            side = -trap                       # the other side of the Trap
            entry = s.c[i]
            stop = min(s.l[i], s.l[i - 1]) if side > 0 else max(s.h[i], s.h[i - 1])
            risk = abs(entry - stop)
            if risk > 0:
                x, px, why = run_exit(s, i, side, entry, stop, entry + side * 3 * risk, b1)
                trades.append(_trade(s, i, x, side, entry, px, why))
            break
    return trades


# --- judging -------------------------------------------------------------------

def period_of(entry: date) -> str | None:
    if CONFIRM[0] <= entry < CONFIRM[1]:
        return "confirmation"
    return "discovery" if entry >= DISCOVERY_START else None


def judge(name: str, trades: list[dict], s: Series, model: OptionModel, eligible: set[date]) -> dict:
    from stats.multiple_comparisons import required_t

    rows = {"confirmation": [], "discovery": []}
    for t in trades:
        p = period_of(pd.Timestamp(t["entry_ts"]).date())
        if p is None:
            continue
        r = model.trade_return(name, t["side"], pd.Timestamp(t["entry_ts"]), pd.Timestamp(t["exit_ts"]),
                               t["entry"], t["exit"])
        if r:
            rows[p].append({**t, **r})

    def block(sample: list[dict], lo: date, hi: date) -> dict:
        days = sorted(d for d in eligible if lo <= d < hi)
        base = baseline_sample(name, sample, s, model, days)
        rets = [r["option_pct"] for r in sample]
        return {**summarise(rets),
                "index_points_total": round(sum(r["points"] for r in sample), 1),
                "index_points_mean": round(float(np.mean([r["points"] for r in sample])), 2) if sample else None,
                "index_win_rate": round(float(np.mean([r["points"] > 0 for r in sample])) * 100, 1) if sample else None,
                "baseline_mean_pct": round(float(np.mean(base)), 3) if base else None,
                "t_vs_baseline": welch_t_stat(rets, base) if len(rets) > 1 and len(base) > 1 else None,
                "exits": {k: sum(1 for r in sample if r["reason"] == k) for k in sorted({r["reason"] for r in sample})},
                "trades": sample}

    end = date(2100, 1, 1)
    conf = block(rows["confirmation"], *CONFIRM)
    disc = block(rows["discovery"], DISCOVERY_START, end)
    split = {"2018-23": block([r for r in rows["discovery"] if r["entry_ts"][:10] < "2024-01-01"], DISCOVERY_START, SPLIT),
             "2024-26": block([r for r in rows["discovery"] if r["entry_ts"][:10] >= "2024-01-01"], SPLIT, end)}
    n = conf.get("num_trades", 0)
    bar = required_t(TESTS_IN_FAMILY, df=n - 1) if n > 1 else None
    if n and disc.get("num_trades"):
        verdict, reason = holdout_verdict(
            disc["mean_pct"], conf["mean_pct"], disc["baseline_mean_pct"] or 0.0, conf["baseline_mean_pct"] or 0.0,
            n, MIN_CONFIRMATION_TRADES, holdout_t=conf["t_vs_baseline"], min_t=bar,
            baseline_label="the same option bought at the same times with no signal", unit="%")
        reason = reason.replace("development period", "discovery period (2018-26)").replace(
            "holdout period", "confirmation period (2015-17)").replace("holdout edge", "confirmation edge")
    else:
        verdict, reason = "REJECTED", "Too few trades in one of the periods to judge."
    for b in (conf, disc, *split.values()):
        b.pop("trades", None) if b is not disc and b is not conf else None
    return {"verdict": verdict, "reason": reason, "required_t": bar, "confirmation": conf, "discovery": disc,
            "discovery_split": split}


def run_breakout_research() -> dict:
    s = Series(load_bars("5m"))
    archive = load_expiries()
    expiries = sorted(set(monthly_expiries(s.sessions, archive[0])) | set(archive))
    exp_set = set(expiries)
    eligible = set(s.sessions) - exp_set
    model = OptionModel(s.sessions, expiries, load_vix())
    results = {}
    for name, fn in (("afternoon_breakout", afternoon_breakout), ("trap_reversed", trap_reversed)):
        v = judge(name, fn(s, exp_set), s, model, eligible)
        v["label"] = PREREGISTERED["hypotheses"][name]["label"]
        results[name] = v
        c = v["confirmation"]
        log_run(f"breakout_{name}", {"prereg": PREREG_HASH, "period": "confirmation 2015-17"}, "^NSEI", 0,
                {"num_trades": c.get("num_trades"), "expectancy_pct": c.get("mean_pct")})
    out = {"computed_at": datetime.now().isoformat(timespec="seconds"), "prereg_hash": PREREG_HASH,
           "preregistered": PREREGISTERED, "tests_in_family": TESTS_IN_FAMILY,
           "hypotheses": [{"name": k, **v} for k, v in results.items()]}
    RESEARCH_PATH.write_text(json.dumps(out, default=str))
    return out


def load_breakout_research() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None
