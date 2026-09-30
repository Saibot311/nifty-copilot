"""The journal's arithmetic and its comparison with the system (Phase 13).

"Followed" means the user's decision matched the system's verdict for that
session: took a trade in the direction it said, or stayed out on NO TRADE.
Anything else is an override — and whether overrides help or hurt is the
thing this exists to measure, once there are enough of them."""

import math
import sqlite3
import statistics
from datetime import date, datetime, time, timedelta
from pathlib import Path

from backtest.options_engine import LOT_SIZES, OptionsCostModel
from market_data.kite_session import IST
from storage import journal_db
from storage.forward_log_db import all_recommendations

# Each leg on its own premium and day, one order each, as in every backtest.
_COSTS = OptionsCostModel()

EXPIRY_TIME = time(15, 30)
# STT on an option held to expiry and exercised, as a fraction of its
# intrinsic value, paid by the buyer (NSE/FATAX/73524: 0.125% until
# 2026-03-31, 0.15% from 2026-04-01). The backtests never hold to expiry,
# so their cost model leaves it out; a journal trade can.
STT_ON_EXERCISE = (("2016-06-01", 0.00125), ("2026-04-01", 0.0015))
# Where each index's own option prices are archived, for a closing mark when
# Kite is not logged in.
_DATA = Path(__file__).parent.parent / "data"
ARCHIVES = {"NIFTY": "nifty_options.db", "BANKNIFTY": "options_banknifty.db",
            "MIDCPNIFTY": "options_midcpnifty.db", "SENSEX": "options_sensex.db"}
# The index close that settles an expiring contract: Kite's daily bar where it
# is mapped (NSE's own closes), else NSE's index report.
_KITE_INDEX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
_NSE_INDEX = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "MIDCPNIFTY": "Nifty Midcap Select"}
# The quote key for each index's level, asked in the same Kite call as the options.
SPOT_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
             "MIDCPNIFTY": "NSE:NIFTY MID SELECT", "SENSEX": "BSE:SENSEX"}


def system_action_for(trade_date: str) -> str | None:
    """The verdict the forward log recorded for that session, if any."""
    for r in all_recommendations():
        if r["as_of"] == trade_date:
            return r["action"]
    return None


def _rate(schedule: tuple, on) -> float:
    key = str(on)[:10]
    rates = [r for d, r in schedule if d <= key]
    return rates[-1] if rates else schedule[0][1]


def exercise_cost_rs(value: float, quantity: int, on) -> float:
    """What holding to expiry costs a buyer: STT on the intrinsic value, and
    nothing on a contract that expires worthless. No order, so no brokerage."""
    return max(value, 0.0) * quantity * _rate(STT_ON_EXERCISE, on)


def pnl(e: dict) -> dict | None:
    """Rupees on a closed, bought option, after the backtests' cost model."""
    if e["decision"] != "TOOK" or e.get("exit_premium") is None or not e.get("entry_premium") or not e.get("quantity"):
        return None
    gross = (e["exit_premium"] - e["entry_premium"]) * e["quantity"]
    exit_day = e.get("exit_date") or e["trade_date"]
    exit_cost = (exercise_cost_rs(e["exit_premium"], e["quantity"], exit_day) if e.get("exit_kind") == "settled"
                 else _COSTS.sell_cost_rs(e["exit_premium"], e["quantity"], exit_day))
    costs = _COSTS.buy_cost_rs(e["entry_premium"], e["quantity"], e["trade_date"]) + exit_cost
    return {"gross_rs": round(gross), "costs_rs": round(costs), "net_rs": round(gross - costs),
            "return_pct": round(100 * (gross - costs) / (e["entry_premium"] * e["quantity"]), 1)}


