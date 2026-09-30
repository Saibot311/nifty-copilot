"""The strategy pipeline's Phase 2: five pre-registered hypotheses for an
option buyer on NIFTY, each one fixed rule, judged once on 2024-26 against the
same option bought with no signal.

Two are daily, priced at real NSE closes from the options archive:
  event_straddle      scheduled RBI policy decisions, Union Budgets and
                      general-election results
  cheap_vol_straddle  implied volatility below what the index has been doing

Three are intraday, from published intraday-momentum research, priced by the
course study's option model (Black-Scholes on the real 5-minute index path at
the previous session's implied volatility; the archive has no intraday
option prices):
  noise_band          Zarattini, Aziz & Barbon (2024), adapted
  last_half_hour      Gao, Han, Li & Zhou (2018)
  opening_range_5m    Zarattini & Aziz (2023)

Nothing here is tuned: every number below is in the registration, and a
changed idea is a new test.
"""

import json
import math
import statistics
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .course_strategies import (DEV_START, SPLIT, OptionModel, Series, _trade, baseline_sample, load_bars,
                                load_daily, load_expiries, load_iv, period_of, run_exit, summarise)
from .hypothesis_log import log_run
from .instrument_study import MIN_OPEN_INTEREST, Archive
from .options_engine import LOT_SIZE, OptionsCostModel
from .walkforward import holdout_verdict, welch_t_stat

API_DIR = Path(__file__).parent.parent
RESEARCH_PATH = API_DIR / "data" / "nifty_pipeline.json"

# Every MPC decision on RBI's own monetary-policy page (rbi.org.in, Annual
# Policy, the dated block carrying "Resolution of the Monetary Policy
# Committee"), 2018 to 2026, read 2026-09-30.
RBI_DECISIONS = (
    "2018-02-07", "2018-04-05", "2018-06-06", "2018-08-01", "2018-10-05", "2018-12-05",
    "2019-02-07", "2019-04-04", "2019-06-06", "2019-08-07", "2019-10-04", "2019-12-05",
    "2020-02-06", "2020-03-27", "2020-05-22", "2020-08-06", "2020-10-09", "2020-12-04",
    "2021-02-05", "2021-04-07", "2021-06-04", "2021-08-06", "2021-10-08", "2021-12-08",
    "2022-02-10", "2022-04-08", "2022-05-04", "2022-06-08", "2022-08-05", "2022-09-30", "2022-12-07",
    "2023-02-08", "2023-04-06", "2023-06-08", "2023-08-10", "2023-10-06", "2023-12-08",
    "2024-02-08", "2024-04-05", "2024-06-07", "2024-08-08", "2024-10-09", "2024-12-06",
    "2025-02-07", "2025-04-09", "2025-06-06", "2025-08-06", "2025-10-01", "2025-12-05",
    "2026-02-06", "2026-04-08", "2026-06-05", "2026-08-05",
)
# Announced without notice, so no one could have bought the day before.
RBI_OFF_CYCLE = ("2020-03-27", "2020-05-22", "2022-05-04")
# Union Budget presentations (full and interim); weekend ones had special NSE sessions.
BUDGETS = ("2018-02-01", "2019-02-01", "2019-07-05", "2020-02-01", "2021-02-01", "2022-02-01", "2023-02-01",
           "2024-02-01", "2024-07-23", "2025-02-01", "2026-02-01")
ELECTION_RESULTS = ("2019-05-23", "2024-06-04")

