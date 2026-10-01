"""What the bid-ask spread really costs a buyer, from the five-minute option
snapshots — the input the strategy pipeline's Phase 1 was missing.

Phase 1 (backtest/instrument_study) charges an assumed 1.5% of premium a side
for the spread. That assumption decides its answer: with it the nearest expiry
is cheapest, without it the monthly. A percent of premium charges an expensive
monthly contract far more in points than its real spread, so the answer has to
come from the spread itself, which option_snapshots.db has recorded since
1 Oct 2026 (storage/option_snapshots_db).

This measures the half-spread, (ask - bid) / 2, in index points and as a
percent of the mid, for each (expiry, moneyness) Phase 1 compares, choosing
the contract as Phase 1's pick() does:

  nearest   the nearest expiry after the snapshot's day (never one expiring
            that day)
  monthly   the last expiry of its month, at least 14 calendar days out
  moneyness the strike nearest spot * (1 + m) for a call, spot * (1 - m) for a
            put, m = +1% out of the money, 0, -1% in the money, among the
            strikes quoted on both sides

NSE stamps each expiry's chain separately, so a snapshot is one chain: its
time, its expiry and its spot. The expiries a day offers are those recorded
that day. The recorder keeps the two nearest expiries and the last one of the
first expiry's month, so a later month's last recorded expiry need not be its
monthly; one counts only when the recording shows the month is complete (an
expiry from a later month was recorded too). In the last two weeks of a month
that leaves no monthly at least 14 days out, and those days measure none.

The primary measure is the median over snapshots between 14:30 and 15:30,
because Phase 1 trades at the close; the all-day median is reported beside it.
A median, not a mean, so one stale quote cannot move it.

SpreadCostModel then charges that half-spread in points on each side in
place of the percent-of-premium slippage. Nothing here touches the 2024-26
holdout: the spreads are 2026 quotes, and Phase 1 prices 2019-23 with them.
"""

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .instrument_study import EXPIRY_CHOICES, MONEYNESS, MONTHLY_MIN_DAYS
from .options_engine import OptionsCostModel

API_DIR = Path(__file__).parent.parent
SNAPSHOTS_DB = API_DIR / "data" / "option_snapshots.db"

CLOSE_WINDOW = ("14:30:00", "15:30:59")    # IST, inclusive; the recorder's last chain is stamped by 15:30:59
CLOSE_WINDOW_LABEL = "14:30-15:30"


def _ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def classify_expiries(day: str, expiries) -> dict[str, str]:
    """{"nearest": expiry, "monthly": expiry} for a session `day`, from the
    expiries recorded that day; a choice with no qualifying expiry is left out."""
    listed = sorted(set(expiries))
    later = [e for e in listed if e > day]
    out = {}
    if later:
        out["nearest"] = later[0]
    if not listed:
        return out
    last_of_month: dict[str, str] = {}
    for e in listed:
        last_of_month[e[:7]] = max(last_of_month.get(e[:7], e), e)
    first_month, final_month = listed[0][:7], listed[-1][:7]
    for e in later:
        complete = e[:7] == first_month or e[:7] < final_month
        if (last_of_month[e[:7]] == e and complete
                and (date.fromisoformat(e) - date.fromisoformat(day)).days >= MONTHLY_MIN_DAYS):
            out["monthly"] = e
            break
    return out


def nearest_strike(quotes: dict[float, tuple[float, float]], target: float) -> float | None:
    """The strike nearest `target` among those quoted; ties to the lower, as pick()."""
    return min(quotes, key=lambda s: (abs(s - target), s)) if quotes else None


