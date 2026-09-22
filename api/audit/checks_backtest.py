"""Phases 6-8: the backtest engine, the research, and the validation.

This is where a number becomes a verdict, so it is where a quiet error does
the most damage. The research does not store individual trades, so the
checks re-run each pattern's chosen option setup with trade-level detail and
inspect every trade.
"""

import math
import random
import statistics
from functools import lru_cache
from statistics import NormalDist

import pandas as pd

from backtest.costs import CostModel
from backtest.engine import run_backtest
from backtest.options_engine import OptionsCostModel
from backtest.pattern_options import (MIN_HOLDOUT_TRADES, SPLIT_DATE, _run, _rupees, load_research)
from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from stats import student_t

from . import FAIL, PASS, WARN, Result, check


@lru_cache(maxsize=1)
def _data():
    df, regime = load_daily_data("^NSEI", 7000)
    td = [str(d.date()) for d in df.index]
    return df, regime, (df, pd.Series(df["close"].values, index=td), td)


@lru_cache(maxsize=1)
def _chosen_trades() -> dict:
    """Every researched pattern's chosen option setup, re-run trade by trade."""
    from backtest.pattern_options import OPTIONS_START, _non_overlapping
    df, regime, ctx = _data()
    td = ctx[2]
    out = {}
    for p in (load_research() or {}).get("patterns", []):
        opt = p.get("suggested_option")
        if not opt:
            continue
        spec = STRATEGY_REGISTRY[p["strategy"]]
        entries = spec["fn"](df, regime, **spec["params"]).astype(bool)
        fire = [i for i in range(len(df)) if entries.iloc[i] and td[i] >= OPTIONS_START]
        dates = [td[i] for i in _non_overlapping(fire, opt["hold_days"])]
        trades = _run(dates, ctx, opt["type"], opt["moneyness_pct"], opt["min_days_to_expiry"], opt["hold_days"])
        out[p["strategy"]] = {"pattern": p, "trades": trades, "hold": opt["hold_days"], "signals": len(dates)}
    return out


# --- Phase 6: the engine -----------------------------------------------------

@check("6", "6.1", "Index engine: every entry is the open after the signal, every exit a real close")
def engine_timing():
    df, regime, _ = _data()
    opens, closes = df["open"], df["close"]
    by_date = {str(d.date()): i for i, d in enumerate(df.index)}
    bad, total = [], 0
    for name in list(STRATEGY_REGISTRY)[:8]:
        spec = STRATEGY_REGISTRY[name]
        sig = spec["fn"](df, regime, **spec["params"]).astype(bool)
        for t in run_backtest(df, sig, regime, direction=spec["direction"], hold_days=10):
            total += 1
            i = by_date[t.entry_date]
            if not sig.iloc[i - 1]:
                bad.append((name, t.entry_date, "no signal on the bar before entry"))
            if abs(t.entry_price - round(float(opens.iloc[i]), 2)) > 0.01:
                bad.append((name, t.entry_date, "entry is not that day's open"))
            if abs(t.exit_price - round(float(closes.iloc[by_date[t.exit_date]]), 2)) > 0.01:
                bad.append((name, t.exit_date, "exit is not that day's close"))
    return Result(FAIL if bad else PASS, f"{total} trades across 8 strategies; {len(bad)} timing violations",
                  {"violations": bad[:10]})


@check("6", "6.2", "No incomplete trade is counted as a completed one")
def truncated_trades():
    """A trade entered a few days before the data ends cannot have run its
    full hold. Counting it as completed puts a 2-day result into a 10-day
    statistic — and the holdout runs to today, so the newest trades are
    exactly the ones at risk."""
    short = {}
    for name, d in _chosen_trades().items():
        cut = [t for t in d["trades"] if t.holding_days < d["hold"]]
        if cut:
            short[name] = {"hold": d["hold"], "truncated": [(t.entry_date, t.holding_days) for t in cut],
                           "in_holdout": sum(1 for t in cut if t.entry_date >= SPLIT_DATE)}
    df, regime, _ = _data()
    idx_short = 0
    for name in list(STRATEGY_REGISTRY)[:8]:
        spec = STRATEGY_REGISTRY[name]
        sig = spec["fn"](df, regime, **spec["params"]).astype(bool)
        idx_short += sum(1 for t in run_backtest(df, sig, regime, spec["direction"], 10) if t.holding_days < 10)
    n = sum(v["in_holdout"] for v in short.values())
    return Result(FAIL if n else (WARN if idx_short else PASS),
                  f"{n} truncated option trade(s) counted in holdout statistics across {len(short)} pattern(s); "
                  f"{idx_short} in the index engine",
                  {"option_patterns": short})


