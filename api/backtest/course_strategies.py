"""Five intraday strategies from a trading course, tested the project's way.

The user's own strategy notes (Booming Bulls Academy PDFs: Gap Fill, TMS Pro
option buying, Nifty Triple Sync, Impulsive Momentum, Trap Trading). Each
note gives indicators and entry conditions but leaves the stop, the target
and a few terms ("definitive candle", "DCC", "trend") to the trader's eye —
"target and SL will be logical". A rule a program cannot follow cannot be
tested, so every gap is closed below with one fixed reading, written down
(PREREGISTERED) and hashed before any of the five was computed on NIFTY.
Nothing is chosen from a grid; a reading that turns out badly is a result,
not a reason to try another.

Two limits, said up front:
  * The options archive is end-of-day, so no intraday option price exists.
    The verdict measure is a modelled option: Black-Scholes on the real
    intraday index path, with the previous session's implied volatility and
    the real NSE expiry calendar, and the project's per-leg costs. It prices
    delta, gamma and theta; it does not know the day's IV moves or the
    bid-ask on that strike at that minute (the cost model's slippage stands
    in for the spread).
  * Trap Trading was written for EURUSD/GBPUSD in the London session. The
    user asked for it on NIFTY; it is adapted (first 4-hour block of the
    NSE session, pip filters converted to percent) and reported as an
    adaptation, not the original.
"""

import json
import math
from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from quant.indicators import adx, ema, supertrend

from .hypothesis_log import log_run
from .options_engine import OptionsCostModel
from .walkforward import holdout_verdict, welch_t_stat

API_DIR = Path(__file__).parent.parent
RESEARCH_PATH = API_DIR / "data" / "course_research.json"