def _group_digits(n: int) -> str:
    """Indian grouping, as the page's own rupee figures: 1,23,456."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, parts = s[:-3], []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + parts + [s[-3:]])


def _rs(v: float) -> str:
    n = round(v)
    return f"{'+' if n > 0 else '−' if n < 0 else ''}₹{_group_digits(abs(n))}"


def expiry_moment(expiry: str) -> datetime:
    return datetime.combine(date.fromisoformat(expiry), EXPIRY_TIME, tzinfo=IST)


def intrinsic(option_type: str, strike: float, index: float) -> float:
    return max(index - strike, 0.0) if option_type == "CE" else max(strike - index, 0.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def black76(forward: float, strike: float, years: float, sigma: float, option_type: str) -> float:
    """A European option on the index, with discounting and carry left out:
    over the days to a weekly or monthly expiry they are a rounding error.
    Enough to read what a day of waiting costs, not to price the contract."""
    if years <= 0 or sigma <= 0:
        return intrinsic(option_type, strike, forward)
    sd = sigma * math.sqrt(years)
    d1 = (math.log(forward / strike) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    if option_type == "CE":
        return forward * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1)


def implied_vol(price: float, forward: float, strike: float, years: float, option_type: str) -> float | None:
    """The volatility at which black76 gives `price`, by bisection. None when
    the price is at or below intrinsic value: there is no time value to solve for."""
    if years <= 0 or price <= intrinsic(option_type, strike, forward) + 0.01:
        return None
    lo, hi = 0.01, 5.0
    if black76(forward, strike, years, hi, option_type) < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if black76(forward, strike, years, mid, option_type) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def position_now(e: dict, mark: float | None, spot: float | None, now: datetime,
                 mark_source: str | None = None, mark_at: str | None = None) -> dict:
    """An open trade as it stands: what it is worth, what a day of waiting
    costs if the index does not move, what expiry pays if it stays where it
    is, and where the user's own stop and target sit. Facts about the
    position, never a call to sell: the one prompt, "consider exiting", comes
    only from a stop or target the user set."""
    qty, strike, kind, paid = e["quantity"], float(e["strike"]), e["option_type"], e["entry_premium"]
    name = e.get("underlying") or "the index"
    expiry = expiry_moment(e["expiry"])
    buy = _COSTS.buy_cost_rs(paid, qty, e["trade_date"])
    out = {"mark": mark, "mark_source": mark_source, "mark_at": mark_at, "spot": spot,
           "days_to_expiry": (expiry.date() - now.date()).days, "expired": now >= expiry,
           "expires_today": expiry.date() == now.date() and now < expiry}
    if mark is not None:
        gross = (mark - paid) * qty
        net = gross - buy - _COSTS.sell_cost_rs(mark, qty, now.date().isoformat())
        out["pnl_now"] = {"gross_rs": round(gross), "net_rs": round(net), "return_pct": round(100 * net / (paid * qty), 1)}
    value = net_at_expiry = breakeven = None
    if spot is not None:
        value = intrinsic(kind, strike, spot)
        net_at_expiry = (value - paid) * qty - buy - exercise_cost_rs(value, qty, e["expiry"])
        per_unit = paid + buy / qty
        breakeven = strike + per_unit if kind == "CE" else strike - per_unit
        out["intrinsic"] = round(value, 2)
        out["if_unchanged_at_expiry"] = {"index": round(spot, 2), "value": round(value, 2),
                                         "net_rs": round(net_at_expiry)}
        out["breakeven_index"] = round(breakeven, 2)
        if mark is not None:
            out["time_value"] = round(max(mark - value, 0.0), 2)
    years = (expiry - now).total_seconds() / (365 * 86400)
    decay = None
    if mark is not None and spot is not None and years > 0:
        iv = implied_vol(mark, spot, strike, years, kind)
        if iv is not None:
            decay = (black76(spot, strike, years, iv, kind)
                     - black76(spot, strike, max(years - 1 / 365, 0.0), iv, kind)) * qty
            out["implied_vol_pct"] = round(iv * 100, 1)
            out["decay_per_day_rs"] = round(decay)
    stop, target = e.get("stop_premium"), e.get("target_premium")
    state = None
    if mark is not None:
        if stop is not None and mark <= stop:
            state = "stop"
        elif target is not None and mark >= target:
            state = "target"
    out["plan"] = {"stop": stop, "target": target, "state": state}

    # The page shows these words as written here (I2): conditional facts,
    # no forecast, and "consider" only against the user's own plan.
    lines = []
    if state == "stop":
        lines.append(f"Consider exiting: the price (₹{mark:g}) is at or below the stop you set (₹{stop:g}).")
    elif state == "target":
        lines.append(f"Consider exiting: the price (₹{mark:g}) is at or above the target you set (₹{target:g}).")
    if out["expired"]:
        lines.append(f"It expired on {e['expiry']} and settles at its value at {name}'s close that day.")
    else:
        if out["expires_today"] and "time_value" in out:
            lines.append(f"It expires today at 15:30: the ₹{out['time_value']:g} a unit of time value left "
                         "goes to nothing by then.")
        elif decay is not None:
            lines.append(f"If {name} doesn't move, time decay takes about {_rs(decay).lstrip('+')} off it by tomorrow.")
        if value is not None:
            lines.append(f"Held to expiry with {name} where it is ({spot:,.2f}), it settles at ₹{value:g} a unit: "
                         f"{_rs(net_at_expiry)} after costs.")
            lines.append(f"To cover the premium and the costs, {name} has to close {'above' if kind == 'CE' else 'below'} "
                         f"{breakeven:,.2f} on expiry day.")
    out["lines"] = lines
    return out


def _read_only(db: Path):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def archive_mark(e: dict) -> tuple[float | None, str | None]:
    """The contract's last closing price in the local archive, and its date."""
    db = _DATA / ARCHIVES.get(e.get("underlying") or "", "missing.db")
    if not db.is_file():
        return None, None
    conn = _read_only(db)
    try:
        row = conn.execute("SELECT trade_date, close FROM option_bars WHERE expiry_date = ? AND strike = ? "
                           "AND option_type = ? AND close IS NOT NULL AND close > 0 "
                           "ORDER BY trade_date DESC LIMIT 1",
                           (e["expiry"], float(e["strike"]), e["option_type"])).fetchone()
    finally:
        conn.close()
    return (float(row[1]), row[0]) if row else (None, None)