PREREGISTERED = {
    "registered": "2026-09-30, before any of these five had been computed on NIFTY data",
    "source": ("The strategy pipeline's plan, approved by the owner 2026-09-30: event and volatility-timing "
               "straddles, and three published intraday-momentum rules adapted to NIFTY's session. Zarattini, "
               "Aziz & Barbon (2024) SSRN 4824172; Gao, Han, Li & Zhou (2018) JFE 129(2); Zarattini & Aziz "
               "(2023), the 5-minute opening range."),
    "already_seen": (
        "Before registering: NIFTY's 5.93% fall on the 2024 election result with India VIX at 20.94 the evening "
        "before (one holdout event, the prompt for the event idea); the volatility premium measured on "
        "2018-2026, by year (implied above delivered on 71% of days; unconditional, not the rule below); the "
        "intraday study's time-of-day drift on 2015-2026 (the first 15 minutes fell on average, t = -7.2); the "
        "afternoon-breakout study's index results; and Phase 1 (2019-23 only). No conditional return of any "
        "rule below had been computed."),
    "instrument": (
        "Phase 1's rule as fixed, confirmed by the owner 2026-09-30: the nearest expiry that outlasts the hold, "
        "at the money. Phase 1 also showed the choice rests on the assumed 1.5%-of-premium slippage; without it "
        "the monthly is cheaper. The owner chose to test now on the rule as fixed."),
    "costs": "The rate card (options_engine.OptionsCostModel) with 1.5% of premium slippage a side, as every study.",
    "periods": ("Development: entries from 2018-01-01 with the exit before 2024. Holdout: entries from 2024-01-01. "
                "Judged once, on the holdout."),
    "verdict": ("APPROVED only if the option return is positive in both periods, beats the same option bought "
                "with no signal in both, has at least 15 holdout trades, and its holdout Welch t against that "
                "baseline clears the Bonferroni bar for 65 hypotheses at its own degrees of freedom."),
    "hypotheses": {
        "event_straddle": {
            "label": "Event straddle", "timeframe": "1d",
            "rule": ("Buy the at-the-money call and put (the strike nearest NIFTY's close where both have open "
                     "interest of at least 1,000 and traded that day; the nearest expiry after the event day) "
                     "at the close of the session before each scheduled event, and sell both at the event "
                     "session's close. Events: RBI MPC decisions except the three off-cycle ones, Union Budget "
                     "presentations, general-election results."),
            "baseline": "The same straddle bought at every other session's close and sold at the next close.",
        },
        "cheap_vol_straddle": {
            "label": "Cheap-volatility straddle", "timeframe": "1d",
            "rule": ("At a close where the 30-day at-the-money implied volatility (iv.db, iv_30d) is below the "
                     "annualised standard deviation of NIFTY's last 21 daily log returns (x sqrt 252), buy the "
                     "at-the-money straddle at the next session's close (the nearest expiry after the exit) and "
                     "sell it 5 sessions later at the close. One position at a time."),
            "baseline": "The same straddle, entered at the next close after every session where the rule did not hold.",
        },
        "noise_band": {
            "label": "Noise-band momentum", "timeframe": "5m",
            "rule": ("For each 5-minute time of day, the band is the average over the previous 14 sessions of "
                     "|close at that time / that session's open - 1| (at least 10 of the 14 must have the bar). "
                     "Upper = max(today's open, previous close) x (1 + band); lower = min(...) x (1 - band). At "
                     "the closes of 09:45, 10:15, ... 15:15, the first close above the upper buys the call, "
                     "below the lower buys the put. Exits are checked on the same half-hourly closes: out at the "
                     "first one back inside the band, else at 15:25 (or the last bar of a short session). One "
                     "trade a day. The paper's VWAP stop is dropped: NIFTY has no volume."),
            "baseline": "The same option bought at the same clock time, held as many bars, on every session.",
        },
        "last_half_hour": {
            "label": "Last-half-hour momentum", "timeframe": "5m",
            "rule": ("The sign of NIFTY's return from the previous close to 09:45 picks the side. Buy the call "
                     "(up) or put (down) at 15:00 and sell at 15:25."),
            "baseline": "The same option bought at 15:00 and sold at 15:25 on every session.",
        },
        "opening_range_5m": {
            "label": "5-minute opening range", "timeframe": "5m",
            "rule": ("The first 5-minute candle's colour picks the side (none if unchanged). Buy the call "
                     "(green) or put (red) at its close, 09:20; exit if the index reaches that candle's low "
                     "(call) or high (put), else at 15:25. The paper's ten-times-risk target is left out, as in "
                     "the approved plan."),
            "baseline": "The same option bought at 09:20 and held as long, on every session.",
        },
    },
    "option_pricing": ("Daily straddles: real NSE closing prices of both legs. Intraday: the course study's "
                       "OptionModel, at the money, the nearest expiry that does not expire that day."),
    "event_dates": {"rbi_decisions": RBI_DECISIONS, "rbi_off_cycle_excluded": RBI_OFF_CYCLE, "budgets": BUDGETS,
                    "election_results": ELECTION_RESULTS,
                    "sources": ("RBI Annual Policy page (rbi.org.in); Union Budget dates as presented in "
                                "Parliament; Election Commission results days")},
}
TESTS_IN_FAMILY = 65
MIN_HOLDOUT_TRADES = 15
PREREG_HASH = "e0dd9b3f9fe1986b"

