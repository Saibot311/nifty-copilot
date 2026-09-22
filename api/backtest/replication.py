"""Replication on other indices: BANKNIFTY, SENSEX and NIFTY Midcap Select.

The binding constraint on every verdict so far is sample size — the best
pattern rested on 13 holdout trades. Running the *same* rules on other
indices gives each one more trades without inventing a single new idea.
Nothing is re-chosen per index: a pattern carries the option setup NIFTY's
research picked on 2018-23, and a structural test its fixed setup.

The indices move together, so trades on the same date are not independent
evidence. The unit of observation is the entry date, not the trade.

Everything below was written before any result on another index existed.
"""

# --- fixed before any result was computed; do not edit after seeing one ------
PREREGISTERED = {
    "registered": "2026-09-22, before any option result on BANKNIFTY, SENSEX or Midcap Select had been computed",
    "indices": {
        "NIFTY": "the original data, included so the pooled verdict rests on everything",
        "BANKNIFTY": "NSE options from 2018; index levels from NSE's all-index report",
        "MIDCPNIFTY": ("NSE options from January 2022, when they launched; index levels from NSE's all-index "
                       "report (Yahoo does not carry the index); days NSE reported with a close only are dropped"),
        "SENSEX": "BSE options from January 2024, where BSE's public archive begins; index levels from Yahoo",
    },
    "hypotheses": (
        "Every pattern that NIFTY's research judged on the holdout, with the option setup chosen for it on "
        "NIFTY's 2018-23 data (moneyness as a percentage of spot, minimum days to expiry, holding period); and "
        "the three structural tests that need nothing NIFTY-specific — turn of the month, the day before a "
        "holiday, and the opening gap pushed back — with their pre-registered setups. Patterns NIFTY found too "
        "rare to judge are not replicated: they have no setup, and choosing one here would be a new test. The "
        "volatility and positioning tests are not replicated: they use NIFTY-only inputs."),
    "signals": "Each index's own daily bars, through the same signal functions as NIFTY.",
    "measure": (
        "Net return on premium, per cent, after the options cost model. Rupees per lot cannot be pooled: lot "
        "sizes differ by index and have changed over time. The setup was chosen by rupees on NIFTY, so "
        "nothing here is chosen by percentage."),
    "unit": ("One observation per entry date: the mean return of every trade (any index) entered that day. "
             "The no-signal baseline is built the same way from each index's scheduled no-signal trades."),
    "periods": "As before: development trades exit before 2024-01-01; holdout trades enter on or after it.",
    "verdict": (
        "The project's ladder on the pooled date-level returns: profitable in both periods, better than the "
        "no-signal baseline in both, a holdout Welch t above the bar, and at least 15 holdout dates for "
        "APPROVED. The pooled verdict replaces the NIFTY-only one as the verdict of record."),
    "bar": ("Replication is a second look at the holdout for each hypothesis, so each one counts again: the "
            "Bonferroni bar is for 26 + (number replicated) tests, from Student's t at the holdout dates minus one."),
    "also_reported": ("Each index's own result and whether they agree in sign — description only. A result "
                      "carried by one index and contradicted by the others is not a pattern."),
}
BASE_TESTS = 26
MIN_HOLDOUT_DATES = 15
STRUCTURAL_REPLICATED = ("turn_of_month", "pre_holiday", "absorbed_gap")
# -----------------------------------------------------------------------------

import json
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from market_data import YFinanceProvider
from market_data.bar_archive import index_trading_days
from quant.pipeline import candles_to_df
from quant.regime import classify_regime_series
from stats.multiple_comparisons import required_t
from storage.options_db import db_path_for

from . import structural_research as sr
from .hypothesis_log import log_run
from .options_engine import run_options_backtest
from .pattern_options import OPTIONS_START, SPLIT_DATE, load_research
from .strategies import STRATEGY_REGISTRY, load_daily_data
from .walkforward import holdout_verdict, welch_t_stat

RESEARCH_PATH = Path(__file__).parent.parent / "data" / "replication.json"
PREREG_HASH = "01c923a162284ea7"
INDICES = ("NIFTY", "BANKNIFTY", "MIDCPNIFTY", "SENSEX")
PCR_PATTERNS = ("pcr_capitulation_call", "pcr_exhaustion_put")


