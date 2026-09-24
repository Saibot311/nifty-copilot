"""Phase 11 — historical similarity: past days whose market state looked
like today's, and what happened next.

Deliberately small (the plan's biggest scope-creep risk): five features,
Euclidean nearest neighbours on z-scores, nothing learned.

  ret20      20-day return
  vs_ema50   close vs its 50-day EMA
  rsi14      RSI(14)
  vol20      20-day realised volatility, annualised
  off_high   distance below the 252-day high

Honesty rules, same as everything else here:
  * An analog only counts once its outcome was known: at least HORIZON
    trading days before the query date.
  * Analogs are spread out (one per SPACING days) so a single episode can't
    masquerade as twenty independent "similar days".
  * Outcomes are always shown next to the base rate of all eligible days —
    NIFTY drifts up, so "60% were higher" alone means nothing.
  * Whether analogs predict anything is itself tested walk-forward, and the
    result is reported with the analogs.
"""

import math
import statistics

import numpy as np
import pandas as pd

from quant.indicators import ema, rsi

from .options_engine import run_options_backtest

FEATURES = ["ret20", "vs_ema50", "rsi14", "vol20", "off_high"]
FEATURE_LABELS = {
    "ret20": "20-day return %",
    "vs_ema50": "vs 50-day EMA %",
    "rsi14": "RSI(14)",
    "vol20": "20-day volatility %",
    "off_high": "below 52-week high %",
}
K = 20
SPACING = 5
HORIZON = 10
HORIZONS = (1, 5, 10)
EVAL_START = "2010-01-01"
LOT_SIZE = 65
OPTIONS_START = "2018-01-01"


def features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    logret = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    f["ret20"] = (c / c.shift(20) - 1) * 100
    f["vs_ema50"] = (c / ema(c, 50) - 1) * 100
    f["rsi14"] = rsi(c, 14)
    f["vol20"] = logret.rolling(20).std() * math.sqrt(252) * 100
    f["off_high"] = (c / c.rolling(252).max() - 1) * 100
    return f


def forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    return pd.DataFrame({f"{h}d": (c.shift(-h) / c - 1) * 100 for h in HORIZONS}, index=df.index)


def _neighbours(f: np.ndarray, query: int, pool_end: int) -> list[tuple[int, float]]:
    """Nearest pool rows (indices < pool_end) to row `query`, z-scored on the
    pool's own mean/std, spread at least SPACING apart."""
    pool = f[:pool_end]
    ok = ~np.isnan(pool).any(axis=1)
    idx = np.flatnonzero(ok)
    if len(idx) < K * SPACING:
        return []
    mu, sd = pool[idx].mean(axis=0), pool[idx].std(axis=0)
    sd[sd == 0] = 1
    z = (pool[idx] - mu) / sd
    q = (f[query] - mu) / sd
    dist = np.sqrt(((z - q) ** 2).sum(axis=1))
    chosen: list[tuple[int, float]] = []
    for j in np.argsort(dist):
        i = int(idx[j])
        if all(abs(i - c) >= SPACING for c, _ in chosen):
            chosen.append((i, float(dist[j])))
            if len(chosen) == K:
                break
    return chosen


def walk_forward_test(df: pd.DataFrame, f: pd.DataFrame, fwd: pd.DataFrame) -> dict:
    """Every HORIZON days from EVAL_START: predict the next-10-day return as
    the analogs' mean minus the base rate, using only analogs whose outcome
    was known. Non-overlapping test points, so they're independent samples."""
    fa, target = f[FEATURES].to_numpy(), fwd[f"{HORIZON}d"].to_numpy()
    start = int(np.searchsorted(df.index, pd.Timestamp(EVAL_START)))
    preds, actuals = [], []
    for t in range(start, len(df) - HORIZON, HORIZON):
        if np.isnan(fa[t]).any():
            continue
        pool_end = t - HORIZON + 1  # outcomes of rows < pool_end are known at t
        nb = _neighbours(fa, t, pool_end)
        if not nb:
            continue
        known = target[:pool_end]
        base = np.nanmean(known)
        preds.append(np.mean([target[i] for i, _ in nb]) - base)
        actuals.append(target[t] - base)
    n = len(preds)
    if n < 30:
        return {"test_points": n, "verdict": "too few test points"}
    ic = float(pd.Series(preds).rank().corr(pd.Series(actuals).rank()))  # Spearman, without scipy
    t_stat = ic * math.sqrt((n - 2) / max(1e-9, 1 - ic**2))
    hit = sum((p > 0) == (a > 0) for p, a in zip(preds, actuals)) / n
    return {
        "test_points": n,
        "period_start": EVAL_START,
        "rank_correlation": round(ic, 3),
        "t_stat": round(t_stat, 2),
        # The same rule as the verdict below, so the card never re-judges it.
        "predictive": t_stat >= 2,
        "direction_hit_rate": round(hit, 3),
        "verdict": (
            "Analogs have predicted the next 10 days better than chance (t >= 2)."
            if t_stat >= 2 else
            "No demonstrated predictive value: treat the analogs as context about similar past "
            "markets, not as a forecast."
        ),
    }


