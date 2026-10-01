"""A forward test for rules on the option snapshots: real prices, a
no-signal baseline, and a refusal to judge before the sample is there.

The snapshots begin on 1 Oct 2026 and no source has them for any earlier
day, so a rule on order-flow features (backtest/orderflow_features.py) has no
past to be tested on. It can only be registered, then judged on sessions
recorded after its registration. This file is that judgement's machinery;
nothing here is registered.

A rule is one decision function, called on each snapshot of a session in its
entry window with the features so far (the last is "now") and the index's
5-minute bars that had closed by then. It returns +1 (buy the call), -1 (buy
the put) or None, and the first non-None is the session's one trade:

  contract  the pipeline's Phase 1 rule: the nearest expiry not expiring that
            day, at the money (the signal snapshot's spot, rounded to 50)
  entry     at the ASK, in the first snapshot of that contract stamped at or
            after the signal time plus `entry_delay_s` — the snapshot the rule
            read is the one it could not have traded on, since it is seen only
            once taken
  exit      at the BID, in the first snapshot stamped at or after the rule's
            exit time (a clock time, or a hold in minutes, never past 15:25)
  costs     options_engine.OptionsCostModel with premium_slippage_pct=0: the
            spread is already paid by buying the ask and selling the bid
  counted   only when both legs were priced within `max_late_s` of their times

The baseline is the same contract chosen the same way, bought and sold at the
same clock times as each trade, on every session from the registration on —
the question is whether the signal beats buying that option anyway. The
trades' clock times and sides are templates; the baseline mean is weighted
to the trades' mix of templates, and its standard error counts each session
once (copying a template's baseline once per trade would shrink it).

The judgement refuses to run until `min_sessions` sessions and `min_trades`
counted trades exist after the registration, and the sample then closes at
the session where both were first reached: re-running it later gives the
same answer, so it cannot be stopped at a lucky moment. A rule is APPROVED
only if its mean net return is positive, above the baseline's, and its t
against the baseline clears the Bonferroni bar for the family size frozen at
registration, at its own degrees of freedom.

To register a rule later: write its PREREGISTERED text and hash literal (as
backtest/nifty_pipeline.py and its test do), fix a ForwardSpec with the
registration date and the family count it is judged against, add it to
backtest/family.py once judged, and call `evaluate`.
"""

import math
import statistics
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from .options_engine import LOT_SIZE, OptionsCostModel
from .orderflow_features import (by_session, expiries_listed, read_rows, session_features, snapshots,
                                 traded_expiry)

STRIKE_STEP = 50
LAST_EXIT = time(15, 25)
BAR_MIN = 5
COSTS = OptionsCostModel(premium_slippage_pct=0.0)


@dataclass(frozen=True)
class Rule:
    name: str
    decide: Callable[[list[dict], pd.DataFrame], int | None]
    first_check: time = time(9, 45)        # snapshots before this are never decided on
    last_entry: time = time(14, 30)        # nor after this
    exit_at: time = LAST_EXIT              # the exit, unless a hold ends it sooner
    hold_minutes: int | None = None
    features_on: str = "traded"            # "traded": the contract's expiry; "nearest": the nearest listed


@dataclass(frozen=True)
class ForwardSpec:
    """What a registration fixes before any data it is judged on exists."""
    registered_on: date                    # sessions from this date on count; nothing before
    tests_in_family: int                   # the Bonferroni count the verdict is judged at
    min_sessions: int
    min_trades: int
    entry_delay_s: int = 60
    max_late_s: int = 360                  # a leg priced later than this after its time is not counted
    quantity: int = LOT_SIZE


# --- the contract and its prices ------------------------------------------------------

def contract(side: int, spot: float, day: date, expiries: list[date]) -> dict | None:
    """The nearest expiry not expiring that day, at the money (the same as
    briefing/intraday_live.contract; a test holds the two together)."""
    expiry = traded_expiry(day, expiries)
    if expiry is None:
        return None
    return {"expiry": expiry.isoformat(), "strike": round(spot / STRIKE_STEP) * STRIKE_STEP,
            "option_type": "CE" if side > 0 else "PE"}