COSTS = OptionsCostModel()
NOISE_LOOKBACK, NOISE_MIN_SESSIONS = 14, 10
RV_WINDOW, STRADDLE_HOLD = 21, 5


def events() -> list[str]:
    off = set(RBI_OFF_CYCLE)
    return sorted({*(d for d in RBI_DECISIONS if d not in off), *BUDGETS, *ELECTION_RESULTS})


# --- intraday rules -----------------------------------------------------------------

def _at(s: Series, d: date, minutes: int) -> int | None:
    b0, b1 = s.bounds[d]
    where = np.flatnonzero(s.hm[b0:b1 + 1] == minutes)
    return b0 + int(where[0]) if len(where) else None


def _prev_close(s: Series, daily_close: dict, k: int) -> float:
    prev = s.sessions[k - 1]
    return daily_close.get(prev) or float(s.c[s.bounds[prev][1]])


def noise_band(s: Series, daily_close: dict) -> list[dict]:
    moves = {}
    for d in s.sessions:
        b0, b1 = s.bounds[d]
        moves[d] = {int(s.hm[i]): abs(s.c[i] / s.o[b0] - 1) for i in range(b0, b1 + 1)}
    first, last, step, flat = 9 * 60 + 45, 15 * 60 + 15, 30, 15 * 60 + 25

    def check(i: int) -> bool:                           # a bar stamped 09:40 closes at 09:45
        end = int(s.hm[i]) + 5
        return first <= end <= last and (end - first) % step == 0

    trades = []
    for k, d in enumerate(s.sessions):
        if k < NOISE_LOOKBACK:
            continue
        prior = s.sessions[k - NOISE_LOOKBACK:k]

        def band(t: int) -> float | None:
            vals = [moves[p][t] for p in prior if t in moves[p]]
            return sum(vals) / len(vals) if len(vals) >= NOISE_MIN_SESSIONS else None

        b0, b1 = s.bounds[d]
        pc = _prev_close(s, daily_close, k)
        hi_ref, lo_ref = max(s.o[b0], pc), min(s.o[b0], pc)
        for i in range(b0, b1 + 1):
            if not check(i):
                continue
            sig = band(int(s.hm[i]))
            if sig is None:
                continue
            side = 1 if s.c[i] > hi_ref * (1 + sig) else -1 if s.c[i] < lo_ref * (1 - sig) else 0
            if not side or i == b1:
                continue
            exit_i, reason = b1, "time"
            for j in range(i + 1, b1 + 1):
                if int(s.hm[j]) + 5 >= flat:
                    exit_i, reason = j, "time"
                    break
                if not check(j):
                    continue
                sj = band(int(s.hm[j]))
                if sj is not None and (s.c[j] < hi_ref * (1 + sj) if side > 0 else s.c[j] > lo_ref * (1 - sj)):
                    exit_i, reason = j, "back inside"
                    break
            trades.append(_trade(s, i, exit_i, side, s.c[i], s.c[exit_i], reason))
            break                                        # the first break of the day only
    return trades


def last_half_hour(s: Series, daily_close: dict) -> list[dict]:
    trades = []
    for k, d in enumerate(s.sessions):
        if k == 0:
            continue
        i45, i_in, i_out = _at(s, d, 9 * 60 + 40), _at(s, d, 14 * 60 + 55), _at(s, d, 15 * 60 + 20)
        if None in (i45, i_in, i_out):
            continue
        r = s.c[i45] / _prev_close(s, daily_close, k) - 1
        if r == 0:
            continue
        side = 1 if r > 0 else -1
        trades.append(_trade(s, i_in, i_out, side, s.c[i_in], s.c[i_out], "time"))
    return trades


def opening_range_5m(s: Series) -> list[dict]:
    trades = []
    for d in s.sessions:
        b0, _ = s.bounds[d]
        i_out = _at(s, d, 15 * 60 + 20)
        if s.hm[b0] != 9 * 60 + 15 or i_out is None or s.c[b0] == s.o[b0]:
            continue
        side = 1 if s.c[b0] > s.o[b0] else -1
        stop = s.l[b0] if side > 0 else s.h[b0]
        x, px, why = run_exit(s, b0, side, s.c[b0], stop, 1e12 if side > 0 else -1e12, i_out)
        trades.append(_trade(s, b0, x, side, s.c[b0], px, why))
    return trades


# --- daily straddles on real closes ---------------------------------------------------