_CLOSES: dict[tuple[str, str], float] = {}


def index_close(underlying: str, on: str) -> float | None:
    """The index's official close on `on`: Kite's daily bar where the index
    is mapped (NSE's own figure), else NSE's index report. None if neither has
    it. A finished session's close never changes, so it is kept once found."""
    if (underlying, on) in _CLOSES:
        return _CLOSES[(underlying, on)]
    close = _index_close(underlying, on)
    if close is not None and on < date.today().isoformat():
        _CLOSES[(underlying, on)] = close
    return close


def _index_close(underlying: str, on: str) -> float | None:
    symbol = _KITE_INDEX.get(underlying)
    if symbol:
        try:
            from market_data.zerodha_provider import ZerodhaProvider
            day = date.fromisoformat(on)
            bars = [c for c in ZerodhaProvider().get_ohlc(symbol, "1d", day, day)
                    if c.timestamp[:10] == on and not c.provisional]
            if bars:
                return float(bars[-1].close)
        except Exception:
            pass
    name, db = _NSE_INDEX.get(underlying), _DATA / "nse_indices.db"
    if not name or not db.is_file():
        return None
    conn = _read_only(db)
    try:
        row = conn.execute("SELECT close FROM index_daily WHERE index_name = ? AND trade_date = ?", (name, on)).fetchone()
    finally:
        conn.close()
    return float(row[0]) if row else None


def archive_forward(e: dict, on: str) -> float | None:
    """The index level implied by that session's closing option prices for
    the same expiry (put-call parity at the strike where call and put are
    nearest in price): strike + call − put. From the same file as the
    contract's own close, so the two are never from different moments, and it
    needs no network. Used when the index's own close is not in hand."""
    db = _DATA / ARCHIVES.get(e.get("underlying") or "", "missing.db")
    if not db.is_file():
        return None
    conn = _read_only(db)
    try:
        rows = conn.execute(
            "SELECT c.strike, c.close, p.close FROM option_bars c JOIN option_bars p "
            "ON p.trade_date = c.trade_date AND p.expiry_date = c.expiry_date AND p.strike = c.strike "
            "AND p.option_type = 'PE' WHERE c.option_type = 'CE' AND c.trade_date = ? AND c.expiry_date = ? "
            "AND c.close > 0 AND p.close > 0 AND c.contracts > 0 AND p.contracts > 0",
            (on, e["expiry"])).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    strike, call, put = min(rows, key=lambda r: abs(r[1] - r[2]))
    return round(strike + call - put, 2)