def _option_outcomes(dates: list[str], df: pd.DataFrame, hold: int = 5) -> dict:
    td = [str(d.date()) for d in df.index]
    spot = pd.Series(df["close"].values, index=td)
    out = {}
    for ot in ("CE", "PE"):
        trades = run_options_backtest(dates, spot, td, option_type=ot, min_days_to_expiry=7, hold_days=hold,
                                      strike_offset_pct=0.0)
        rs = [t.entry_premium * t.net_return_pct / 100 * LOT_SIZE for t in trades]
        out[ot] = {
            "trades": len(trades),
            "win_rate": round(sum(r > 0 for r in rs) / len(rs), 3) if rs else None,
            "avg_profit_per_lot_rs": round(statistics.mean(rs)) if rs else None,
        }
    return {"hold_days": hold, "option": "ATM, expiry at least 7 days out", **out}


def similar_days(df: pd.DataFrame) -> dict:
    f = features(df)
    fwd = forward_returns(df)
    fa = f[FEATURES].to_numpy()
    q = len(df) - 1
    if np.isnan(fa[q]).any():
        return {"unavailable": "not enough history for today's features"}
    pool_end = q - HORIZON + 1
    nb = _neighbours(fa, q, pool_end)

    pool = fwd.iloc[:pool_end]
    base = {h: {"pct_higher": round(float((pool[h] > 0).mean()), 3), "median_pct": round(float(pool[h].median()), 2)}
            for h in fwd.columns}
    analog_fwd = fwd.iloc[[i for i, _ in nb]]
    analogs = {h: {"pct_higher": round(float((analog_fwd[h] > 0).mean()), 3),
                   "median_pct": round(float(analog_fwd[h].median()), 2)} for h in fwd.columns}

    rows = []
    for i, d in nb:
        rows.append({
            "date": str(df.index[i].date()),
            "distance": round(d, 2),
            "close": round(float(df["close"].iloc[i]), 2),
            **{k: round(float(f[k].iloc[i]), 2) for k in FEATURES},
            **{f"fwd_{h}": round(float(fwd[h].iloc[i]), 2) for h in fwd.columns},
        })

    option_dates = [r["date"] for r in rows if r["date"] >= OPTIONS_START]
    return {
        "as_of": str(df.index[q].date()),
        "today": {k: round(float(f[k].iloc[q]), 2) for k in FEATURES},
        "feature_labels": FEATURE_LABELS,
        "analogs": rows,
        "outcomes": {"analogs": analogs, "all_days": base},
        "options_on_analog_days": _option_outcomes(option_dates, df) if option_dates else None,
        "walk_forward": walk_forward_test(df, f, fwd),
        "method_note": (
            f"{K} past days nearest to today on {len(FEATURES)} features (z-scored), no two within {SPACING} "
            f"trading days, each at least {HORIZON} days old so its outcome is known. Outcomes are close to "
            "close, shown next to the same figures for all past days."
        ),
    }


def run_similarity(symbol: str = "^NSEI") -> dict:
    from datetime import datetime

    from market_data.kite_session import IST
    from market_data.zerodha_provider import is_provisional

    from .strategies import load_daily_data

    df, _ = load_daily_data(symbol, 7000)
    now = datetime.now(IST)
    if is_provisional(df.index[-1].to_pydatetime().replace(tzinfo=IST), "day", now):
        df = df.iloc[:-1]  # judge from the last final close
    return similar_days(df)