@check("6", "6.3", "Costs: every trade is charged, and the rate matches an independent calculation")
def costs_applied():
    fut, opt = CostModel(), OptionsCostModel()
    # Recomputed from the rate-card fields, by hand, in basis points.
    fut_ref = (2 * fut.brokerage_pct + 2 * fut.exchange_txn_pct + fut.stamp_duty_pct + fut.stt_pct
               + 2 * fut.slippage_pct + fut.gst_pct * 2 * (fut.brokerage_pct + fut.exchange_txn_pct)) * 100
    opt_ref = (2 * opt.brokerage_pct + 2 * opt.exchange_txn_pct + opt.stamp_duty_pct + opt.stt_pct_sell
               + 2 * opt.premium_slippage_pct + opt.gst_pct * 2 * (opt.brokerage_pct + opt.exchange_txn_pct))
    uncharged = []
    for name, d in _chosen_trades().items():
        for t in d["trades"]:
            if abs((t.gross_return_pct - t.cost_pct) - t.net_return_pct) > 0.02 or t.cost_pct <= 0:
                uncharged.append((name, t.entry_date))
    ok = abs(fut.round_trip_cost_pct() - fut_ref) < 1e-9 and abs(opt.round_trip_cost_fraction() - opt_ref) < 1e-12
    return Result(FAIL if uncharged or not ok else PASS,
                  f"futures round trip {fut.round_trip_cost_pct():.4f}% of notional, options "
                  f"{opt.round_trip_cost_fraction() * 100:.3f}% of premium; {len(uncharged)} trade(s) not charged",
                  {"independent_futures_pct": round(fut_ref, 4), "independent_options_pct": round(opt_ref * 100, 3),
                   "uncharged": uncharged[:10]})


@check("6", "6.4", "One definition of an N-day hold across every engine")
def hold_definitions():
    """The same words have to mean the same trade, or a forward-log outcome
    cannot be compared with the backtest that justified it. The entry point
    legitimately differs — option results enter at a close because the
    archive is end-of-day — but the time in the market must not."""
    from backtest.options_engine import run_options_backtest
    df, regime, ctx = _data()
    td = ctx[2]
    i = next(k for k in range(len(td) - 80, 0, -1) if td[k] >= "2026-01-01")
    sig = pd.Series(False, index=df.index)
    sig.iloc[i] = True
    idx = run_backtest(df, sig, regime, "long", hold_days=10)[0]
    opt = run_options_backtest([td[i]], ctx[1], td, "CE", min_days_to_expiry=7, hold_days=10, strike_offset_pct=0.0)
    span = lambda a, b: td.index(b) - td.index(a) + 1  # noqa: E731  sessions from first to last, inclusive
    engines = {
        "index engine": {"entry": f"open {idx.entry_date}", "exit": f"close {idx.exit_date}",
                         "sessions_in_market": span(idx.entry_date, idx.exit_date)},
        "forward log": {"entry": f"open {td[i + 1]}", "exit": f"close {td[i + 10]}",
                        "sessions_in_market": span(td[i + 1], td[i + 10])},
    }
    if opt:
        # Bought at a close, so the first session of exposure is the next one.
        engines["options engine"] = {"entry": f"close {opt[0].entry_date}", "exit": f"close {opt[0].exit_date}",
                                     "sessions_in_market": span(opt[0].entry_date, opt[0].exit_date) - 1}
    distinct = {v["sessions_in_market"] for v in engines.values()}
    return Result(PASS if len(distinct) == 1 else FAIL,
                  f"a '10-day hold' is {sorted(distinct)} session(s) in the market across {len(engines)} engines; "
                  "options enter at a close by necessity (end-of-day archive), which the research states", engines)


