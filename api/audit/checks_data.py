"""Phase 0 and 4: is the data what it claims to be?

Everything downstream trusts these tables. A duplicated bar, a high below a
close, or an option priced off a stale quote does not raise an error — it
quietly becomes a signal, a trade, a verdict.
"""

import sqlite3
import statistics
from collections import defaultdict
from datetime import date, datetime

from market_data.bar_archive import DB_PATH as BARS_DB
from storage.options_db import DB_PATH as OPTIONS_DB

from . import FAIL, PASS, WARN, Result, check


def _bars(interval: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(BARS_DB)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT ts, open, high, low, close FROM index_bars "
                            "WHERE symbol='^NSEI' AND interval=? ORDER BY ts", (interval,)).fetchall()
    finally:
        conn.close()


def _ohlc_violations(rows) -> list[str]:
    bad = []
    for r in rows:
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        if min(o, h, l, c) <= 0:
            bad.append(f"{r['ts']}: non-positive price")
        elif not (l <= min(o, c) + 1e-6 and h >= max(o, c) - 1e-6 and l <= h):
            bad.append(f"{r['ts']}: O={o} H={h} L={l} C={c}")
    return bad


@check("0", "0.1", "Daily bars: no duplicates, OHLC consistent, no impossible gaps")
def daily_integrity():
    rows = _bars("1d")
    dates = [r["ts"][:10] for r in rows]
    dupes = len(dates) - len(set(dates))
    bad = _ohlc_violations(rows)
    # A gap over 7 calendar days in NIFTY data is not a holiday — it is
    # missing data, and every rolling indicator silently spans it.
    gaps = []
    for a, b in zip(dates, dates[1:]):
        d = (date.fromisoformat(b) - date.fromisoformat(a)).days
        if d > 7:
            gaps.append(f"{a} -> {b} ({d} days)")
    status = FAIL if dupes or bad else (WARN if gaps else PASS)
    return Result(status, f"{len(rows)} bars; {dupes} duplicate dates, {len(bad)} OHLC violations, "
                          f"{len(gaps)} gaps over a week",
                  {"first": dates[0], "last": dates[-1], "ohlc_violations": bad[:10], "gaps": gaps[:10]})


@check("0", "0.2", "15-minute bars: OHLC consistent, on the 15-minute grid, inside session hours")
def intraday_integrity():
    rows = _bars("15m")
    bad = _ohlc_violations(rows)
    off_grid, off_hours = [], []
    for r in rows:
        t = datetime.fromisoformat(r["ts"])
        if t.minute % 15 or t.second:
            off_grid.append(r["ts"])
        # 09:15 open to the 15:15 bar; Muhurat evening sessions are the
        # only legitimate exception.
        if not ((t.hour, t.minute) >= (9, 15) and (t.hour, t.minute) <= (15, 15)) and t.hour < 17:
            off_hours.append(r["ts"])
    status = FAIL if bad or off_grid else (WARN if off_hours else PASS)
    return Result(status, f"{len(rows)} bars; {len(bad)} OHLC violations, {len(off_grid)} off the grid, "
                          f"{len(off_hours)} outside 09:15-15:15",
                  {"ohlc_violations": bad[:10], "off_grid": off_grid[:10], "off_hours": off_hours[:10]})


# Bars that go beyond the day's official range cannot be real trades. The
# reverse — the official range reaching slightly past what 15-minute bars
# captured — is sampling, and conservative; it is reported, not failed.
SPIKE_POINTS = 20


def intraday_spikes() -> list[tuple[str, str, float]]:
    daily = {r["ts"][:10]: r for r in _bars("1d")}
    days = defaultdict(list)
    for r in _bars("15m"):
        days[r["ts"][:10]].append(r)
    out = []
    for d, bars in days.items():
        if d not in daily:
            continue
        over = max(b["high"] for b in bars) - daily[d]["high"]
        under = daily[d]["low"] - min(b["low"] for b in bars)
        if over > SPIKE_POINTS:
            out.append((d, "high", round(over, 2)))
        if under > SPIKE_POINTS:
            out.append((d, "low", round(under, 2)))
    return out