class Quotes:
    """One session's quotes by contract, for 'the first snapshot at or after'."""

    def __init__(self, rows: list[dict]):
        self._by: dict[tuple, list[tuple[datetime, dict]]] = {}
        for r in rows:
            key = (r["expiry"], float(r["strike"]), r["option_type"])
            self._by.setdefault(key, []).append((datetime.fromisoformat(r["taken_at"][:19]), r))
        for v in self._by.values():
            v.sort(key=lambda x: x[0])

    def first_at_or_after(self, c: dict, at: datetime, field: str, max_late_s: int) -> dict | None:
        """The first quote of `c` stamped at or after `at` with a positive
        `field` (ask to buy, bid to sell), if one came within `max_late_s`."""
        seq = self._by.get((c["expiry"], float(c["strike"]), c["option_type"]), [])
        i = bisect_left([s for s, _ in seq], at)
        for stamp, r in seq[i:]:
            if (stamp - at).total_seconds() > max_late_s:
                return None
            if r.get(field) is not None and r[field] > 0:
                return {"taken_at": stamp.isoformat(), field: float(r[field])}
        return None


def price_trade(quotes: Quotes, day: date, c: dict, entry_at: datetime, exit_at: datetime,
                spec: ForwardSpec) -> dict:
    """Bought at the ask at or after `entry_at`, sold at the bid at or after
    `exit_at`, costs on each leg; `counted` only when both were priced."""
    buy = quotes.first_at_or_after(c, entry_at, "ask", spec.max_late_s)
    sell = quotes.first_at_or_after(c, exit_at, "bid", spec.max_late_s) if buy else None
    out = {"contract": c, "entry_target": entry_at.isoformat(), "exit_target": exit_at.isoformat(),
           "ask_in": buy and buy["ask"], "entry_at": buy and buy["taken_at"],
           "bid_out": sell and sell["bid"], "exit_at": sell and sell["taken_at"],
           "counted": bool(buy and sell and sell["taken_at"] > buy["taken_at"])}
    if out["counted"]:
        gross = (sell["bid"] / buy["ask"] - 1) * 100
        cost = COSTS.cost_pct(buy["ask"], sell["bid"], day, day, spec.quantity)
        out.update(gross_pct=round(gross, 3), cost_pct=round(cost, 3), net_pct=round(gross - cost, 3))
    return out


def _exit_time(rule: Rule, day: date, signal_at: datetime) -> datetime:
    end = datetime.combine(day, min(rule.exit_at, LAST_EXIT))
    if rule.hold_minutes is not None:
        end = min(end, signal_at + timedelta(minutes=rule.hold_minutes))
    return end


def bars_closed_by(bars: pd.DataFrame | None, t: datetime) -> pd.DataFrame:
    """The 5-minute bars whose window had closed by t (a bar stamped 10:05 closes at 10:10)."""
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    idx = bars.index.tz_convert("Asia/Kolkata").tz_localize(None) if bars.index.tz is not None else bars.index
    return bars[idx + timedelta(minutes=BAR_MIN) <= t]


# --- running a rule -------------------------------------------------------------------

def run_rule(rule: Rule, rows_by_day: dict[date, list[dict]], spec: ForwardSpec,
             bars: pd.DataFrame | None = None) -> list[dict]:
    """The rule's one trade on each session from the registration on; a
    session where it never fired has no row."""
    trades = []
    for day in sorted(d for d in rows_by_day if d >= spec.registered_on):
        rows = rows_by_day[day]
        listed = expiries_listed(rows)
        expiry = traded_expiry(day, listed) if rule.features_on == "traded" else (min(listed) if listed else None)
        if expiry is None:
            continue
        feats = session_features(snapshots(rows, expiry))
        for k, f in enumerate(feats):
            t = datetime.fromisoformat(f["taken_at"])
            if t.time() < rule.first_check:
                continue
            if t.time() > rule.last_entry:
                break
            side = rule.decide(feats[:k + 1], bars_closed_by(bars, t))
            if side not in (1, -1):
                continue
            c = contract(side, f["spot"], day, listed)
            if c is None:
                break
            entry_at = t + timedelta(seconds=spec.entry_delay_s)
            exit_at = _exit_time(rule, day, t)
            trades.append({"rule": rule.name, "day": day.isoformat(), "side": side, "signal_at": t.isoformat(),
                           "spot": f["spot"], **price_trade(Quotes(rows), day, c, entry_at, exit_at, spec)})
            break
    return trades