# --- data per index -----------------------------------------------------------

def load_index(underlying: str) -> tuple[pd.DataFrame, pd.Series] | None:
    """Daily bars and regime for an index, from the sources the plan names."""
    if underlying == "NIFTY":
        return load_daily_data("^NSEI", 7000)
    if underlying == "SENSEX":
        candles = YFinanceProvider().get_ohlc("^BSESN", "1d", date(2017, 6, 1), date.today())
        df = candles_to_df(candles)
    else:
        from storage.nse_index_db import load as load_nse
        df = load_nse(underlying)
        df = df.dropna(subset=["open", "high", "low", "close"])  # close-only days are dropped, as registered
        df = df.assign(volume=0.0, provisional=False)
    if len(df) < 100:
        return None
    return df, classify_regime_series(df)


def _ctx(df: pd.DataFrame):
    td = [str(d.date()) for d in df.index]
    return df, pd.Series(df["close"].values, index=td), td


def _non_overlapping(sigs: list[tuple[str, str]], td: list[str], hold: int) -> list[tuple[str, str]]:
    return sr.non_overlapping(sigs, td, hold)


def _trades(sigs, ctx, underlying, m_pct, dte, hold) -> list:
    df, spot, td = ctx
    out = []
    for kind in ("CE", "PE"):
        dates = [d for d, k in sigs if k == kind]
        if not dates:
            continue
        off = m_pct if kind == "CE" else -m_pct  # positive = OTM, direction-aware, as in pattern_options
        out += run_options_backtest(dates, spot, td, option_type=kind, min_days_to_expiry=dte, hold_days=hold,
                                    strike_offset_pct=off, db_path=db_path_for(underlying))
    return out


def _baseline(ctx, underlying, kinds, m_pct, dte, hold) -> list:
    """Scheduled no-signal trades, every hold+1 sessions, for each leg the
    hypothesis uses."""
    _, _, td = ctx
    days = [d for d in td if d >= OPTIONS_START][:: hold + 1]
    return _trades([(d, k) for d in days for k in kinds], ctx, underlying, m_pct, dte, hold)


# --- pooling ---------------------------------------------------------------------

def _by_date(trades_by_index: dict[str, list], pick) -> dict[str, float]:
    """Mean net return of every trade entered on each date, across indices —
    one observation per date, because the indices move together."""
    per: dict[str, list[float]] = {}
    for trades in trades_by_index.values():
        for t in pick(trades):
            per.setdefault(t.entry_date, []).append(t.net_return_pct)
    return {d: statistics.mean(v) for d, v in per.items()}


def _dev(trades):
    return [t for t in trades if t.exit_date < SPLIT_DATE]


def _hol(trades):
    return [t for t in trades if t.entry_date >= SPLIT_DATE]


def _summ(trades) -> dict:
    r = [t.net_return_pct for t in trades]
    return {"trades": len(r), "avg_return_pct": round(statistics.mean(r), 2) if r else None,
            "win_rate": round(sum(x > 0 for x in r) / len(r), 3) if r else None}


def judge(name: str, label: str, sig_by_index: dict, base_by_index: dict, tests: int) -> dict:
    dev_s, hol_s = _by_date(sig_by_index, _dev), _by_date(sig_by_index, _hol)
    dev_b, hol_b = _by_date(base_by_index, _dev), _by_date(base_by_index, _hol)
    mean = lambda d: round(statistics.mean(d.values()), 2) if d else 0.0  # noqa: E731
    n = len(hol_s)
    t = welch_t_stat(list(hol_s.values()), list(hol_b.values()))
    bar = required_t(tests, df=n - 1) if n >= 2 else None
    status, reason = holdout_verdict(mean(dev_s), mean(hol_s), mean(dev_b), mean(hol_b), n, MIN_HOLDOUT_DATES,
                                     "long", t, min_t=bar, baseline_label="the same option bought with no signal",
                                     unit="%")
    per_index = {}
    for u in sig_by_index:
        s, b = sig_by_index[u], base_by_index.get(u, [])
        per_index[u] = {"development": _summ(_dev(s)), "holdout": _summ(_hol(s)),
                        "baseline_holdout_avg_pct": _summ(_hol(b))["avg_return_pct"],
                        "baseline_development_avg_pct": _summ(_dev(b))["avg_return_pct"]}
    signs = [v["holdout"]["avg_return_pct"] - (v["baseline_holdout_avg_pct"] or 0)
             for v in per_index.values() if v["holdout"]["trades"]]
    log_run(f"replication_{name}", {"prereg": PREREG_HASH}, "MULTI", 0,
            {"num_trades": n, "expectancy_pct": mean(hol_s)})
    return {
        "name": name, "label": label,
        "pooled": {"development_dates": len(dev_s), "holdout_dates": n,
                   "development_avg_pct": mean(dev_s), "holdout_avg_pct": mean(hol_s),
                   "baseline_development_avg_pct": mean(dev_b), "baseline_holdout_avg_pct": mean(hol_b),
                   "holdout_t": t, "required_t": bar},
        "status": status, "reason": reason, "per_index": per_index,
        "indices_beating_baseline_in_holdout": sum(x > 0 for x in signs), "indices_with_holdout_trades": len(signs),
    }


