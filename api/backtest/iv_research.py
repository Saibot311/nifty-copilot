"""Implied volatility: first as a description of every trade, then — once,
by a test fixed in advance — as a candidate filter.

Order matters here. Looking at how trades did in high- and low-IV markets
and *then* choosing a threshold would be fitting the filter to the answer.
So the one filter hypothesis below was written into this file before any
implied-volatility result existed, and it is not to be edited after seeing
one. A different hypothesis is a new test, logged as one.

Three outputs:
  1. A daily 30-day at-the-money IV series from 2018, checked against India
     VIX — an independent calculation by the exchange from the same market.
  2. A description of each pattern's trades: the IV they were bought at,
     how it moved while they were held, and how they fared by IV level.
     Description only — it adds no hypotheses.
  3. The pre-registered test.
"""

import json
import math
import sqlite3
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from options.iv import MIN_OI, MIN_PRICE, atm_iv, constant_maturity, fit_forward, implied_vol
from stats import student_t
from storage.options_db import DB_PATH as OPTIONS_DB

from .hypothesis_log import log_run
from .pattern_options import (OPTIONS_START, SPLIT_DATE, _non_overlapping, _run, _rupees, load_research)
from .strategies import STRATEGY_REGISTRY, load_daily_data

IV_DB = Path(__file__).parent.parent / "data" / "iv.db"
RESEARCH_PATH = Path(__file__).parent.parent / "data" / "iv_research.json"

PCT_WINDOW = 252      # one year of sessions
PCT_MIN_HISTORY = 126  # no percentile until half a year of history exists
MIN_DTE, MAX_DTE = 7, 75