@check("6", "6.5", "Reported metrics match an independent recomputation from the trade list")
def metrics_recomputed():
    from backtest.metrics import compute_metrics
    df, regime, _ = _data()
    wrong = {}
    for name in list(STRATEGY_REGISTRY)[:6]:
        spec = STRATEGY_REGISTRY[name]
        trades = run_backtest(df, spec["fn"](df, regime, **spec["params"]).astype(bool), regime, spec["direction"], 10)
        if len(trades) < 3:
            continue
        m = compute_metrics(trades)
        r = [t.net_return_pct for t in trades]
        eq, peak, mdd = 1.0, 1.0, 0.0
        for x in r:
            eq *= 1 + x / 100
            peak = max(peak, eq)
            mdd = min(mdd, (eq - peak) / peak)
        ref = {"win_rate": sum(x > 0 for x in r) / len(r), "expectancy_pct": statistics.mean(r),
               "max_drawdown_pct": mdd * 100}
        for k, v in ref.items():
            got = m.get(k)
            if got is None or abs(got - v) > 0.01 * max(1, abs(v)):
                wrong.setdefault(name, {})[k] = {"reported": got, "independent": round(v, 4)}
    pf_inf = []
    return Result(FAIL if wrong else PASS, f"win rate, expectancy and max drawdown recomputed; "
                                           f"{len(wrong)} strategy(ies) disagree", {"disagree": wrong, "pf_inf": pf_inf})


# --- Phase 7: research -------------------------------------------------------

@check("7", "7.1", "No strategy in the registry changes its past signals when the future is removed")
def all_strategies_no_lookahead():
    df, regime, _ = _data()
    rng = random.Random(11)
    cuts = sorted(rng.sample(range(400, len(df) - 1), 12))
    leaks = {}
    for name, spec in STRATEGY_REGISTRY.items():
        full = spec["fn"](df, regime, **spec["params"]).astype(bool)
        for cut in cuts:
            part = spec["fn"](df.iloc[:cut], regime.iloc[:cut], **spec["params"]).astype(bool)
            diff = (full.iloc[:cut] != part).sum()
            if diff:
                leaks[name] = {"cut": str(df.index[cut - 1].date()), "signals_changed": int(diff)}
                break
    return Result(FAIL if leaks else PASS,
                  f"{len(STRATEGY_REGISTRY)} strategies x {len(cuts)} cut points; {len(leaks)} rewrite their past",
                  {"leaks": leaks})


@check("7", "7.2", "Signals are clean booleans that fire at a plausible rate")
def signal_sanity():
    """The pandas-3 bug made EMA Pullback fire every day of a trend for six
    phases. A pattern that fires constantly, or on runs of consecutive days,
    is the signature of that class of bug."""
    df, regime, _ = _data()
    odd = {}
    # A close beyond yesterday's range recurs in any trend — by definition,
    # not by bug. The engines take them non-overlapping.
    by_design = {"prev_day_breakout", "prev_day_breakdown"}
    for name, spec in STRATEGY_REGISTRY.items():
        if name in by_design:
            continue
        s = spec["fn"](df, regime, **spec["params"])
        rate = float(s.astype(bool).mean())
        runs = s.astype(bool) & s.astype(bool).shift(1, fill_value=False)
        problems = []
        if s.dtype != bool:
            problems.append(f"dtype {s.dtype}")
        if s.isna().any():
            problems.append(f"{int(s.isna().sum())} NaN")
        if rate > 0.25:
            problems.append(f"fires on {rate:.0%} of days")
        if runs.mean() > 0.10:
            problems.append(f"{runs.mean():.0%} of days continue yesterday's signal")
        if problems:
            odd[name] = problems
    return Result(WARN if odd else PASS, f"{len(STRATEGY_REGISTRY)} strategies; {len(odd)} look unusual", odd)


# --- Phase 8: validation -----------------------------------------------------

@check("8", "8.1", "No development statistic includes a trade priced with holdout-period data")
def dev_holdout_purged():
    """Selection is made on development trades. A trade entered before the
    split but exiting after it is scored on prices from the holdout — so the
    holdout would influence the choice it is supposed to judge. Such trades
    still exist in a raw run; what matters is whether the stored development
    figures, the ones the choice was made on, count them."""
    leaky = {}
    for name, d in _chosen_trades().items():
        straddling = [t for t in d["trades"] if t.entry_date < SPLIT_DATE <= t.exit_date]
        if not straddling:
            continue
        stored = (d["pattern"].get("development") or {}).get("num_trades")
        purged = sum(1 for t in d["trades"] if t.exit_date < SPLIT_DATE)
        with_leak = sum(1 for t in d["trades"] if t.entry_date < SPLIT_DATE)
        if stored != purged:
            leaky[name] = {"stored_dev_trades": stored, "purged": purged, "with_straddlers": with_leak,
                           "straddling": [(t.entry_date, t.exit_date) for t in straddling]}
    return Result(FAIL if leaky else PASS,
                  f"{len(leaky)} pattern(s) whose stored development figures include a trade exiting in the holdout",
                  {"leaky": leaky})