def settlement(e: dict, now: datetime) -> float:
    """What an expired contract settles at: its intrinsic value at the index's
    close on expiry day (NSE Clearing's final settlement price). Computed,
    never typed."""
    if now < expiry_moment(e["expiry"]):
        raise ValueError(f"It has not expired yet: it expires on {e['expiry']} at 15:30.")
    close = index_close(e["underlying"], e["expiry"])
    if close is None:
        raise LookupError(f"{e['underlying']}'s close on {e['expiry']} isn't available here yet. "
                          "Try again after the evening job, or close it by hand at the settlement value.")
    return round(intrinsic(e["option_type"], float(e["strike"]), close), 2)


def open_trades() -> list[dict]:
    return [e for e in journal_db.all_entries() if e["decision"] == "TOOK" and e.get("exit_premium") is None]


def positions(live: dict | None = None, now: datetime | None = None) -> dict[str, dict]:
    """Every open trade priced now. `live` is Kite's answer ({"marks": {entry
    id: premium}, "spots": {index: level}, "source", "at"}); a trade Kite did
    not price falls back to its last archived close, with the index at that
    same session's close, so the two are never from different moments."""
    now = now or datetime.now(IST)
    out = {}
    for e in open_trades():
        mark = (live or {}).get("marks", {}).get(e["id"])
        spot = (live or {}).get("spots", {}).get(e["underlying"])
        if mark is not None and spot is not None:
            out[str(e["id"])] = position_now(e, mark, spot, now, live.get("source"), live.get("at"))
            continue
        mark, day = archive_mark(e)
        spot = (index_close(e["underlying"], day) or archive_forward(e, day)) if day else None
        out[str(e["id"])] = position_now(e, mark, spot, now, f"close of {day}" if day else None, day)
    return out


def followed(e: dict) -> bool | None:
    sys_action = e.get("system_action")
    if not sys_action:
        return None
    if sys_action == "NO_TRADE":
        return e["decision"] != "TOOK"
    wanted = "CE" if sys_action == "CONSIDER_CALL" else "PE"
    return e["decision"] == "TOOK" and e.get("option_type") == wanted


def report(live: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    open_now = positions(live, now)
    entries = []
    for e in journal_db.all_entries():
        # A decision logged during the session has no verdict yet — the
        # forward log writes it that evening. Look it up on every read so the
        # comparison appears once it exists, rather than staying blank for a
        # row that was simply logged early. Still never typed by the user.
        if not e.get("system_action"):
            e = {**e, "system_action": system_action_for(e["trade_date"])}
        row = {**e, "pnl": pnl(e), "followed_system": followed(e)}
        if e["decision"] == "TOOK" and e.get("quantity"):
            lot = LOT_SIZES.get(e.get("underlying") or "")
            row["lot_size"] = lot
            row["lots"] = round(e["quantity"] / lot, 2) if lot else None
        if str(e["id"]) in open_now:
            row["position"] = open_now[str(e["id"])]
            row["can_settle"] = now >= expiry_moment(e["expiry"])
        entries.append(row)
    closed = [e for e in entries if e["pnl"]]
    net = [e["pnl"]["net_rs"] for e in closed]

    def group(flag):
        # Every decision counts, not only the trades: staying out on a
        # "no trade" day is following the system, and it made exactly ₹0.
        g = [e["pnl"]["net_rs"] for e in closed if e["followed_system"] is flag]
        return {"decisions": sum(1 for e in entries if e["followed_system"] is flag),
                "trades": len(g), "net_rs": sum(g), "avg_rs": round(statistics.mean(g)) if g else None}

    return {
        "entries": entries,
        "lot_sizes": LOT_SIZES,
        "summary": {
            "entries": len(entries),
            "by_decision": {d: sum(1 for e in entries if e["decision"] == d) for d in journal_db.DECISIONS},
            "open_trades": sum(1 for e in entries if e["decision"] == "TOOK" and e["pnl"] is None),
            "closed_trades": len(closed),
            "net_rs": sum(net),
            "win_rate": round(sum(1 for x in net if x > 0) / len(net), 3) if net else None,
            "followed_system": group(True),
            "overrode_system": group(False),
            "decisions_matching_system": sum(1 for e in entries if e["followed_system"]),
            "decisions_with_a_system_verdict": sum(1 for e in entries if e["followed_system"] is not None),
        },
        "note": ("Your own trades, as you entered them. Net is after the same cost model as every backtest "
                 f"({_COSTS.summary(date.today())}; each leg at the rates of its own day). Followed means your decision matched the system's "
                 "verdict for that session. With few trades, these totals are a record, not evidence."),
    }