# --- fixed before any result was computed; do not edit after seeing one ------
PREREGISTERED = {
    "registered": "2026-09-21, before any implied-volatility result had been computed",
    "hypothesis": ("Option trades bought when 30-day at-the-money implied volatility is at or below its "
                   "trailing one-year median earn more per lot than trades bought above it."),
    "why_this_one": ("It is the standard reason to care about IV when buying options — a high-IV entry "
                     "pays for volatility that tends to drain away — so it is the hypothesis options theory "
                     "hands us, not one read off this data."),
    "universe": ("Every pattern's chosen option setup from pattern_options.json, pooled. Those setups were "
                 "chosen without any reference to IV."),
    "unit": ("One observation per entry date: the mean rupees per lot of every trade bought that day. "
             "Trades from different patterns on the same day share one market, so counting them "
             "separately would overstate the sample."),
    "split": "IV percentile <= 50 versus > 50, over the trailing 252 sessions, measured at the entry close.",
    "test": ("Welch's t on rupees per lot, low-IV minus high-IV. It must be positive in the development "
             "period and in the holdout, and the holdout t must clear Student's t at 2.5% one-sided with "
             "Welch-Satterthwaite degrees of freedom."),
    "if_passed": ("A candidate filter, not an applied one. Using it means re-judging every pattern on a "
                  "different set of trades, which adds hypotheses and raises the bar for all of them."),
    "if_failed": "Implied volatility stays a description.",
}
IV_THRESHOLD_PCT = 50
SIGNIFICANCE_ALPHA = 0.025
# -----------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS iv_daily (
    trade_date   TEXT PRIMARY KEY,
    iv_30d       REAL,     -- constant-maturity 30-day ATM implied vol, annualised, as a fraction
    iv_near      REAL,     -- ATM vol of the nearest expiry at least a week out
    near_expiry  TEXT,
    near_days    INTEGER,
    forward      REAL,     -- that expiry's forward, from put-call parity
    discount     REAL,
    strikes_used INTEGER,
    method       TEXT      -- 'parity fit' | 'parity forward' | 'fallback'
);
"""


# --- 1. the daily series -----------------------------------------------------

def _options_conn():
    conn = sqlite3.connect(OPTIONS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def chain(conn, trade_date: str, expiry: str) -> tuple[dict, dict]:
    rows = conn.execute(
        "SELECT strike, option_type, close FROM option_bars WHERE trade_date=? AND expiry_date=? "
        "AND close >= ? AND open_interest >= ?", (trade_date, expiry, MIN_PRICE, MIN_OI)).fetchall()
    calls = {r["strike"]: r["close"] for r in rows if r["option_type"] == "CE"}
    puts = {r["strike"]: r["close"] for r in rows if r["option_type"] == "PE"}
    return calls, puts


def _years(trade_date: str, expiry: str) -> float:
    return (date.fromisoformat(expiry) - date.fromisoformat(trade_date)).days / 365


def day_iv(conn, trade_date: str, spot: float) -> dict | None:
    expiries = [r[0] for r in conn.execute(
        "SELECT DISTINCT expiry_date FROM option_bars WHERE trade_date=? "
        "AND expiry_date BETWEEN date(?, ?) AND date(?, ?) ORDER BY expiry_date",
        (trade_date, trade_date, f"+{MIN_DTE} day", trade_date, f"+{MAX_DTE} day"))]
    points, near = [], None
    for e in expiries:
        calls, puts = chain(conn, trade_date, e)
        if not calls or not puts:
            continue
        T = _years(trade_date, e)
        fit = fit_forward(calls, puts, spot, T)
        v = atm_iv(calls, puts, fit, T)
        if v is None:
            continue
        points.append((T, v))
        if near is None:
            near = {"iv_near": v, "near_expiry": e, "near_days": round(T * 365), "forward": fit.forward,
                    "discount": fit.discount, "strikes_used": fit.strikes_used, "method": fit.method}
    if not near:
        return None
    return {"trade_date": trade_date, "iv_30d": constant_maturity(points), **near}


def compute_series(spot: dict[str, float]) -> int:
    """Fills iv_daily for every archived day not yet in it. Returns rows added."""
    out = sqlite3.connect(IV_DB)
    out.executescript(SCHEMA)
    have = {r[0] for r in out.execute("SELECT trade_date FROM iv_daily")}
    conn = _options_conn()
    added = 0
    try:
        for d in [r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM option_bars ORDER BY trade_date")]:
            if d in have or d not in spot:
                continue
            row = day_iv(conn, d, spot[d])
            if row:
                out.execute("INSERT OR REPLACE INTO iv_daily VALUES (:trade_date, :iv_30d, :iv_near, :near_expiry, "
                            ":near_days, :forward, :discount, :strikes_used, :method)", row)
                added += 1
        out.commit()
    finally:
        conn.close()
        out.close()
    return added


def load_series() -> pd.DataFrame:
    """The daily series with a trailing percentile — each day ranked only
    against itself and the days before it, never the days after."""
    if not IV_DB.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(IV_DB)
    try:
        df = pd.read_sql("SELECT * FROM iv_daily ORDER BY trade_date", conn, index_col="trade_date")
    finally:
        conn.close()
    iv = df["iv_30d"]
    df["iv_pct"] = iv.rolling(PCT_WINDOW, min_periods=PCT_MIN_HISTORY).apply(
        lambda w: (w <= w[-1]).mean() * 100, raw=True)
    return df


def vix_check(series: pd.DataFrame) -> dict:
    """India VIX is the exchange's own 30-day volatility, computed from the
    whole strike range rather than at the money. It usually sits a little
    above ATM vol (it prices the skew), but the two must move together — if
    they do not, the calculation here is wrong."""
    from market_data import YFinanceProvider
    vix = YFinanceProvider().get_ohlc("^INDIAVIX", "1d", date(2018, 1, 1), date.today())
    v = pd.Series({c.timestamp[:10]: c.close for c in vix})
    both = pd.DataFrame({"ours": series["iv_30d"] * 100, "vix": v}).dropna()
    if len(both) < 30:
        return {"compared_days": len(both), "verdict": "too few overlapping days"}
    corr = float(both["ours"].corr(both["vix"]))
    chg = both.diff().dropna()
    return {
        "compared_days": len(both),
        "level_correlation": round(corr, 3),
        "daily_change_correlation": round(float(chg["ours"].corr(chg["vix"])), 3),
        "median_ours": round(float(both["ours"].median()), 2),
        "median_vix": round(float(both["vix"].median()), 2),
        "median_gap_points": round(float((both["vix"] - both["ours"]).median()), 2),
        "verdict": ("Tracks India VIX closely — the calculation is sound." if corr >= 0.9 else
                    "Does NOT track India VIX closely — do not trust these numbers until this is explained."),
    }


# --- 2. describing trades ----------------------------------------------------

def _chosen_trades() -> dict:
    df, regime = load_daily_data("^NSEI", 7000)
    td = [str(d.date()) for d in df.index]
    ctx = (df, pd.Series(df["close"].values, index=td), td)
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
        out[p["strategy"]] = {"label": p["label"], "status": p["status"], "trades": trades}
    return out


def contract_iv(conn, cache: dict, trade_date: str, expiry: str, strike: float, kind: str,
                price: float, spot: float) -> float | None:
    key = (trade_date, expiry)
    if key not in cache:
        calls, puts = chain(conn, trade_date, expiry)
        cache[key] = fit_forward(calls, puts, spot, _years(trade_date, expiry)) if calls and puts else None
    fit = cache[key]
    if fit is None:
        return None
    return implied_vol(price, fit.forward, strike, _years(trade_date, expiry), fit.discount, kind)


def annotate(trades_by_pattern: dict, series: pd.DataFrame, spot: dict[str, float]) -> list[dict]:
    """Every trade with the IV it was bought and sold at, and where that
    stood against the previous year."""
    conn = _options_conn()
    cache: dict = {}
    rows = []
    try:
        for name, d in trades_by_pattern.items():
            for t in d["trades"]:
                entry_iv = contract_iv(conn, cache, t.entry_date, t.expiry_date, t.strike, t.option_type,
                                       t.entry_premium, spot.get(t.entry_date, t.spot_at_entry))
                exit_spot = spot.get(t.exit_date)
                exit_iv = (contract_iv(conn, cache, t.exit_date, t.expiry_date, t.strike, t.option_type,
                                       t.exit_premium, exit_spot) if exit_spot else None)
                s = series.loc[t.entry_date] if t.entry_date in series.index else None
                e = series.loc[t.exit_date] if t.exit_date in series.index else None
                rows.append({
                    "pattern": name, "entry_date": t.entry_date, "exit_date": t.exit_date,
                    "rupees": _rupees(t), "entry_iv": entry_iv, "exit_iv": exit_iv,
                    "iv_30d": None if s is None else s["iv_30d"],
                    "iv_30d_exit": None if e is None else e["iv_30d"],
                    "iv_pct": None if s is None or pd.isna(s["iv_pct"]) else float(s["iv_pct"]),
                })
    finally:
        conn.close()
    return rows


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs)) if xs else None


def describe(rows: list[dict], labels: dict) -> dict:
    """Per pattern: what IV its trades were bought at, how that IV moved
    while held, and profit per lot on each side of the median. The last is a
    description, and is labelled as one — reading it as a rule would be
    choosing a filter after seeing the answer."""
    out = {}
    for name in labels:
        rs = [r for r in rows if r["pattern"] == name]
        if not rs:
            continue
        pct = [r["iv_pct"] for r in rs if r["iv_pct"] is not None]
        moves = [(r["exit_iv"] - r["entry_iv"]) * 100 for r in rs if r["entry_iv"] and r["exit_iv"]]
        # The market's 30-day vol over the same days. Cleaner than the
        # contract's own vol, which also shifts as the contract drifts in or
        # out of the money along the skew.
        market = [(r["iv_30d_exit"] - r["iv_30d"]) * 100 for r in rs
                  if r["iv_30d"] is not None and r["iv_30d_exit"] is not None]
        low = [r["rupees"] for r in rs if r["iv_pct"] is not None and r["iv_pct"] <= IV_THRESHOLD_PCT]
        high = [r["rupees"] for r in rs if r["iv_pct"] is not None and r["iv_pct"] > IV_THRESHOLD_PCT]
        out[name] = {
            "label": labels[name], "trades": len(rs),
            "median_entry_iv_pct": round(statistics.median(pct)) if pct else None,
            "bought_in_top_half_of_iv": round(sum(p > 50 for p in pct) / len(pct), 2) if pct else None,
            "median_contract_iv_at_entry": round(statistics.median(
                [r["entry_iv"] for r in rs if r["entry_iv"]]) * 100, 1) if any(r["entry_iv"] for r in rs) else None,
            "median_contract_iv_change_pts": round(statistics.median(moves), 1) if moves else None,
            "median_market_iv_change_pts": round(statistics.median(market), 1) if market else None,
            "rupees_per_lot_when_iv_low": _mean(low), "trades_when_iv_low": len(low),
            "rupees_per_lot_when_iv_high": _mean(high), "trades_when_iv_high": len(high),
        }
    return out


# --- 3. the pre-registered test ------------------------------------------------

def _by_entry_date(rows: list[dict]) -> dict[str, dict]:
    days: dict[str, dict] = {}
    for r in rows:
        if r["iv_pct"] is None:
            continue
        d = days.setdefault(r["entry_date"], {"rupees": [], "iv_pct": r["iv_pct"], "exit": r["exit_date"]})
        d["rupees"].append(r["rupees"])
        d["exit"] = max(d["exit"], r["exit_date"])
    return {k: {"rupees": statistics.mean(v["rupees"]), "iv_pct": v["iv_pct"], "exit": v["exit"]}
            for k, v in days.items()}


def _welch(a: list[float], b: list[float]) -> dict:
    if len(a) < 3 or len(b) < 3:
        return {"n_low": len(a), "n_high": len(b), "t": None, "df": None, "bar": None}
    va, vb = statistics.variance(a), statistics.variance(b)
    se2 = va / len(a) + vb / len(b)
    t = (statistics.mean(a) - statistics.mean(b)) / math.sqrt(se2)
    df = se2 ** 2 / ((va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1))
    return {"n_low": len(a), "n_high": len(b), "mean_low": round(statistics.mean(a)),
            "mean_high": round(statistics.mean(b)), "difference": round(statistics.mean(a) - statistics.mean(b)),
            "t": round(t, 2), "df": round(df, 1), "bar": round(student_t.ppf(1 - SIGNIFICANCE_ALPHA, df), 2)}


def preregistered_test(rows: list[dict]) -> dict:
    days = _by_entry_date(rows)
    # Development observations must finish before the split, as in the
    # option research: a trade priced with holdout data cannot inform it.
    dev = {k: v for k, v in days.items() if v["exit"] < SPLIT_DATE}
    hol = {k: v for k, v in days.items() if k >= SPLIT_DATE}

    def split(obs):
        return ([v["rupees"] for v in obs.values() if v["iv_pct"] <= IV_THRESHOLD_PCT],
                [v["rupees"] for v in obs.values() if v["iv_pct"] > IV_THRESHOLD_PCT])

    d, h = _welch(*split(dev)), _welch(*split(hol))
    log_run("iv_filter_preregistered", {"iv_pct_max": IV_THRESHOLD_PCT, "window": PCT_WINDOW},
            "^NSEI", 0, {"num_trades": h["n_low"] + h["n_high"], "holdout_t": h["t"]})

    if d["t"] is None or h["t"] is None:
        verdict, detail = "NOT ENOUGH DATA", "Too few entry dates on one side of the median."
    elif d["difference"] <= 0 or h["difference"] <= 0:
        verdict = "NOT ADOPTED"
        detail = (f"Low-IV entries did not beat high-IV entries in both periods: development "
                  f"₹{d['difference']:+,} per lot (t = {d['t']}), holdout ₹{h['difference']:+,} (t = {h['t']}). "
                  "Implied volatility stays a description.")
    elif h["t"] < h["bar"]:
        verdict = "NOT ADOPTED"
        detail = (f"Low-IV entries did better in both periods — development ₹{d['difference']:+,} per lot, "
                  f"holdout ₹{h['difference']:+,} — but the holdout t of {h['t']} is below the {h['bar']} "
                  "needed to tell it from luck. Implied volatility stays a description.")
    else:
        verdict = "CANDIDATE FILTER"
        detail = (f"Low-IV entries beat high-IV entries in both periods, and clearly on the holdout: "
                  f"₹{h['difference']:+,} per lot, t = {h['t']} against a bar of {h['bar']}. "
                  + PREREGISTERED["if_passed"])
    return {**PREREGISTERED, "threshold_pct": IV_THRESHOLD_PCT, "development": d, "holdout": h,
            "verdict": verdict, "detail": detail}


# --- all of it ---------------------------------------------------------------

def run_iv_research(symbol: str = "^NSEI") -> dict:
    df, _ = load_daily_data(symbol, 7000)
    spot = {str(ix.date()): float(c) for ix, c in df["close"].items()}
    added = compute_series(spot)
    series = load_series()
    trades = _chosen_trades()
    rows = annotate(trades, series, spot)
    today = series.dropna(subset=["iv_30d"]).iloc[-1]
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "series": {
            "first": series.index[0], "last": series.index[-1], "days": len(series), "added_this_run": added,
            "parity_fit_share": round(float((series["method"] == "parity fit").mean()), 3),
            "latest": {"date": series.dropna(subset=["iv_30d"]).index[-1],
                       "iv_30d_pct": round(float(today["iv_30d"]) * 100, 2),
                       "percentile_1y": None if pd.isna(today["iv_pct"]) else round(float(today["iv_pct"]))},
        },
        "vix_check": vix_check(series),
        "by_pattern": describe(rows, {k: v["label"] for k, v in trades.items()}),
        "by_pattern_note": (
            "A description, not a finding. Which patterns did better at low or high IV flips from one "
            "pattern to the next, and picking the favourable cells out of a table this size would be "
            "choosing a filter after seeing the answer. The one filter that was tested is below."
        ),
        "preregistered_test": preregistered_test(rows),
        "method_note": (
            "Implied volatility is backed out of NSE closing prices with Black-76 on each expiry's forward, "
            "which is read off put-call parity rather than assumed. The 30-day figure interpolates total "
            "variance between the expiries either side of 30 days. Percentiles rank each day against the "
            "252 sessions before it and never after."
        ),
    }


def load_iv_research() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None