def _clock(iso: str) -> time:
    return datetime.fromisoformat(iso).time().replace(microsecond=0)


def template(trade: dict) -> tuple[time, time, int]:
    """(signal clock, exit clock, side): what the baseline repeats."""
    return _clock(trade["signal_at"]), _clock(trade["exit_target"]), trade["side"]


def baseline(trades: list[dict], rows_by_day: dict[date, list[dict]], spec: ForwardSpec,
             through: date | None = None) -> dict[tuple, list[float]]:
    """{template: net returns}: for each distinct template among the counted
    trades, the same option bought at the same signal clock (plus the entry
    delay) and sold at the same exit clock on every session from the
    registration on, signal or not, each session once."""
    out: dict[tuple, list[float]] = {}
    days = sorted(d for d in rows_by_day if d >= spec.registered_on and (through is None or d <= through))
    for tpl in sorted({template(t) for t in trades if t["counted"]}):
        sig, ex, side = tpl
        vals = []
        for day in days:
            rows = rows_by_day[day]
            listed = expiries_listed(rows)
            expiry = traded_expiry(day, listed)
            snaps = snapshots(rows, expiry) if expiry else []
            signal_at = datetime.combine(day, sig)
            before = [s for s in snaps if s["taken_at"] <= signal_at]
            if not before:
                continue
            c = contract(side, before[-1]["spot"], day, listed)    # the spot the rule would have seen
            p = price_trade(Quotes(rows), day, c, signal_at + timedelta(seconds=spec.entry_delay_s),
                            datetime.combine(day, ex), spec)
            if p["counted"]:
                vals.append(p["net_pct"])
        out[tpl] = vals
    return out


# --- judging --------------------------------------------------------------------------

def forward_t(trades: list[float], base: dict[tuple, list[float]], mix: dict[tuple, int]) -> dict:
    """The trades' mean against the baseline mean weighted to the trades' mix
    of templates. With one template this is exactly Welch's t
    (walkforward.welch_t_stat); with several, the baseline's variance is
    sum(w_k^2 var_k / n_k), each session counted once."""
    n = len(trades)
    total = sum(mix.values())
    usable = {k: v for k, v in base.items() if mix.get(k) and len(v) > 1}
    if n < 2 or not usable or set(usable) != {k for k, m in mix.items() if m}:
        return {"t": None, "baseline_mean_pct": None}
    w = {k: mix[k] / total for k in usable}
    b_mean = sum(w[k] * statistics.mean(v) for k, v in usable.items())
    b_var = sum(w[k] ** 2 * statistics.variance(v) / len(v) for k, v in usable.items())
    se = math.sqrt(statistics.variance(trades) / n + b_var)
    t = None if se == 0 else round((statistics.mean(trades) - b_mean) / se, 2)
    return {"t": t, "baseline_mean_pct": round(b_mean, 3), "baseline_n": sum(len(v) for v in usable.values())}


def closing_session(trades: list[dict], sessions: list[date], spec: ForwardSpec) -> date | None:
    """The first session by which both minimums were met, or None while either is short."""
    counted = sorted(date.fromisoformat(t["day"]) for t in trades if t["counted"])
    eligible = sorted(d for d in sessions if d >= spec.registered_on)
    if len(counted) < spec.min_trades or len(eligible) < spec.min_sessions:
        return None
    return max(counted[spec.min_trades - 1], eligible[spec.min_sessions - 1])