def _research_end() -> str:
    """The last session the stored research saw. Recomputing on data that has
    grown since then compares tonight's numbers with last night's and fails
    on every new session — the audit must judge the research as it was run."""
    return ((load_research() or {}).get("options_period") or {}).get("end") or "9999-12-31"


def _baseline_trades(d):
    from backtest.pattern_options import _run
    _, _, ctx = _data()
    opt = d["pattern"]["suggested_option"]
    end = _research_end()
    days = [x for x in ctx[2] if SPLIT_DATE <= x <= end]
    trades = _run(days[:: opt["hold_days"] + 1], ctx, opt["type"], opt["moneyness_pct"],
                  opt["min_days_to_expiry"], opt["hold_days"])
    return [t for t in trades if t.exit_date <= end]


@check("8", "8.2", "The significance test treats the no-signal baseline as the estimate it is")
def welch_vs_one_sample():
    """The baseline's mean is a sample too. Welch's two-sample test includes
    its uncertainty; the one-sample test treats it as exact and overstates t.
    Checks that the stored t is the Welch one."""
    rows, mismatched = {}, {}
    for name, d in _chosen_trades().items():
        end = _research_end()
        hol = [_rupees(t) for t in d["trades"] if t.entry_date >= SPLIT_DATE and t.exit_date <= end]
        base = [_rupees(t) for t in _baseline_trades(d)]
        if len(hol) < 3 or len(base) < 3:
            continue
        m1, m2 = statistics.mean(hol), statistics.mean(base)
        s1, s2 = statistics.variance(hol), statistics.variance(base)
        one = (m1 - m2) / math.sqrt(s1 / len(hol))
        welch = (m1 - m2) / math.sqrt(s1 / len(hol) + s2 / len(base))
        stored = d["pattern"].get("holdout_t_stat")
        rows[name] = {"n": len(hol), "t_one_sample": round(one, 2), "t_welch": round(welch, 2), "stored_t": stored}
        if stored is None or abs(stored - welch) > 0.02:
            mismatched[name] = rows[name]
    return Result(FAIL if mismatched else PASS,
                  f"{len(rows)} patterns; stored t is the Welch t in {len(rows) - len(mismatched)}",
                  {"mismatched": mismatched, "by_pattern": rows})


@check("8", "8.3", "The evidence bar each pattern faces accounts for how few trades it rests on")
def critical_value_small_samples():
    from briefing.recommendation import build_recommendation
    from stats.multiple_comparisons import required_t
    research = load_research() or {}
    judged = [p for p in research.get("patterns", []) if (p.get("holdout") or {}).get("num_trades")]
    n_tests = build_recommendation()["evidence_bar"]["tests_judged"]
    normal = required_t(n_tests)
    rows = {}
    for x in judged:
        n = x["holdout"]["num_trades"]
        rows[x["label"]] = {"holdout_trades": n, "bar": required_t(n_tests, df=n - 1),
                            "normal_bar": normal, "t": x.get("holdout_t_stat")}
    df_aware = all(v["bar"] > normal for v in rows.values() if v["holdout_trades"] >= 2)
    return Result(PASS if df_aware else FAIL,
                  f"large-sample bar {normal}; every pattern is held to Student's t at its own sample size "
                  f"({min((v['bar'] for v in rows.values()), default=0)} to "
                  f"{max((v['bar'] for v in rows.values() if v['bar'] != float('inf')), default=0)})",
                  {"by_pattern": rows})


@check("8", "8.4", "Holdout samples are large enough to mean something")
def holdout_sizes():
    research = load_research() or {}
    sizes = {p["label"]: (p.get("holdout") or {}).get("num_trades", 0) for p in research.get("patterns", [])}
    small = {k: v for k, v in sizes.items() if 0 < v < MIN_HOLDOUT_TRADES}
    return Result(WARN if small else PASS,
                  f"{len(small)} of {len(sizes)} patterns were judged on fewer than {MIN_HOLDOUT_TRADES} holdout "
                  "trades — too few for a verdict other than 'unproven'", {"small": small})