def straddle(archive: Archive, day: str, exit_day: str, spot: float) -> dict | None:
    """Both legs at the strike nearest the close that both trade, the nearest
    expiry after the exit, bought at `day`'s close and sold at `exit_day`'s."""
    rows = archive.day(day)
    expiries = sorted({k[0] for k in rows if k[0] > exit_day})
    if not expiries:
        return None
    expiry = expiries[0]

    def ok(r):
        return r is not None and (r["open_interest"] or 0) >= MIN_OPEN_INTEREST and (r["close"] or 0) > 0 \
            and (r["contracts"] or 0) > 0
    strikes = [k[1] for k in rows if k[0] == expiry and k[2] == "CE" and ok(rows[k]) and ok(rows.get((expiry, k[1], "PE")))]
    if not strikes:
        return None
    strike = min(strikes, key=lambda x: (abs(x - spot), x))
    ce, pe = float(rows[(expiry, strike, "CE")]["close"]), float(rows[(expiry, strike, "PE")]["close"])
    out = archive.day(exit_day)
    xce, xpe = out.get((expiry, strike, "CE")), out.get((expiry, strike, "PE"))
    if xce is None or xpe is None or not (xce["close"] or 0) > 0 or not (xpe["close"] or 0) > 0:
        return None
    xce, xpe = float(xce["close"]), float(xpe["close"])
    costs = (COSTS.buy_cost_rs(ce, LOT_SIZE, day) + COSTS.buy_cost_rs(pe, LOT_SIZE, day)
             + COSTS.sell_cost_rs(xce, LOT_SIZE, exit_day) + COSTS.sell_cost_rs(xpe, LOT_SIZE, exit_day))
    paid = (ce + pe) * LOT_SIZE
    net = (xce + xpe - ce - pe) * LOT_SIZE - costs
    return {"entry": day, "exit": exit_day, "expiry": expiry, "strike": strike, "premium_in": round(ce + pe, 2),
            "premium_out": round(xce + xpe, 2), "spot": spot, "option_pct": round(100 * net / paid, 3)}


def realised_vol(closes: list[float]) -> float | None:
    if len(closes) < RV_WINDOW + 1:
        return None
    r = [math.log(b / a) for a, b in zip(closes[-RV_WINDOW - 1:-1], closes[-RV_WINDOW:])]
    return statistics.stdev(r) * math.sqrt(252)


def _period(entry: str, exit_: str) -> str | None:
    return period_of(date.fromisoformat(entry), date.fromisoformat(exit_))


def event_straddle(archive: Archive, sessions: list[str], spot: dict) -> tuple[list[dict], list[dict]]:
    ev = set(events())
    trades, base = [], []
    for k in range(len(sessions) - 1):
        day, nxt = sessions[k], sessions[k + 1]
        if day not in spot:
            continue
        t = straddle(archive, day, nxt, spot[day])
        if t:
            (trades if nxt in ev else base).append({**t, "event": nxt in ev})
    return trades, base


def trailing_rv(spot: dict) -> dict:
    """Each session's realised volatility over the 21 daily returns ending at its close."""
    days = sorted(spot)
    closes = [spot[d] for d in days]
    return {d: realised_vol(closes[k - RV_WINDOW:k + 1]) for k, d in enumerate(days) if k >= RV_WINDOW}


def cheap_vol_straddle(archive: Archive, sessions: list[str], spot: dict, iv: dict) -> tuple[list[dict], list[dict]]:
    rvs = trailing_rv(spot)
    trades, base, busy_until = [], [], ""
    for k in range(len(sessions) - 1 - STRADDLE_HOLD):
        day = sessions[k]
        rv = rvs.get(day)
        if rv is None or day not in iv:
            continue
        entry, exit_ = sessions[k + 1], sessions[k + 1 + STRADDLE_HOLD]
        signal = iv[day] < rv
        if signal and entry < busy_until:
            continue                                     # one position at a time
        t = straddle(archive, entry, exit_, spot[entry]) if entry in spot else None
        if not t:
            continue
        t = {**t, "signal_day": day, "iv": round(iv[day], 4), "rv": round(rv, 4)}
        if signal:
            trades.append(t)
            busy_until = exit_
        else:
            base.append(t)
    return trades, base


# --- judging ------------------------------------------------------------------------