@check("0", "0.3", "15-minute bars never reach beyond the official daily range")
def daily_vs_intraday():
    spikes = intraday_spikes()
    daily = {r["ts"][:10]: r for r in _bars("1d")}
    first_open = {}
    for r in _bars("15m"):
        first_open.setdefault(r["ts"][:10], r["open"])
    opens = [abs(first_open[d] - daily[d]["open"]) for d in first_open if d in daily]
    open_off = sum(1 for x in opens if x > 0.5)
    return Result(WARN if spikes else PASS,
                  f"{len(spikes)} day(s) where a 15-minute bar exceeds the official high/low by over "
                  f"{SPIKE_POINTS} points (bad ticks in the source); opens disagree on {open_off} of {len(opens)} days",
                  {"spikes": spikes, "note": "Source data cannot be edited here; the loaders must not serve these. "
                                             "See check 4.2."})


@check("0", "0.4", "Two independent sources agree: Yahoo daily close vs Kite daily close")
def two_sources_agree():
    from backtest.strategies import load_daily_data
    yf, _ = load_daily_data("^NSEI", 7000)
    kite = {r["ts"][:10]: r["close"] for r in _bars("1d")}
    diffs = []
    for ts, c in yf["close"].items():
        d = str(ts.date())
        if d in kite:
            diffs.append((d, abs(c - kite[d]) / kite[d] * 100))
    big = [(d, round(x, 3)) for d, x in diffs if x > 0.1]
    status = FAIL if len(big) > 0.01 * len(diffs) else (WARN if big else PASS)
    return Result(status, f"{len(diffs)} overlapping days; {len(big)} differ by more than 0.1%",
                  {"median_diff_pct": round(statistics.median(x for _, x in diffs), 5),
                   "worst": sorted(big, key=lambda x: -x[1])[:8],
                   "note": "Signals are computed on Yahoo; the archive is Kite. They must be the same market."})


def _options_conn():
    conn = sqlite3.connect(OPTIONS_DB)
    conn.row_factory = sqlite3.Row
    return conn


@check("0", "0.5", "Options archive: prices, expiries and strikes are possible")
def options_integrity():
    conn = _options_conn()
    try:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        negative = q("SELECT COUNT(*) FROM option_bars WHERE close < 0 OR open < 0 OR high < 0 OR low < 0")
        expired = q("SELECT COUNT(*) FROM option_bars WHERE expiry_date < trade_date")
        ohlc = q("SELECT COUNT(*) FROM option_bars WHERE high > 0 AND low > 0 AND "
                 "(high < low OR close > high + 0.01 OR close < low - 0.01)")
        off_grid = q("SELECT COUNT(*) FROM option_bars WHERE CAST(strike AS INTEGER) % 50 != 0")
        total = q("SELECT COUNT(*) FROM option_bars")
        zero_close_with_oi = q("SELECT COUNT(*) FROM option_bars WHERE close = 0 AND open_interest > 0")
        ingested_empty = q("SELECT COUNT(*) FROM ingested_days WHERE row_count = 0")
    finally:
        conn.close()
    status = FAIL if negative or expired else (WARN if ohlc or off_grid else PASS)
    return Result(status, f"{total:,} rows; {negative} negative, {expired} past expiry, {ohlc} OHLC-inconsistent, "
                          f"{off_grid} strikes off the 50-point grid",
                  {"zero_close_but_open_interest": zero_close_with_oi, "ingested_days_with_no_rows": ingested_empty})


