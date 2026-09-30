"""Which option a buyer should hold — the strategy pipeline's Phase 1.

Every signal tested here has failed, and buying options with no signal loses
money: the buyer pays the volatility premium, the spread and the costs. No
signal is needed to lose less of that. This measures, on development data
only (entries from the first NIFTY weekly, 14 Feb 2019, with every exit
before 2024), what holding NIFTY exposure costs through each kind of option:

  expiry     the nearest one that outlasts the hold, or the nearest monthly
             (the last expiry of its month) at least 14 days out
  moneyness  1% out of the money, at the money, 1% in the money
  hold       1, 3 and 5 sessions, close to close

Bought with no signal on every session, calls and puts alike, at real NSE
closes, with the rate-card costs every study uses (backtest/options_engine).

The measure is the cost of carrying one point of NIFTY exposure for one
session: the net rupees a trade made, per unit, divided by the option's
delta at entry (Black-Scholes on that day's 30-day implied volatility) and by
the sessions held. Percent of premium would favour in-the-money options for
the wrong reason — they barely decay in percent — so it is reported, not used
to choose. Calls and puts are averaged with equal weight, so NIFTY's own drift
over those years cancels instead of passing for a cheap instrument.

The choices are fixed here, before the numbers exist:
  event straddle (hypothesis D1, held one session): the expiry with the lower
      at-the-money carry at a 1-session hold;
  cheap-volatility straddle (D2, held five): the same at a 5-session hold;
  directional (the Today tab's intraday contract line): the expiry and
      moneyness with the lowest carry at a 1-session hold.

This is not a hypothesis about an edge: it chooses an instrument on
development data and never looks at 2024-26, so it adds nothing to the
multiple-testing count.
"""

import math
import sqlite3
import statistics
from datetime import date
from functools import lru_cache
from pathlib import Path

from .options_engine import LOT_SIZE, OptionsCostModel
from .pattern_options import SPLIT_DATE

API_DIR = Path(__file__).parent.parent
OPTIONS_DB = API_DIR / "data" / "nifty_options.db"
IV_DB = API_DIR / "data" / "iv.db"
RESULT_PATH = API_DIR / "data" / "instrument_study.json"

START = "2019-02-14"                 # the first NIFTY weekly expiry
HOLDS = (1, 3, 5)
MONEYNESS = {"1% OTM": 0.01, "ATM": 0.0, "1% ITM": -0.01}   # positive is out of the money
EXPIRY_CHOICES = ("nearest", "monthly")
MONTHLY_MIN_DAYS = 14
MIN_OPEN_INTEREST = 1000             # as the paper book and the option choice
COSTS = OptionsCostModel()


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def delta(kind: str, spot: float, strike: float, years: float, vol: float) -> float | None:
    """Black-Scholes delta, carry left out, as a positive number."""
    if years <= 0 or vol <= 0:
        return None
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * years) / (vol * math.sqrt(years))
    return _ncdf(d1) if kind == "CE" else 1 - _ncdf(d1)


class Archive:
    """One session's option rows at a time, cached: a few thousand look-ups
    against the archive instead of a hundred thousand."""

    def __init__(self, db: Path = OPTIONS_DB, iv_db: Path = IV_DB):
        self.conn = _ro(db)
        self.iv = {r[0]: r[1] for r in _ro(iv_db).execute("SELECT trade_date, iv_30d FROM iv_daily WHERE iv_30d > 0")}
        expiries = [r[0] for r in self.conn.execute("SELECT DISTINCT expiry_date FROM option_bars")]
        by_month: dict[str, str] = {}
        for e in expiries:
            by_month[e[:7]] = max(by_month.get(e[:7], e), e)
        self.monthly = set(by_month.values())

    def sessions(self, first: str, before: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT trade_date FROM option_bars WHERE trade_date >= ? AND trade_date < ? ORDER BY 1",
            (first, before))]

    @lru_cache(maxsize=64)
    def day(self, trade_date: str) -> dict:
        rows = self.conn.execute("SELECT expiry_date, strike, option_type, close, contracts, open_interest "
                                 "FROM option_bars WHERE trade_date = ?", (trade_date,)).fetchall()
        return {(r["expiry_date"], r["strike"], r["option_type"]): r for r in rows}


def pick(archive: Archive, day: str, spot: float, kind: str, moneyness: float, choice: str, exit_day: str):
    """(expiry, strike, entry close) a buyer would take at the close of `day`,
    or None. The expiry outlasts the exit; the strike has real open interest
    and a trade that day."""
    rows = archive.day(day)
    expiries = sorted({k[0] for k in rows if k[0] > exit_day})
    if choice == "monthly":
        expiries = [e for e in expiries if e in archive.monthly
                    and (date.fromisoformat(e) - date.fromisoformat(day)).days >= MONTHLY_MIN_DAYS]
    if not expiries:
        return None
    expiry = expiries[0]
    target = spot * (1 + moneyness) if kind == "CE" else spot * (1 - moneyness)
    tradeable = [k[1] for k, r in rows.items() if k[0] == expiry and k[2] == kind
                 and (r["open_interest"] or 0) >= MIN_OPEN_INTEREST and (r["close"] or 0) > 0 and (r["contracts"] or 0) > 0]
    if not tradeable:
        return None
    strike = min(tradeable, key=lambda s: (abs(s - target), s))
    return expiry, strike, float(rows[(expiry, strike, kind)]["close"])


def exit_close(archive: Archive, exit_day: str, expiry: str, strike: float, kind: str) -> float | None:
    r = archive.day(exit_day).get((expiry, strike, kind))
    return float(r["close"]) if r is not None and (r["close"] or 0) > 0 else None