# --- fixed before any result was computed; do not edit after seeing one ------
PREREGISTERED = {
    "registered": "2026-09-27, before any of these five had been computed on NIFTY data",
    "source": ("The user's PDFs: GAP FILL UPDATED VERSION, TMS PRO - UPDATED VERSION OPTION BUYING, NIFTY "
               "TRIPLE SYNC STRATEGY, IMPULSIVE MOMENTUM STRATEGY, Trap Trading Strategy, and the NIFTY "
               "STRATEGIES SCHEDULE (which days each is used). The course's own option-selling variant is not "
               "tested: this project only buys options."),
    "already_seen": (
        "Before registering: the course's own claimed results (TMS Pro Jan 2023-May 2025: 205 trades, +5,209 "
        "index points, 47.8% win; Triple Sync ~2 years: ~103 trades, 64.9% win; Gap Fill ~3 years: ~66 trades, "
        "55% win; Impulsive Momentum ~2.5 years; Trap 1.5 years on EURUSD/GBPUSD: 142 trades, 59% win), the "
        "course's example charts, this project's rejected 'Opening gap pushed back' structural test (a daily, "
        "overnight option hold, not an intraday gap fill), and the count of 5-minute bars downloaded. No "
        "conditional return of any rule below on NIFTY had been computed."),
    "web_research": (
        "Searched 2026-09-27 for the course's definitions ('definitive candle 60:40', 'DCC', TMS Pro, the "
        "trap). None was published; the readings below are the standard ones: a gap-fill target at the "
        "previous close with the stop beyond the day's extreme; a range trap as a sweep of the range "
        "followed by a close back inside it, stop beyond the last two candles."),
    "data": ("NIFTY 50 index bars from the local archive (Kite): 15-minute for TMS Pro, 5-minute for the other "
             "four, 2015 onward for indicator warm-up; the official daily close (1d archive) where a strategy "
             "reads the previous close. Timestamps are bar starts, IST; the session is 09:15-15:30."),
    "common": (
        "Indicators on the strategy's own timeframe over the continuous series: EMA(200, close); Supertrend "
        "(ATR by Wilder's smoothing, the stated length and factor); ADX(14, 14). A definitive candle is one "
        "whose body is at least 60% of its high-low range, coloured in the trade's direction ('60:40'). "
        "Entries are at the close of the entry candle. Stops and targets are checked on later bars; a gap "
        "through a level exits at the open; when a bar touches both, the stop is assumed first. An intraday "
        "trade still open exits at the close of the day's last bar (15:25 on 5-minute bars). One position at "
        "a time. The schedule's weekdays were set for Thursday weekly expiry and are translated to the "
        "expiry calendar: 'Mon, Tue, Wed & Fri' becomes every session except an expiry session; 'Mon-Thu' "
        "becomes every session except the first session after an expiry."),
    "option_model": (
        "The verdict is on a bought option: a call for a long signal, a put for a short one. Premium by "
        "Black-Scholes (no rates, no dividends) on the index price at entry and exit, with the previous "
        "session's near-expiry implied volatility (iv_daily.iv_near) held for the trade, and time to the "
        "chosen expiry's 15:30 close. Strike: nearest 50 to spot (ATM), except where a strategy says "
        "otherwise. Expiry: the nearest expiry after the entry date (never one expiring that day), except "
        "where a strategy says otherwise. Return = premium change as % of the premium paid, minus the "
        "project's per-leg option costs (OptionsCostModel.cost_pct). Index points and percent are reported "
        "beside it, for comparison with the course's own figures, and are not the verdict."),
    "periods": ("Development: trades entered 2018-01-01 to 2023-12-31 and closed before 2024-01-01. Holdout: "
                "trades entered from 2024-01-01 to the archive's end. A trade straddling the split is dropped."),
    "baseline": (
        "For each trade: the same option (same side, strike and expiry rule), bought at the same clock time "
        "and held for the same number of bars, on every other session of the same period that the strategy "
        "would trade — being in the market the same way with no signal. The period's baseline is the mean "
        "of all of those; Welch's t compares the trades with that sample."),
    "verdict": (
        "The project's ladder (walkforward.holdout_verdict), unit %: profitable in both periods, better than "
        "the baseline in both, a holdout t above the Bonferroni bar for 58 hypotheses (the 53 already judged "
        "plus these five) at the strategy's own holdout trades minus one, then at least 15 holdout trades."),
    "hypotheses": {
        "tms_pro": {
            "label": "TMS Pro (option buying)", "timeframe": "15m", "days": "every session",
            "rules": (
                "Long setup: close above EMA200 and Supertrend(13, 3) bullish; short setup mirrors. A setup "
                "episode is a run of consecutive bars with the setup true. Entry at the close of the first "
                "definitive candle in the setup's direction within an episode; one trade per episode. Stop: "
                "the nearer of the entry candle's low and the EMA200 below entry (mirror for shorts), capped at "
                "0.55% from entry, on a closing basis. Also exits: a touch 0.55% against entry (the max-pain "
                "stop), at that level, or at the open if the market opens beyond it; a touch 0.6% in favour "
                "(the fixed target); a close on which Supertrend has turned against the trade. May be held "
                "overnight. Strike: 100 points in the money on the current expiry with 3+ sessions to go, 150 "
                "in the money with 2, at the money on the next expiry with 1 or 0 (the course's Mon/Fri, Tue, "
                "Wed/Thu table under Thursday expiry)."),
        },
        "triple_sync": {
            "label": "Nifty Triple Sync", "timeframe": "5m", "days": "not the first session after an expiry",
            "rules": (
                "Bullish conditions: close above EMA200, Supertrend(10, 2) bullish and ADX above 25; bearish "
                "mirror. The conditions must turn true (false on the bar before, which may be the previous "
                "session's last) on a bar starting 09:15-10:05; if they were already true, no trade that day. "
                "Entry at the close of the first definitive candle in that direction from that bar through the "
                "10:05 bar, while the conditions still hold. Stop: the entry candle's low (high for shorts), "
                "on a touch. Target: 1.5 times the risk (the course's minimum reward:risk). One trade a day."),
        },
        "gap_fill": {
            "label": "Gap Fill", "timeframe": "5m", "days": "every session",
            "rules": (
                "From the official daily candles of the three prior sessions: body high = highest of "
                "max(open, close), body low = lowest of min(open, close); trade only if (body high - body "
                "low) / body low exceeds 1%. Trend is up if the prior session closed above the open of the "
                "first of the three, else down. Uptrend: only a short, only on a gap-up open; downtrend: only a "
                "long, only on a gap-down open; skip gaps beyond 1%. Entry: the first 5-minute close (from the "
                "second candle, bars starting up to 10:55) beyond the first candle's body (below its body low "
                "for a short), taken only if that close is still more than 0.20% from the previous close "
                "(only the first such close counts). Target: the previous close, on a touch. Stop: the day's "
                "extreme up to entry (high for a short), on a touch."),
        },
        "impulsive_momentum": {
            "label": "Impulsive Momentum", "timeframe": "5m", "days": "not an expiry session",
            "rules": (
                "An upside break is a close above EMA200 after a close at or below it (a downside break "
                "mirrors). After an upside break, a close back below the EMA opens the search for a virtual "
                "short: a DCC (two red candles in a row, the second closing below the first's low) or a "
                "bearish engulfing candle (a red body covering the previous green body). Virtual stop: the "
                "higher high of the pattern's two candles; virtual target: twice the risk. A close back above "
                "the EMA before a pattern restarts the wait for a retrace. If the virtual target is touched "
                "first, look for another virtual trade in the same context. If the virtual stop is touched "
                "first, the real trade is long, at the close of the first candle that closes above the virtual "
                "stop. Real stop: the lower low of the entry candle and the one before; real target: twice "
                "the risk. Real entries on bars starting by 14:45; one real trade a day."),
        },
        "trap_nifty": {
            "label": "Trap Trading (adapted to NIFTY)", "timeframe": "5m", "days": "not an expiry session",
            "rules": (
                "The range is the high and low (wicks included) of the session's first 4-hour block, bars "
                "starting 09:15-13:10. Skip the day if the range is under 0.09% of its low (the course's 10 "
                "pips on EURUSD near 1.10). Entry window: bars starting 13:15-15:10 (the London window cannot "
                "map onto NSE hours). Once a bar trades above the range high, the first close back at or below "
                "it is a sell trap (a short); the low mirrors (a long). Only the first trap counts. Skip if the "
                "entry close is within 0.027% of EMA200 (the course's 3 pips). Stop: beyond the last two "
                "candles' extreme; target: three times the risk (the course's fixed 1:3)."),
        },
    },
}
TESTS_IN_FAMILY = 58
MIN_HOLDOUT_TRADES = 15
DEV_START, SPLIT = date(2018, 1, 1), date(2024, 1, 1)