def observations(db_path: Path = SNAPSHOTS_DB) -> list[dict]:
    """One half-spread per snapshot, side and (expiry, moneyness) it serves.
    Only quotes with a bid above zero and an ask at or above it count."""
    conn = _ro(db_path)
    try:
        days = [r[0] for r in conn.execute("SELECT DISTINCT substr(taken_at, 1, 10) FROM snapshots ORDER BY 1")]
        out = []
        for day in days:
            rows = conn.execute(
                "SELECT taken_at, expiry, strike, option_type, spot, bid, ask FROM snapshots "
                "WHERE taken_at >= ? AND taken_at < ? ORDER BY taken_at",
                (f"{day}T00:00:00", f"{day}T99")).fetchall()
            chosen = classify_expiries(day, {r["expiry"] for r in rows})
            roles: dict[str, list[str]] = {}
            for choice, expiry in chosen.items():
                roles.setdefault(expiry, []).append(choice)
            chains: dict[tuple, dict] = {}
            for r in rows:
                if r["expiry"] not in roles or not r["spot"] or r["bid"] is None or r["ask"] is None:
                    continue
                if r["bid"] <= 0 or r["ask"] < r["bid"]:
                    continue
                chain = chains.setdefault((r["taken_at"], r["expiry"]), {"spot": r["spot"], "CE": {}, "PE": {}})
                if r["option_type"] in ("CE", "PE"):
                    chain[r["option_type"]][r["strike"]] = (r["bid"], r["ask"])
            for (taken_at, expiry), chain in chains.items():
                for kind in ("CE", "PE"):
                    for label, m in MONEYNESS.items():
                        target = chain["spot"] * (1 + m) if kind == "CE" else chain["spot"] * (1 - m)
                        strike = nearest_strike(chain[kind], target)
                        if strike is None:
                            continue
                        bid, ask = chain[kind][strike]
                        half = (ask - bid) / 2
                        for choice in roles[expiry]:
                            out.append({"day": day, "taken_at": taken_at, "expiry_choice": choice, "expiry": expiry,
                                        "moneyness": label, "kind": kind, "strike": strike, "spot": chain["spot"],
                                        "half_spread_pts": half, "half_spread_pct": 100 * half / ((ask + bid) / 2)})
        return out
    finally:
        conn.close()


def in_close_window(taken_at: str) -> bool:
    return CLOSE_WINDOW[0] <= taken_at[11:19] <= CLOSE_WINDOW[1]


def _median(obs: list[dict]) -> dict:
    if not obs:
        return {"half_spread_pts": None, "half_spread_pct": None, "n": 0}
    return {"half_spread_pts": round(statistics.median(o["half_spread_pts"] for o in obs), 3),
            "half_spread_pct": round(statistics.median(o["half_spread_pct"] for o in obs), 3),
            "n": len(obs)}


def measure_spreads(db_path: Path = SNAPSHOTS_DB) -> dict:
    """The median half-spread for every (expiry, moneyness) Phase 1 compares,
    calls and puts together: at the close (14:30-15:30, the primary measure)
    and over the whole session, with the snapshots behind each."""
    obs = observations(db_path)
    buckets = []
    for choice in EXPIRY_CHOICES:
        for label in MONEYNESS:
            mine = [o for o in obs if o["expiry_choice"] == choice and o["moneyness"] == label]
            close = _median([o for o in mine if in_close_window(o["taken_at"])])
            day = _median(mine)
            buckets.append({"expiry": choice, "moneyness": label, **close,
                            "all_day_half_spread_pts": day["half_spread_pts"],
                            "all_day_half_spread_pct": day["half_spread_pct"], "all_day_n": day["n"],
                            "sessions": sorted({o["day"] for o in mine})})
    return {"window": CLOSE_WINDOW_LABEL, "sessions": sorted({o["day"] for o in obs}),
            "spot": round(statistics.median(o["spot"] for o in obs), 2) if obs else None,
            "close_sessions": sorted({o["day"] for o in obs if in_close_window(o["taken_at"])}),
            "buckets": buckets}


def half_spreads(measured: dict, basis: str = "close") -> dict[tuple[str, str], float] | None:
    """{(expiry choice, moneyness): half-spread in points} on the close window
    ("close") or the whole session ("all_day"); None unless every bucket has one."""
    key = "half_spread_pts" if basis == "close" else "all_day_half_spread_pts"
    out = {(b["expiry"], b["moneyness"]): b[key] for b in measured["buckets"]}
    return out if all(v is not None for v in out.values()) else None


@dataclass
class SpreadCostModel(OptionsCostModel):
    """The rate card, with the spread charged as a measured half-spread in
    index points on each side instead of a percent of premium: half_spread_pts
    rupees a unit when buying (paying the ask) and again when selling (taking
    the bid). A sale that would cost more than it fetches still lapses."""
    premium_slippage_pct: float = 0.0
    half_spread_pts: float = 0.0

    def buy_cost_rs(self, premium: float, quantity: int, on) -> float:
        return super().buy_cost_rs(premium, quantity, on) + self.half_spread_pts * quantity

    def sell_cost_rs(self, premium: float, quantity: int, on) -> float:
        return min(super().sell_cost_rs(premium, quantity, on) + self.half_spread_pts * quantity, premium * quantity)

    def summary(self, on) -> str:
        return f"{super().summary(on)} and a measured half-spread of {self.half_spread_pts:g} points each way"