def trade(archive: Archive, sessions: list[str], i: int, spot_by_day: dict, kind: str, moneyness: float,
          choice: str, hold: int, costs: OptionsCostModel = COSTS) -> dict | None:
    if i + hold >= len(sessions):
        return None
    day, exit_day = sessions[i], sessions[i + hold]
    spot, vol = spot_by_day.get(day), archive.iv.get(day)
    if not spot or not vol:
        return None
    picked = pick(archive, day, spot, kind, moneyness, choice, exit_day)
    if picked is None:
        return None
    expiry, strike, entry = picked
    out = exit_close(archive, exit_day, expiry, strike, kind)
    if out is None:
        return None
    d = delta(kind, spot, strike, (date.fromisoformat(expiry) - date.fromisoformat(day)).days / 365, vol)
    if not d or d < 0.02:
        return None
    net_rs = (out - entry) * LOT_SIZE - costs.buy_cost_rs(entry, LOT_SIZE, day) - costs.sell_cost_rs(out, LOT_SIZE, exit_day)
    return {"entry": day, "exit": exit_day, "expiry": expiry, "strike": strike, "kind": kind,
            "net_pct": 100 * net_rs / (entry * LOT_SIZE), "cost_pct": costs.cost_pct(entry, out, day, exit_day),
            "carry_pts": -(net_rs / LOT_SIZE) / d / hold, "days_to_expiry": (date.fromisoformat(expiry) - date.fromisoformat(day)).days}


def _cell(trades: list[dict]) -> dict:
    by_kind = {k: [t for t in trades if t["kind"] == k] for k in ("CE", "PE")}
    if not all(by_kind.values()):
        return {"trades": len(trades)}
    mean = lambda k, f: statistics.mean(t[f] for t in by_kind[k])  # noqa: E731
    return {
        "trades": len(trades),
        # Calls and puts weighted equally: NIFTY's drift cancels.
        "carry_pts_per_session": round((mean("CE", "carry_pts") + mean("PE", "carry_pts")) / 2, 2),
        "net_pct": round((mean("CE", "net_pct") + mean("PE", "net_pct")) / 2, 2),
        "cost_pct": round((mean("CE", "cost_pct") + mean("PE", "cost_pct")) / 2, 2),
        "median_net_pct": round(statistics.median(t["net_pct"] for t in trades), 2),
        "days_to_expiry": round(statistics.median(t["days_to_expiry"] for t in trades), 1),
    }


def run_instrument_study(archive: Archive | None = None, spot_by_day: dict | None = None,
                         costs: OptionsCostModel = COSTS, sensitivity: bool = True) -> dict:
    archive = archive or Archive()
    if spot_by_day is None:
        from .strategies import load_daily_data
        df, _ = load_daily_data("^NSEI", 4000)
        spot_by_day = {str(ts.date()): float(c) for ts, c in df["close"].items()}
    sessions = archive.sessions(START, SPLIT_DATE)
    combos = [(choice, label, m, hold) for choice in EXPIRY_CHOICES for label, m in MONEYNESS.items() for hold in HOLDS]
    found: dict[tuple, list[dict]] = {(c, lb, h): [] for c, lb, _, h in combos}
    # Sessions outermost: each day's rows are read once and stay cached
    # while every combination that enters or exits on it is priced.
    for i in range(len(sessions)):
        for choice, label, m, hold in combos:
            for kind in ("CE", "PE"):
                t = trade(archive, sessions, i, spot_by_day, kind, m, choice, hold, costs)
                if t:
                    found[(choice, label, hold)].append(t)
    cells = [{"expiry": c, "moneyness": lb, "hold": h, **_cell(found[(c, lb, h)])} for c, lb, _, h in combos]

    def best(pool):
        pool = [c for c in pool if "carry_pts_per_session" in c]
        return min(pool, key=lambda c: c["carry_pts_per_session"]) if pool else None

    atm = lambda hold: [c for c in cells if c["moneyness"] == "ATM" and c["hold"] == hold]  # noqa: E731
    d1, d2 = best(atm(1)), best(atm(5))
    directional = best([c for c in cells if c["hold"] == 1])
    # The slippage the studies assume is a share of premium, which charges an
    # expensive monthly contract far more in points than a real spread would.
    # The choice above stands as fixed; this says how much it rests on that.
    no_slip = (run_instrument_study(archive, spot_by_day, OptionsCostModel(premium_slippage_pct=0.0), False)
               if sensitivity else None)
    return {
        "without_assumed_slippage": ({"choices": no_slip["choices"], "cells": no_slip["cells"]} if no_slip else None),
        "period": {"from": sessions[0] if sessions else None, "to": sessions[-1] if sessions else None,
                   "sessions": len(sessions), "note": "development only: every exit before 2024"},
        "cells": cells,
        "choices": {
            "event_straddle": {"expiry": d1["expiry"] if d1 else None, "hold": 1},
            "cheap_vol_straddle": {"expiry": d2["expiry"] if d2 else None, "hold": 5},
            "directional": ({"expiry": directional["expiry"], "moneyness": directional["moneyness"]}
                            if directional else None),
        },
        "rule": ("Lowest carry cost per point of NIFTY exposure per session, calls and puts weighted equally, "
                 "on 2019-02-14 to 2023 entries only. Fixed before the numbers were computed."),
        "costs": costs.summary(date(2023, 12, 29)),
    }


def load_instrument_study() -> dict | None:
    import json
    return json.loads(RESULT_PATH.read_text()) if RESULT_PATH.exists() else None