def _verdict(by_period: dict, base_by_period: dict) -> dict:
    from stats.multiple_comparisons import required_t
    out = {}
    for p in ("development", "holdout"):
        rets = [t["option_pct"] for t in by_period[p]]
        base = base_by_period[p]
        out[p] = {**summarise(rets), "baseline_mean_pct": round(float(np.mean(base)), 3) if base else None,
                  "baseline_n": len(base),
                  "t_vs_baseline": welch_t_stat(rets, base) if len(rets) > 1 and len(base) > 1 else None,
                  "trades": by_period[p]}
    dev, hold = out["development"], out["holdout"]
    n = hold.get("num_trades", 0)
    bar = required_t(TESTS_IN_FAMILY, df=n - 1) if n > 1 else None
    if dev.get("num_trades", 0) and n:
        verdict, reason = holdout_verdict(
            dev["mean_pct"], hold["mean_pct"], dev["baseline_mean_pct"] or 0.0, hold["baseline_mean_pct"] or 0.0,
            n, MIN_HOLDOUT_TRADES, holdout_t=hold["t_vs_baseline"], min_t=bar,
            baseline_label="the same option bought with no signal", unit="%")
    else:
        verdict, reason = "REJECTED", "Too few trades in one of the periods to judge."
    return {"verdict": verdict, "reason": reason, "required_t": bar, **out}


def judge_daily(trades: list[dict], base: list[dict]) -> dict:
    split = lambda rows: {p: [t for t in rows if _period(t["entry"], t["exit"]) == p]  # noqa: E731
                          for p in ("development", "holdout")}
    tp, bp = split(trades), split(base)
    return _verdict(tp, {p: [t["option_pct"] for t in bp[p]] for p in bp})


def judge_intraday(name: str, trades: list[dict], s: Series, model: OptionModel, eligible: set) -> dict:
    by_period = {"development": [], "holdout": []}
    for t in trades:
        p = period_of(pd.Timestamp(t["entry_ts"]).date(), pd.Timestamp(t["exit_ts"]).date())
        if p is None:
            continue
        r = model.trade_return(name, t["side"], pd.Timestamp(t["entry_ts"]), pd.Timestamp(t["exit_ts"]),
                               t["entry"], t["exit"])
        if r:
            by_period[p].append({**t, **r})
    base = {}
    for p, rows in by_period.items():
        lo, hi = (DEV_START, SPLIT) if p == "development" else (SPLIT, date(2100, 1, 1))
        base[p] = baseline_sample(name, rows, s, model, sorted(d for d in eligible if lo <= d < hi))
    return _verdict(by_period, base)


def run_nifty_pipeline() -> dict:
    expiries, iv_near, daily = load_expiries(), load_iv(), load_daily()
    daily_close = {d: float(c) for d, c in daily["close"].items()}
    s5 = Series(load_bars("5m"))
    model = OptionModel(s5.sessions, expiries, iv_near)
    intraday = {
        "noise_band": (noise_band(s5, daily_close), set(s5.sessions[NOISE_LOOKBACK:])),
        "last_half_hour": (last_half_hour(s5, daily_close), set(s5.sessions[1:])),
        "opening_range_5m": (opening_range_5m(s5), set(s5.sessions)),
    }
    archive = Archive()
    sessions = archive.sessions(DEV_START.isoformat(), "2100-01-01")
    spot = {d.isoformat(): c for d, c in daily_close.items()}
    daily_runs = {"event_straddle": event_straddle(archive, sessions, spot),
                  "cheap_vol_straddle": cheap_vol_straddle(archive, sessions, spot, archive.iv)}
    results = {}
    for name, (trades, base) in daily_runs.items():
        results[name] = judge_daily(trades, base)
    for name, (trades, eligible) in intraday.items():
        results[name] = judge_intraday(name, trades, s5, model, eligible)
    for name, v in results.items():
        v["label"] = PREREGISTERED["hypotheses"][name]["label"]
        hold = v["holdout"]
        log_run(f"pipeline_{name}", {"prereg": PREREG_HASH, "timeframe": PREREGISTERED["hypotheses"][name]["timeframe"]},
                "^NSEI", 0, {"num_trades": hold.get("num_trades"), "expectancy_pct": hold.get("mean_pct")})
    out = {"computed_at": datetime.now().isoformat(timespec="seconds"), "prereg_hash": PREREG_HASH,
           "preregistered": PREREGISTERED, "tests_in_family": TESTS_IN_FAMILY,
           "hypotheses": [{"name": k, **v} for k, v in results.items()]}
    RESEARCH_PATH.write_text(json.dumps(out, default=str))
    return out


def load_nifty_pipeline() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None