@check("0", "0.6", "Options obey put-call parity (European index options: C - P + K is flat across strikes)")
def put_call_parity():
    """The strongest independent check on option prices available here. For
    one expiry, C - P = e^-rT (F - K), so C - P + K barely moves across
    near-the-money strikes. A price that breaks that is a bad price — stale,
    untraded, or mis-keyed — whatever the archive says it is."""
    conn = _options_conn()
    try:
        days = [r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM option_bars ORDER BY trade_date")][::20]
        spreads, worst = [], []
        for d in days:
            exp = conn.execute(
                "SELECT expiry_date FROM option_bars WHERE trade_date=? AND expiry_date >= date(?, '+7 day') "
                "GROUP BY expiry_date ORDER BY expiry_date LIMIT 1", (d, d)).fetchone()
            if not exp:
                continue
            rows = conn.execute(
                "SELECT strike, option_type, close, open_interest FROM option_bars "
                "WHERE trade_date=? AND expiry_date=? AND close > 0 AND open_interest >= 1000",
                (d, exp[0])).fetchall()
            ce = {r["strike"]: r["close"] for r in rows if r["option_type"] == "CE"}
            pe = {r["strike"]: r["close"] for r in rows if r["option_type"] == "PE"}
            both = sorted(set(ce) & set(pe))
            if len(both) < 5:
                continue
            # Near the money: where C and P are both meaningful.
            mid = min(both, key=lambda k: abs(ce[k] - pe[k]))
            near = [k for k in both if abs(k - mid) <= 0.03 * mid]
            implied = [ce[k] - pe[k] + k for k in near]
            spread = (max(implied) - min(implied)) / mid * 100
            spreads.append(spread)
            worst.append((d, exp[0], round(spread, 3)))
    finally:
        conn.close()
    bad = [w for w in worst if w[2] > 0.5]
    status = FAIL if len(bad) > 0.1 * len(spreads) else (WARN if bad else PASS)
    return Result(status, f"{len(spreads)} sampled days; median spread of C-P+K across strikes "
                          f"{statistics.median(spreads):.3f}% of spot; {len(bad)} days over 0.5%",
                  {"worst_days": sorted(worst, key=lambda x: -x[2])[:8]})


@check("0", "0.7", "Options archive covers every trading day it claims to")
def options_coverage():
    conn = _options_conn()
    try:
        have = {r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM option_bars")}
    finally:
        conn.close()
    trading = {r["ts"][:10] for r in _bars("1d") if "2018-01-01" <= r["ts"][:10] <= max(have)}
    missing = sorted(trading - have)
    # Weekend sessions (Budget day, Muhurat, DR drills) are real but thin,
    # and entering a position in one is unrealistic. Weekday gaps are not.
    weekday = [d for d in missing if date.fromisoformat(d).weekday() < 5]
    weekend = [d for d in missing if date.fromisoformat(d).weekday() >= 5]
    # A recent gap means the nightly job is not doing its job. An old one
    # that --fill-gaps keeps retrying is a hole at the source: NSE's archive
    # returns 404 for 2021-03-30 although the index traded that day.
    recent = [d for d in weekday if (date.today() - date.fromisoformat(d)).days <= 7]
    status = FAIL if recent else (WARN if missing else PASS)
    return Result(status, f"{len(trading)} trading days since 2018; {len(weekday)} weekday session(s) and "
                          f"{len(weekend)} weekend special session(s) have no option data",
                  {"weekday_missing": weekday, "weekend_missing": weekend, "recent": recent,
                   "archive_ends": max(have), "note": "Older gaps are retried nightly by backfill_options.py --fill-gaps."})


@check("0", "0.8", "Implied volatility computed from the archive tracks India VIX")
def iv_tracks_vix():
    """India VIX is the exchange's own 30-day volatility from the same
    market. The IV here is computed independently, from closing prices and a
    forward read off put-call parity. If the two stop moving together, the
    calculation — or the archive — has gone wrong."""
    from backtest.iv_research import load_series, vix_check
    series = load_series()
    if series.empty:
        return Result(WARN, "no IV series yet — python scripts/iv_research.py")
    v = vix_check(series)
    corr = v.get("level_correlation") or 0
    fallback = float((series["method"] == "fallback").mean())
    status = FAIL if corr < 0.9 else (WARN if fallback > 0.05 else PASS)
    return Result(status, f"{v['compared_days']} days compared: correlation {corr}, VIX a median "
                          f"{v.get('median_gap_points')} points higher (it prices the skew); "
                          f"{fallback:.1%} of days needed an assumed forward", v)