PREREG_HASH = "42e24490f0b52c4d"


# --- data ---------------------------------------------------------------------

def load_bars(timeframe: str, db_path: Path | None = None) -> pd.DataFrame:
    from market_data.bar_archive import ArchiveProvider
    candles = ArchiveProvider(db_path).get_ohlc("^NSEI", timeframe, date(2015, 1, 1), date(2100, 1, 1))
    idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
    return pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                         "low": [c.low for c in candles], "close": [c.close for c in candles]}, index=idx)


def load_daily(db_path: Path | None = None) -> pd.DataFrame:
    from market_data.bar_archive import ArchiveProvider
    candles = ArchiveProvider(db_path).get_ohlc("^NSEI", "1d", date(2014, 1, 1), date(2100, 1, 1))
    return pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                         "low": [c.low for c in candles], "close": [c.close for c in candles]},
                        index=[date.fromisoformat(c.timestamp[:10]) for c in candles])


def load_expiries() -> list[date]:
    from storage.sqlite_open import open_db
    with open_db(API_DIR / "data" / "nifty_options.db") as conn:
        rows = conn.execute("SELECT DISTINCT expiry_date FROM option_bars").fetchall()
    return sorted(date.fromisoformat(r[0]) for r in rows)


def load_iv() -> dict[date, float]:
    from storage.sqlite_open import open_db
    with open_db(API_DIR / "data" / "iv.db") as conn:
        rows = conn.execute("SELECT trade_date, iv_near, iv_30d FROM iv_daily").fetchall()
    return {date.fromisoformat(d): (near or thirty) for d, near, thirty in rows if (near or thirty)}


# --- the pieces every strategy uses -------------------------------------------

def definitive(o: float, h: float, lo: float, c: float, side: int) -> bool:
    rng = h - lo
    return rng > 0 and abs(c - o) >= 0.6 * rng and (c > o if side > 0 else c < o)


