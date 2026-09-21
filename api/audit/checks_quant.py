"""Phase 5: the quant engine, checked against independent implementations.

quant/indicators.py is hand-written and, until this audit, had no tests at
all — yet every signal in the system is built on it. The references below
are plain loops written from the published definitions (Wilder 1978 for
RSI/ATR/ADX, Bollinger 2001, Lane for stochastics), deliberately not calling
pandas' ewm, so agreement means two different routes reach the same number.

Recursive indicators depend on how they are seeded. Two correct
implementations can differ for the first few dozen bars and then converge,
so values are compared only after a warm-up.
"""

import math
import random
import statistics

import numpy as np
import pandas as pd

from quant import indicators as ind
from quant.regime import classify_regime, classify_regime_series

from . import FAIL, PASS, WARN, Result, check

WARMUP = 250


def _df() -> pd.DataFrame:
    from backtest.strategies import load_daily_data
    df, _ = load_daily_data("^NSEI", 7000)
    return df


# --- independent references --------------------------------------------------

def ref_ema(x: list[float], n: int) -> list[float]:
    a, out = 2 / (n + 1), [x[0]]
    for v in x[1:]:
        out.append(a * v + (1 - a) * out[-1])
    return out


def ref_wilder(x: list[float], n: int) -> list[float]:
    """Wilder's smoothing, seeded with the simple mean of the first n values."""
    out = [math.nan] * len(x)
    out[n - 1] = sum(x[:n]) / n
    for i in range(n, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def ref_rsi(close: list[float], n: int = 14) -> list[float]:
    gains = [0.0] + [max(close[i] - close[i - 1], 0) for i in range(1, len(close))]
    losses = [0.0] + [max(close[i - 1] - close[i], 0) for i in range(1, len(close))]
    g, l = ref_wilder(gains[1:], n), ref_wilder(losses[1:], n)
    out = [math.nan]
    for a, b in zip(g, l):
        out.append(math.nan if math.isnan(a) else (100.0 if b == 0 else 100 - 100 / (1 + a / b)))
    return out


def ref_tr(h, l, c) -> list[float]:
    out = [h[0] - l[0]]
    for i in range(1, len(c)):
        out.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return out


def ref_atr(h, l, c, n=14):
    return ref_wilder(ref_tr(h, l, c), n)


def ref_bollinger(close: list[float], n: int = 20, k: float = 2.0):
    """Bollinger's definition: population standard deviation (divide by n)."""
    up, lo = [math.nan] * len(close), [math.nan] * len(close)
    for i in range(n - 1, len(close)):
        w = close[i - n + 1:i + 1]
        m = sum(w) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in w) / n)
        up[i], lo[i] = m + k * sd, m - k * sd
    return up, lo


def ref_stoch_k(h, l, c, n=14):
    out = [math.nan] * len(c)
    for i in range(n - 1, len(c)):
        hh, ll = max(h[i - n + 1:i + 1]), min(l[i - n + 1:i + 1])
        out[i] = math.nan if hh == ll else 100 * (c[i] - ll) / (hh - ll)
    return out