def judge(trades: list[dict], rows_by_day: dict[date, list[dict]], spec: ForwardSpec) -> dict:
    """The verdict on the fixed sample, or a refusal while it is too small."""
    from stats.multiple_comparisons import required_t

    sessions = sorted(d for d in rows_by_day if d >= spec.registered_on)
    counted = [t for t in trades if t["counted"] and date.fromisoformat(t["day"]) >= spec.registered_on]
    progress = {"sessions": len(sessions), "counted_trades": len(counted), "recorded_trades": len(trades),
                "min_sessions": spec.min_sessions, "min_trades": spec.min_trades}
    close = closing_session(counted, sessions, spec)
    if close is None:
        return {"status": "waiting", **progress,
                "reason": (f"Not judged: {len(sessions)} of {spec.min_sessions} sessions and {len(counted)} of "
                           f"{spec.min_trades} counted trades since {spec.registered_on.isoformat()}.")}
    sample = [t for t in counted if date.fromisoformat(t["day"]) <= close]
    base = baseline(sample, rows_by_day, spec, through=close)
    mix: dict[tuple, int] = {}
    for t in sample:
        mix[template(t)] = mix.get(template(t), 0) + 1
    rets = [t["net_pct"] for t in sample]
    stat = forward_t(rets, base, mix)
    n = len(rets)
    bar = required_t(spec.tests_in_family, df=n - 1)
    mean = round(statistics.mean(rets), 3)
    b = stat["baseline_mean_pct"]
    if mean <= 0:
        verdict, why = "REJECTED", f"Lost money: {mean}% a trade after costs."
    elif b is None or mean <= b:
        verdict, why = "REJECTED", f"No better than the same option bought with no signal: {mean}% against {b}%."
    elif stat["t"] is None or stat["t"] < bar:
        verdict, why = "REJECTED", (f"Ahead of the no-signal option ({mean}% against {b}%) by too little to tell "
                                    f"from luck: t = {stat['t']}, needs {bar}.")
    else:
        verdict, why = "APPROVED", f"{mean}% against {b}% a trade over {n} trades, t = {stat['t']} (bar {bar})."
    return {"status": "judged", **progress, "closed_on": close.isoformat(), "num_trades": n, "mean_pct": mean,
            **stat, "required_t": bar, "verdict": verdict, "reason": why}


def load_bars(start: date, end: date) -> pd.DataFrame:
    """NIFTY's archived 5-minute bars, indexed by their IST start time (naive)."""
    from market_data.bar_archive import ArchiveProvider
    candles = ArchiveProvider().get_ohlc("^NSEI", "5m", start, end)
    idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
    if idx.tz is not None:
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    return pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                         "low": [c.low for c in candles], "close": [c.close for c in candles]}, index=idx)


def evaluate(rule: Rule, spec: ForwardSpec, db_path: Path | None = None, bars: pd.DataFrame | None = None) -> dict:
    """Load the snapshots (read-only) and bars, run the rule, judge it."""
    rows_by_day = by_session(read_rows(db_path, start=spec.registered_on))
    if bars is None and rows_by_day:
        bars = load_bars(min(rows_by_day), max(rows_by_day))
    trades = run_rule(rule, rows_by_day, spec, bars)
    return {"rule": rule.name, "trades": trades, **judge(trades, rows_by_day, spec)}


# --- how much data a judgement needs ---------------------------------------------------

def trades_needed(edge_pct: float, sd_pct: float, tests: int, base_sd_pct: float | None = None,
                  sessions_per_trade: float = 1.0, templates: int = 1, cap: int = 100_000) -> int | None:
    """The fewest counted trades for an edge of `edge_pct` a trade over the
    baseline to reach the Bonferroni bar for `tests` hypotheses, if the
    edge were exactly that and the spreads exactly those: t = edge / se
    with se^2 = sd^2/n + base_sd^2 / (templates x sessions), sessions =
    n x sessions_per_trade (one template a side over every session). A floor
    for planning: half of real edges that size would fall short."""
    from stats.multiple_comparisons import required_t
    base_sd = sd_pct if base_sd_pct is None else base_sd_pct
    n = 2
    while n <= cap:
        sessions = n * sessions_per_trade
        se = math.sqrt(sd_pct ** 2 / n + base_sd ** 2 / (templates * sessions))
        if edge_pct / se >= required_t(tests, df=n - 1):
            return n
        n = n + 1 if n < 200 else int(n * 1.01) + 1
    return None