class Series:
    """A bar series as arrays, with each bar's session and clock time."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        self.ts = df.index
        self.day = np.array([t.date() for t in df.index])
        self.hm = np.array([t.hour * 60 + t.minute for t in df.index])
        self.sessions = sorted(set(self.day))
        starts = np.flatnonzero(np.r_[True, self.day[1:] != self.day[:-1]])
        ends = np.r_[starts[1:] - 1, len(df) - 1]
        self.bounds = {self.day[s]: (s, e) for s, e in zip(starts, ends)}


def hm(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)


def run_exit(s: Series, i: int, side: int, entry: float, stop: float, target: float, last: int) -> tuple[int, float, str]:
    """Touch stop and target from bar i+1 to `last`, then the close of `last`."""
    for j in range(i + 1, last + 1):
        if side > 0:
            if s.o[j] <= stop:
                return j, s.o[j], "stop"
            if s.l[j] <= stop:
                return j, stop, "stop"
            if s.o[j] >= target:
                return j, s.o[j], "target"
            if s.h[j] >= target:
                return j, target, "target"
        else:
            if s.o[j] >= stop:
                return j, s.o[j], "stop"
            if s.h[j] >= stop:
                return j, stop, "stop"
            if s.o[j] <= target:
                return j, s.o[j], "target"
            if s.l[j] <= target:
                return j, target, "target"
    return last, s.c[last], "time"


def _trade(s: Series, i: int, j: int, side: int, entry: float, exit_px: float, reason: str, **extra) -> dict:
    return {"entry_i": int(i), "exit_i": int(j), "side": int(side), "entry": round(entry, 2), "exit": round(exit_px, 2),
            "reason": reason, "entry_ts": s.ts[i].isoformat(), "exit_ts": s.ts[j].isoformat(),
            "points": round(side * (exit_px - entry), 2), "index_pct": round(side * (exit_px / entry - 1) * 100, 4),
            **extra}


# --- the five ------------------------------------------------------------------

def tms_pro(s: Series) -> list[dict]:
    e200 = ema(s.df["close"], 200).to_numpy()
    st = supertrend(s.df, 13, 3.0)["direction"].to_numpy()
    long_ok = (s.c > e200) & (st == 1)
    short_ok = (s.c < e200) & (st == -1)
    trades, i, n = [], 200, len(s.c)
    taken_long = taken_short = False
    while i < n:
        if not long_ok[i]:
            taken_long = False
        if not short_ok[i]:
            taken_short = False
        side = 1 if long_ok[i] and not taken_long else -1 if short_ok[i] and not taken_short else 0
        if side == 0 or not definitive(s.o[i], s.h[i], s.l[i], s.c[i], side):
            i += 1
            continue
        entry = s.c[i]
        if side > 0:
            stop = max(s.l[i], e200[i])
            stop = max(stop, entry * (1 - 0.0055))
            pain, target = entry * (1 - 0.0055), entry * 1.006
        else:
            stop = min(s.h[i], e200[i])
            stop = min(stop, entry * (1 + 0.0055))
            pain, target = entry * (1 + 0.0055), entry * 0.994
        taken_long, taken_short = (True, taken_short) if side > 0 else (taken_long, True)
        j, px, why = None, None, None
        for k in range(i + 1, n):
            opened = s.day[k] != s.day[k - 1]
            if side > 0:
                if opened and s.o[k] <= pain:
                    j, px, why = k, s.o[k], "max-pain gap"
                elif s.l[k] <= pain:
                    j, px, why = k, pain, "max-pain stop"
                elif s.h[k] >= target:
                    j, px, why = k, max(target, s.o[k]), "target"
                elif s.c[k] < stop:
                    j, px, why = k, s.c[k], "stop (close)"
                elif st[k] == -1:
                    j, px, why = k, s.c[k], "supertrend flip"
            else:
                if opened and s.o[k] >= pain:
                    j, px, why = k, s.o[k], "max-pain gap"
                elif s.h[k] >= pain:
                    j, px, why = k, pain, "max-pain stop"
                elif s.l[k] <= target:
                    j, px, why = k, min(target, s.o[k]), "target"
                elif s.c[k] > stop:
                    j, px, why = k, s.c[k], "stop (close)"
                elif st[k] == 1:
                    j, px, why = k, s.c[k], "supertrend flip"
            if j is not None:
                break
        if j is None:
            break  # still open at the end of the data: not a result
        trades.append(_trade(s, i, j, side, entry, px, why))
        # The episode flags carry through the trade: a new trade needs a new episode.
        for k in range(i + 1, j + 1):
            if not long_ok[k]:
                taken_long = False
            if not short_ok[k]:
                taken_short = False
        i = j + 1
    return trades


def triple_sync(s: Series, skip: set[date]) -> list[dict]:
    e200 = ema(s.df["close"], 200).to_numpy()
    st = supertrend(s.df, 10, 2.0)["direction"].to_numpy()
    a = adx(s.df, 14).to_numpy()
    bull = (s.c > e200) & (st == 1) & (a > 25)
    bear = (s.c < e200) & (st == -1) & (a > 25)
    trades = []
    for d in s.sessions:
        if d in skip:
            continue
        b0, b1 = s.bounds[d]
        if b0 < 200:
            continue
        window = [i for i in range(b0, b1 + 1) if hm("09:15") <= s.hm[i] <= hm("10:05")]
        done = False
        for i in window:
            for side, cond in ((1, bull), (-1, bear)):
                if cond[i] and not cond[i - 1]:
                    for j in (k for k in window if k >= i):
                        if not cond[j]:
                            break
                        if definitive(s.o[j], s.h[j], s.l[j], s.c[j], side):
                            entry = s.c[j]
                            stop = s.l[j] if side > 0 else s.h[j]
                            risk = abs(entry - stop)
                            if risk <= 0:
                                break
                            x, px, why = run_exit(s, j, side, entry, stop, entry + side * 1.5 * risk, b1)
                            trades.append(_trade(s, j, x, side, entry, px, why))
                            done = True
                            break
                    if done:
                        break
            if done:
                break
    return trades


def gap_fill(s: Series, daily: pd.DataFrame) -> list[dict]:
    days = list(daily.index)
    pos = {d: k for k, d in enumerate(days)}
    trades = []
    for d in s.sessions:
        k = pos.get(d)
        if k is None or k < 3:
            continue
        prior = daily.iloc[k - 3:k]
        body_hi = max(max(r.open, r.close) for r in prior.itertuples())
        body_lo = min(min(r.open, r.close) for r in prior.itertuples())
        if (body_hi - body_lo) / body_lo * 100 <= 1.0:
            continue
        up = prior["close"].iloc[-1] > prior["open"].iloc[0]
        pdc = float(prior["close"].iloc[-1])
        b0, b1 = s.bounds[d]
        gap = (s.o[b0] / pdc - 1) * 100
        if abs(gap) > 1.0 or gap == 0:
            continue
        if up and gap < 0 or not up and gap > 0:
            continue  # the course trades against the trend only, so only the gap that runs with it
        side = -1 if up else 1
        body_lo0, body_hi0 = min(s.o[b0], s.c[b0]), max(s.o[b0], s.c[b0])
        for i in range(b0 + 1, b1 + 1):
            if s.hm[i] > hm("10:55"):
                break
            broke = s.c[i] < body_lo0 if side < 0 else s.c[i] > body_hi0
            if not broke:
                continue
            # "Still more than 0.20% from the previous close": on the gap's side
            # of it, the gap not yet filled. (Until the first hand check this
            # measured either side, and took longs above an already-filled gap
            # whose "target" then lay below the entry.)
            if -side * (s.c[i] / pdc - 1) * 100 > 0.20:
                entry = s.c[i]
                stop = s.h[b0:i + 1].max() if side < 0 else s.l[b0:i + 1].min()
                x, px, why = run_exit(s, i, side, entry, stop, pdc, b1)
                trades.append(_trade(s, i, x, side, entry, px, why))
            break  # only the first close beyond the body counts
    return trades


def impulsive_momentum(s: Series, skip: set[date]) -> list[dict]:
    e200 = ema(s.df["close"], 200).to_numpy()
    trades = []
    for d in s.sessions:
        if d in skip:
            continue
        b0, b1 = s.bounds[d]
        if b0 < 200:
            continue
        ctx, state = 0, "break"   # break -> retrace -> pattern -> virtual -> real
        v_stop = v_target = None
        for i in range(b0, b1 + 1):
            above, was_above = s.c[i] > e200[i], s.c[i - 1] > e200[i - 1]
            if state == "break":
                if above != was_above:  # the day's first close through the EMA sets the side
                    ctx, state = (1 if above else -1), "retrace"
                continue
            if state == "retrace":
                if above == (ctx > 0):
                    continue            # still beyond the EMA: no retrace yet
                state = "pattern"       # a close back inside; this bar may start the pattern
            if state == "pattern":
                if above == (ctx > 0):
                    state = "retrace"   # back beyond the EMA before a pattern: wait again
                    continue
                vside = -ctx            # the virtual trade fades the break
                red, green = s.c[i] < s.o[i], s.c[i] > s.o[i]
                pr, pg = s.c[i - 1] < s.o[i - 1], s.c[i - 1] > s.o[i - 1]
                if vside < 0:
                    dcc = red and pr and s.c[i] < s.l[i - 1]
                    engulf = red and pg and s.o[i] >= s.c[i - 1] and s.c[i] <= s.o[i - 1]
                    v_stop = max(s.h[i], s.h[i - 1])
                else:
                    dcc = green and pg and s.c[i] > s.h[i - 1]
                    engulf = green and pr and s.o[i] <= s.c[i - 1] and s.c[i] >= s.o[i - 1]
                    v_stop = min(s.l[i], s.l[i - 1])
                if dcc or engulf:
                    v_target = s.c[i] + vside * 2 * abs(s.c[i] - v_stop)
                    state = "virtual"
                continue
            if state == "virtual":
                vside = -ctx
                hit_stop = s.h[i] >= v_stop if vside < 0 else s.l[i] <= v_stop
                hit_target = s.l[i] <= v_target if vside < 0 else s.h[i] >= v_target
                if hit_stop:
                    state = "real"      # this bar may also be the real entry
                elif hit_target:
                    state = "pattern"   # look for another virtual trade in the same context
                    continue
                else:
                    continue
            if state == "real":
                if s.hm[i] > hm("14:45"):
                    break
                if (s.c[i] > v_stop) if ctx > 0 else (s.c[i] < v_stop):
                    entry = s.c[i]
                    stop = min(s.l[i], s.l[i - 1]) if ctx > 0 else max(s.h[i], s.h[i - 1])
                    risk = abs(entry - stop)
                    if risk > 0:
                        x, px, why = run_exit(s, i, ctx, entry, stop, entry + ctx * 2 * risk, b1)
                        trades.append(_trade(s, i, x, ctx, entry, px, why))
                    break
    return trades


def trap_nifty(s: Series, skip: set[date]) -> list[dict]:
    e200 = ema(s.df["close"], 200).to_numpy()
    trades = []
    for d in s.sessions:
        if d in skip:
            continue
        b0, b1 = s.bounds[d]
        if b0 < 200:
            continue
        rng = [i for i in range(b0, b1 + 1) if s.hm[i] <= hm("13:10")]
        win = [i for i in range(b0, b1 + 1) if hm("13:15") <= s.hm[i] <= hm("15:10")]
        if not rng or not win:
            continue
        hi, lo = s.h[rng].max(), s.l[rng].min()
        if (hi - lo) / lo * 100 < 0.09:
            continue
        swept_hi = swept_lo = False
        for i in win:
            swept_hi |= s.h[i] > hi
            swept_lo |= s.l[i] < lo
            side = -1 if swept_hi and s.c[i] <= hi else 1 if swept_lo and s.c[i] >= lo else 0
            if side == 0:
                continue
            if abs(s.c[i] / e200[i] - 1) * 100 < 0.027:
                break
            entry = s.c[i]
            stop = max(s.h[i], s.h[i - 1]) if side < 0 else min(s.l[i], s.l[i - 1])
            risk = abs(entry - stop)
            if risk > 0:
                x, px, why = run_exit(s, i, side, entry, stop, entry + side * 3 * risk, b1)
                trades.append(_trade(s, i, x, side, entry, px, why))
            break
    return trades


# --- the option each trade would have bought ---------------------------------

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(side: int, spot: float, strike: float, t_years: float, vol: float) -> float:
    """Black-Scholes, no rates: a call for side > 0, a put for side < 0. At or
    past expiry it is the intrinsic value."""
    if t_years <= 1e-9 or vol <= 0:
        return max(spot - strike, 0.0) if side > 0 else max(strike - spot, 0.0)
    st = vol * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + 0.5 * st * st) / st
    d2 = d1 - st
    if side > 0:
        return spot * _ncdf(d1) - strike * _ncdf(d2)
    return strike * _ncdf(-d2) - spot * _ncdf(-d1)


class OptionModel:
    def __init__(self, sessions: list[date], expiries: list[date], iv: dict[date, float]):
        self.sessions = sessions
        self.pos = {d: k for k, d in enumerate(sessions)}
        self.expiries = expiries
        self.iv_days = sorted(iv)
        self.iv = iv
        self.cost = OptionsCostModel()

    def prior_iv(self, d: date) -> float | None:
        k = bisect_right(self.iv_days, d - timedelta(days=1))
        return self.iv[self.iv_days[k - 1]] if k else None

    def expiry_after(self, d: date, strictly: bool = True) -> date | None:
        k = bisect_right(self.expiries, d) if strictly else bisect_right(self.expiries, d - timedelta(days=1))
        return self.expiries[k] if k < len(self.expiries) else None

    def sessions_to(self, d: date, exp: date) -> int:
        """Sessions from d (counted) up to the expiry (not counted): 0 on expiry day."""
        from bisect import bisect_left
        return bisect_left(self.sessions, exp) - self.pos[d]

    def choose(self, strategy: str, d: date, spot: float, side: int) -> tuple[float, date] | None:
        atm = round(spot / 50) * 50
        if strategy == "tms_pro":
            current = self.expiry_after(d, strictly=False)
            if current is None:
                return None
            left = self.sessions_to(d, current)
            if left >= 3:
                offset, exp = 100, current
            elif left == 2:
                offset, exp = 150, current
            else:
                offset, exp = 0, self.expiry_after(current)
            if exp is None:
                return None
            return atm - side * offset, exp
        exp = self.expiry_after(d)
        return (atm, exp) if exp else None

    @staticmethod
    def years(ts: pd.Timestamp, exp: date) -> float:
        close = pd.Timestamp(datetime.combine(exp, time(15, 30)), tz=ts.tz)
        return max((close - ts).total_seconds(), 0) / (365 * 24 * 3600)

    def trade_return(self, strategy, side, entry_ts, exit_ts, spot_in, spot_out) -> dict | None:
        d = entry_ts.date()
        vol = self.prior_iv(d)
        pick = self.choose(strategy, d, spot_in, side)
        if vol is None or pick is None:
            return None
        strike, exp = pick
        p_in = bs_price(side, spot_in, strike, self.years(entry_ts, exp), vol)
        p_out = bs_price(side, spot_out, strike, self.years(exit_ts, exp), vol)
        if p_in <= 0.5:
            return None
        ret = (p_out / p_in - 1) * 100 - self.cost.cost_pct(p_in, p_out, d, exit_ts.date())
        return {"strike": strike, "expiry": exp.isoformat(), "premium_in": round(p_in, 2),
                "premium_out": round(p_out, 2), "iv": round(vol, 4), "option_pct": round(ret, 3)}


# --- judging -------------------------------------------------------------------

def period_of(entry: date, exit_: date) -> str | None:
    if DEV_START <= entry < SPLIT:
        return "development" if exit_ < SPLIT else None
    return "holdout" if entry >= SPLIT else None


def baseline_sample(strategy: str, trades: list[dict], s: Series, model: OptionModel,
                    eligible: list[date]) -> list[float]:
    """The same option bought at each trade's clock time, held as many bars,
    on every eligible session of the period — no signal."""
    out = []
    templates = {}
    for t in trades:
        key = (int(s.hm[t["entry_i"]]), t["exit_i"] - t["entry_i"], t["side"])
        templates[key] = templates.get(key, 0) + 1
    for (clock, hold, side), count in templates.items():
        for d in eligible:
            b0, b1 = s.bounds[d]
            where = np.flatnonzero(s.hm[b0:b1 + 1] == clock)
            if not len(where):
                continue
            i = b0 + int(where[0])
            j = i + hold
            if j >= len(s.c):
                continue
            r = model.trade_return(strategy, side, s.ts[i], s.ts[j], s.c[i], s.c[j])
            if r:
                out.extend([r["option_pct"]] * count)
    return out


def summarise(values: list[float]) -> dict:
    if not values:
        return {"num_trades": 0}
    a = np.asarray(values)
    return {"num_trades": len(a), "mean_pct": round(float(a.mean()), 3), "median_pct": round(float(np.median(a)), 3),
            "win_rate": round(float((a > 0).mean()) * 100, 1)}


def judge(strategy: str, trades: list[dict], s: Series, model: OptionModel, eligible: set[date]) -> dict:
    from stats.multiple_comparisons import required_t

    by_period = {"development": [], "holdout": []}
    for t in trades:
        p = period_of(pd.Timestamp(t["entry_ts"]).date(), pd.Timestamp(t["exit_ts"]).date())
        if p is None:
            continue
        r = model.trade_return(strategy, t["side"], pd.Timestamp(t["entry_ts"]), pd.Timestamp(t["exit_ts"]),
                               t["entry"], t["exit"])
        if r is None:
            continue
        by_period[p].append({**t, **r})
    out = {}
    for p, rows in by_period.items():
        lo, hi = (DEV_START, SPLIT) if p == "development" else (SPLIT, date(2100, 1, 1))
        days = sorted(d for d in eligible if lo <= d < hi)
        base = baseline_sample(strategy, rows, s, model, days)
        rets = [r["option_pct"] for r in rows]
        out[p] = {**summarise(rets),
                  "index_points_total": round(sum(r["points"] for r in rows), 1),
                  "index_points_mean": round(float(np.mean([r["points"] for r in rows])), 2) if rows else None,
                  "index_win_rate": round(float(np.mean([r["points"] > 0 for r in rows])) * 100, 1) if rows else None,
                  "baseline_mean_pct": round(float(np.mean(base)), 3) if base else None,
                  "baseline_n": len(base),
                  "t_vs_baseline": welch_t_stat(rets, base) if len(rets) > 1 and len(base) > 1 else None,
                  "exits": {k: sum(1 for r in rows if r["reason"] == k) for k in sorted({r["reason"] for r in rows})},
                  "trades": rows}
    dev, hold = out["development"], out["holdout"]
    n = hold.get("num_trades", 0)
    bar = required_t(TESTS_IN_FAMILY, df=n - 1) if n > 1 else None
    if dev.get("num_trades", 0) and n:
        verdict, reason = holdout_verdict(
            dev["mean_pct"], hold["mean_pct"], dev["baseline_mean_pct"] or 0.0, hold["baseline_mean_pct"] or 0.0,
            n, MIN_HOLDOUT_TRADES, holdout_t=hold["t_vs_baseline"], min_t=bar,
            baseline_label="the same option bought at the same times with no signal", unit="%")
    else:
        verdict, reason = "REJECTED", "Too few trades in one of the periods to judge."
    return {"verdict": verdict, "reason": reason, "required_t": bar, **out}


def by_year(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        y = t["entry_ts"][:4]
        row = out.setdefault(y, {"trades": 0, "points": 0.0, "wins": 0})
        row["trades"] += 1
        row["points"] = round(row["points"] + t["points"], 1)
        row["wins"] += t["points"] > 0
    return out


def window(trades: list[dict], start: str, end: str) -> dict:
    rows = [t for t in trades if start <= t["entry_ts"][:10] <= end]
    return {"from": start, "to": end, "trades": len(rows), "points": round(sum(t["points"] for t in rows), 1),
            "win_rate": round(float(np.mean([t["points"] > 0 for t in rows])) * 100, 1) if rows else None}


def run_course_research() -> dict:
    expiries = load_expiries()
    iv = load_iv()
    daily = load_daily()
    s15, s5 = Series(load_bars("15m")), Series(load_bars("5m"))
    exp_set = set(expiries)
    after_exp = {s5.sessions[k + 1] for k, d in enumerate(s5.sessions[:-1]) if d in exp_set}
    runs = {
        "tms_pro": (tms_pro(s15), s15, set(s15.sessions)),
        "triple_sync": (triple_sync(s5, after_exp), s5, set(s5.sessions) - after_exp),
        "gap_fill": (gap_fill(s5, daily), s5, set(s5.sessions)),
        "impulsive_momentum": (impulsive_momentum(s5, exp_set), s5, set(s5.sessions) - exp_set),
        "trap_nifty": (trap_nifty(s5, exp_set), s5, set(s5.sessions) - exp_set),
    }
    claimed = {"tms_pro": ("2023-01-01", "2025-05-31")}
    results = {}
    for name, (trades, series, eligible) in runs.items():
        model = OptionModel(series.sessions, expiries, iv)
        verdict = judge(name, trades, series, model, eligible)
        verdict["label"] = PREREGISTERED["hypotheses"][name]["label"]
        verdict["by_year"] = by_year(trades)
        if name in claimed:
            verdict["course_window"] = window(trades, *claimed[name])
        results[name] = verdict
        hold = verdict["holdout"]
        log_run(f"course_{name}", {"prereg": PREREG_HASH, "timeframe": PREREGISTERED["hypotheses"][name]["timeframe"]},
                "^NSEI", 0, {"num_trades": hold.get("num_trades"), "expectancy_pct": hold.get("mean_pct")})
    out = {"computed_at": datetime.now().isoformat(timespec="seconds"), "prereg_hash": PREREG_HASH,
           "preregistered": PREREGISTERED, "tests_in_family": TESTS_IN_FAMILY,
           "hypotheses": [{"name": k, **v} for k, v in results.items()]}
    RESEARCH_PATH.write_text(json.dumps(out, default=str))
    return out


def load_course_research() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None