def run_replication() -> dict:
    research = load_research() or {}
    patterns = [p for p in research.get("patterns", []) if (p.get("holdout") or {}).get("num_trades")
                and p.get("suggested_option")]
    tests = BASE_TESTS + len(patterns) + len(STRUCTURAL_REPLICATED)

    data = {u: load_index(u) for u in INDICES}
    data = {u: v for u, v in data.items() if v is not None}
    ctxs = {u: _ctx(v[0]) for u, v in data.items()}
    sessions, archive_last = index_trading_days()
    holidays = sr.weekday_holidays(sessions, OPTIONS_START, archive_last) if archive_last else []

    results = []
    for p in patterns:
        spec = STRATEGY_REGISTRY[p["strategy"]]
        opt = p["suggested_option"]
        kind, m, dte, hold = opt["type"], opt["moneyness_pct"], opt["min_days_to_expiry"], opt["hold_days"]
        sig_by, base_by = {}, {}
        for u, (df, regime) in data.items():
            extra = {"pcr_db": db_path_for(u)} if p["strategy"] in PCR_PATTERNS else {}
            entries = spec["fn"](df, regime, **spec["params"], **extra).astype(bool)
            td = ctxs[u][2]
            sigs = [(td[i], kind) for i in range(len(td)) if entries.iloc[i] and td[i] >= OPTIONS_START]
            sig_by[u] = _trades(_non_overlapping(sigs, td, hold), ctxs[u], u, m, dte, hold)
            base_by[u] = _baseline(ctxs[u], u, (kind,), m, dte, hold)
        results.append({"kind": "pattern", "setup": opt["description"],
                        **judge(p["strategy"], p["label"], sig_by, base_by, tests)})

    for name in STRUCTURAL_REPLICATED:
        hold = sr.PREREGISTERED["hypotheses"][name]["hold_sessions"]
        sig_by, base_by = {}, {}
        for u, (df, _) in data.items():
            td = ctxs[u][2]
            sigs = {"turn_of_month": lambda: sr.turn_of_month(td),
                    "pre_holiday": lambda: sr.pre_holiday(td, holidays),
                    "absorbed_gap": lambda: sr.absorbed_gap(df)}[name]()
            sigs = [s for s in sigs if s[0] >= OPTIONS_START]
            kinds = tuple(sorted({k for _, k in sigs})) or ("CE",)
            sig_by[u] = _trades(_non_overlapping(sigs, td, hold), ctxs[u], u, 0.0, sr.MIN_DTE, hold)
            base_by[u] = _baseline(ctxs[u], u, kinds, 0.0, sr.MIN_DTE, hold)
        results.append({"kind": "structural", "setup": f"ATM, expiry at least {sr.MIN_DTE} days out, hold {hold}",
                        **judge(name, sr.LABELS[name], sig_by, base_by, tests)})

    coverage = {}
    for u, (df, _) in data.items():
        coverage[u] = {"index_days": len(df), "first": str(df.index[0].date()), "last": str(df.index[-1].date())}
    return {"computed_at": datetime.now(timezone.utc).isoformat(), "prereg_hash": PREREG_HASH,
            "preregistered": PREREGISTERED, "tests_counted": tests, "coverage": coverage,
            "hypotheses": results}


def load_replication() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None