def ref_adx(h, l, c, n=14):
    pdm, mdm = [0.0], [0.0]
    for i in range(1, len(c)):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    tr = ref_tr(h, l, c)
    s_tr, s_p, s_m = ref_wilder(tr[1:], n), ref_wilder(pdm[1:], n), ref_wilder(mdm[1:], n)
    dx = []
    for a, b, t in zip(s_p, s_m, s_tr):
        if math.isnan(t) or t == 0:
            dx.append(math.nan)
            continue
        pdi, mdi = 100 * a / t, 100 * b / t
        dx.append(math.nan if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    first = next(i for i, v in enumerate(dx) if not math.isnan(v))
    adx = [math.nan] * len(dx)
    adx[first + n - 1] = sum(dx[first:first + n]) / n
    for i in range(first + n, len(dx)):
        adx[i] = (adx[i - 1] * (n - 1) + dx[i]) / n
    return [math.nan] + adx


def _max_rel_diff(ours, ref, start=WARMUP) -> float:
    worst = 0.0
    for a, b in zip(list(ours)[start:], list(ref)[start:]):
        if a is None or b is None or math.isnan(a) or math.isnan(b):
            continue
        worst = max(worst, abs(a - b) / max(abs(b), 1e-9))
    return worst


@check("5", "5.1", "Every indicator matches an independent implementation of its published definition")
def indicators_match_references():
    df = _df()
    h, l, c = df["high"].tolist(), df["low"].tolist(), df["close"].tolist()
    ours = {
        "EMA(20)": (ind.ema(df["close"], 20), ref_ema(c, 20)),
        "RSI(14)": (ind.rsi(df["close"], 14), ref_rsi(c, 14)),
        "ATR(14)": (ind.atr(df, 14), ref_atr(h, l, c, 14)),
        "ADX(14)": (ind.adx(df, 14), ref_adx(h, l, c, 14)),
        "Stochastic %K(14)": (ind.stochastic(df)["k"], ref_stoch_k(h, l, c, 14)),
        "Bollinger upper(20,2)": (ind.bollinger_bands(df["close"])["upper"], ref_bollinger(c)[0]),
        "Bollinger lower(20,2)": (ind.bollinger_bands(df["close"])["lower"], ref_bollinger(c)[1]),
    }
    diffs = {k: round(_max_rel_diff(a, b) * 100, 4) for k, (a, b) in ours.items()}
    # After a 250-bar warm-up, seeding differences are gone. What is left
    # is a difference in the formula itself.
    wrong = {k: v for k, v in diffs.items() if v > 0.01}
    return Result(FAIL if wrong else PASS,
                  f"{len(diffs)} indicators on {len(df)} real bars; {len(wrong)} differ from their definition "
                  f"after warm-up by more than 0.01%",
                  {"max_relative_diff_pct_after_warmup": diffs, "disagree": wrong})


@check("5", "5.2", "Bollinger's standard deviation: how much the sample-vs-population choice moves the signals")
def bollinger_ddof_impact():
    """pandas' rolling().std() divides by n-1. Bollinger's definition divides
    by n. The bands differ by a fixed factor, sqrt(20/19) ~ 1.026, so the
    question is only how many signals it flips — measured on the two
    patterns that depend on it, which are the two best-ranked in the system."""
    from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
    df, regime = load_daily_data("^NSEI", 7000)
    out = {}
    orig = pd.Series.rolling

    for name in ("bollinger_reversion", "bollinger_upper_rejection"):
        spec = STRATEGY_REGISTRY.get(name)
        if not spec:
            continue
        sample = spec["fn"](df, regime, **spec["params"]).astype(bool)
        # Recompute with population std by swapping the band function.
        saved = ind.bollinger_bands

        def population(series, window=20, num_std=2):
            mid = series.rolling(window).mean()
            sd = series.rolling(window).std(ddof=0)
            return pd.DataFrame({"mid": mid, "upper": mid + num_std * sd, "lower": mid - num_std * sd})

        import backtest.strategies as s1
        import backtest.strategies_v2 as s2
        s1_saved, s2_saved = getattr(s1, "bollinger_bands", None), getattr(s2, "bollinger_bands", None)
        try:
            for mod in (ind, s1, s2):
                if hasattr(mod, "bollinger_bands"):
                    mod.bollinger_bands = population
            fixed = spec["fn"](df, regime, **spec["params"]).astype(bool)
        finally:
            ind.bollinger_bands = saved
            if s1_saved is not None:
                s1.bollinger_bands = s1_saved
            if s2_saved is not None:
                s2.bollinger_bands = s2_saved
        out[name] = {"signals_sample_std": int(sample.sum()), "signals_population_std": int(fixed.sum()),
                     "only_with_sample_std": int((sample & ~fixed).sum()),
                     "only_with_population_std": int((fixed & ~sample).sum())}
    pd.Series.rolling = orig
    changed = sum(v["only_with_sample_std"] + v["only_with_population_std"] for v in out.values())
    return Result(WARN if changed else PASS,
                  f"band width differs by x{math.sqrt(20/19):.4f}; {changed} signal(s) change across the two "
                  "Bollinger patterns if the published definition is used", out)


@check("5", "5.3", "No indicator or regime label changes when future bars are removed")
def indicators_no_lookahead():
    df = _df()
    rng = random.Random(7)
    cuts = sorted(rng.sample(range(300, len(df) - 1), 25))
    funcs = {
        "ema": lambda d: ind.ema(d["close"], 20),
        "rsi": lambda d: ind.rsi(d["close"]),
        "atr": lambda d: ind.atr(d),
        "adx": lambda d: ind.adx(d),
        "bollinger": lambda d: ind.bollinger_bands(d["close"])["lower"],
        "stochastic": lambda d: ind.stochastic(d)["k"],
        "macd": lambda d: ind.macd(d["close"])["histogram"],
        "supertrend": lambda d: ind.supertrend(d)["direction"].astype(float),
        "regime": lambda d: classify_regime_series(d).map(
            {"TREND_BULL": 1, "TREND_BEAR": 2, "RANGE": 3, "TRANSITION": 4, "UNKNOWN": 0}).astype(float),
    }
    full = {k: f(df) for k, f in funcs.items()}
    leaks = []
    for k, f in funcs.items():
        for cut in cuts:
            truncated = f(df.iloc[:cut])
            a, b = full[k].iloc[cut - 1], truncated.iloc[-1]
            if not (pd.isna(a) and pd.isna(b)) and abs(a - b) > 1e-9 * max(1, abs(a)):
                leaks.append((k, str(df.index[cut - 1].date()), float(a), float(b)))
                break
    return Result(FAIL if leaks else PASS,
                  f"{len(funcs)} series x {len(cuts)} random cut points; {len(leaks)} changed when the future was removed",
                  {"leaks": leaks})


@check("5", "5.4", "The regime classifier refuses to label bars it does not have the history for")
def regime_min_history():
    df = _df()
    short = df.iloc[:30]
    try:
        r = classify_regime(short)
        raised = False
        label = r.regime
    except ValueError:
        raised, label = True, None
    series = classify_regime_series(df)
    unknown = int((series == "UNKNOWN").sum())
    # The slow EMA needs its span: the 50th bar is the first with 50 bars of
    # history, so the first 49 must be UNKNOWN and no more.
    need = 49
    early_labelled = int((series.iloc[:need] != "UNKNOWN").sum())
    status = FAIL if not raised or early_labelled else PASS
    return Result(status,
                  f"on 30 bars classify_regime {'raised as documented' if raised else f'returned {label!r} instead of raising'}; "
                  f"the series labels {early_labelled} of its first {need} bars (only {unknown} UNKNOWN in total)",
                  {"docstring_says": "Not enough history to classify regime (need 50+ bars)."})


@check("5", "5.5", "Regime labels are distributed plausibly and are not stuck")
def regime_distribution():
    df = _df()
    s = classify_regime_series(df)
    dist = (s.value_counts(normalize=True) * 100).round(1).to_dict()
    runs = (s != s.shift()).cumsum()
    longest = int(s.groupby(runs).size().max())
    stuck = any(v > 70 for v in dist.values())
    return Result(WARN if stuck else PASS, f"distribution %: {dist}; longest unbroken run {longest} bars",
                  {"distribution_pct": dist, "longest_run": longest})


@check("5", "5.6", "An IV percentile never changes when later days are removed")
def iv_percentile_no_lookahead():
    import sqlite3
    import tempfile
    from pathlib import Path

    import backtest.iv_research as ivr
    full = ivr.load_series()
    if full.empty:
        return Result(WARN, "no IV series yet")
    rng = random.Random(5)
    cuts = sorted(rng.sample(range(300, len(full) - 1), 8))
    real_db = ivr.IV_DB
    leaks = []
    try:
        for cut in cuts:
            scratch = Path(tempfile.mkdtemp()) / "iv.db"
            conn = sqlite3.connect(scratch)
            conn.executescript(ivr.SCHEMA)
            keep = full.iloc[:cut]
            conn.executemany("INSERT INTO iv_daily (trade_date, iv_30d) VALUES (?, ?)",
                             list(zip(keep.index, keep["iv_30d"])))
            conn.commit()
            conn.close()
            ivr.IV_DB = scratch
            a, b = full["iv_pct"].iloc[cut - 1], ivr.load_series()["iv_pct"].iloc[-1]
            if not (pd.isna(a) and pd.isna(b)) and abs(a - b) > 1e-9:
                leaks.append((full.index[cut - 1], float(a), float(b)))
    finally:
        ivr.IV_DB = real_db
    return Result(FAIL if leaks else PASS,
                  f"{len(cuts)} random cut points; {len(leaks)} percentile(s) changed when later days were removed",
                  {"leaks": leaks})
