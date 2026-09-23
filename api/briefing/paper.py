"""Phase 14 — paper observation.

Every evening: open a paper position for each pattern that formed on the
previous close, mark every open position to that day's premium, and close
the ones whose hold is up. Real NSE premiums, no money, no orders.

Two things make it evidence rather than decoration:

  * it only ever opens a position for the session that has just closed, so
    nothing is chosen knowing what came next (storage/paper_db.py refuses a
    stale signal date);
  * it runs a control — the same kind of option bought on a fixed weekly
    schedule with no signal at all — so the comparison the backtests use
    exists forward too. An option buyer makes money in a moving market
    whatever the signal; the control is what the patterns have to beat.
"""

import statistics
from datetime import date, datetime, timedelta, timezone

from backtest.options_engine import OptionsCostModel, select_contract
from backtest.pattern_options import LOT_SIZE, load_research
from backtest.pattern_proximity import pattern_proximity
from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from market_data.kite_session import IST
from storage import connect as options_connect
from storage import paper_db

COST_FRACTION = OptionsCostModel().round_trip_cost_fraction()

# Paper observation began the day the feature shipped. Nothing before this
# date may ever be opened: those signals' outcomes already exist.
FIRST_SIGNAL_DATE = "2026-09-22"
MIN_OPEN_INTEREST = 1000
CONTROL = {"hold_days": 5, "min_days_to_expiry": 7, "moneyness_pct": 0.0}


def _sessions() -> tuple[list[str], dict[str, float]]:
    df, _ = load_daily_data("^NSEI", 400)
    td = [str(d.date()) for d in df.index]
    return td, {d: float(c) for d, c in zip(td, df["close"])}


def _premium(conn, trade_date: str, expiry: str, strike: float, option_type: str) -> float | None:
    row = conn.execute(
        """SELECT close FROM option_bars WHERE trade_date = ? AND expiry_date = ?
           AND strike = ? AND option_type = ?""", (trade_date, expiry, strike, option_type)).fetchone()
    return float(row["close"]) if row and row["close"] else None


def _open_one(conn, spec: dict, signal_date: str, entry_date: str, planned_exit: str | None) -> bool:
    """Buys the setup's option at the entry session's close, as the research
    does. Skips silently when the archive has no usable contract — a paper
    trade priced off a guess would be worse than no paper trade."""
    spot = spec["spot"]
    offset = spot * spec["moneyness_pct"] / 100 * (1 if spec["option_type"] == "CE" else -1)
    picked = select_contract(entry_date, spot, spec["option_type"], offset, spec["min_days_to_expiry"],
                             planned_exit or entry_date, MIN_OPEN_INTEREST, conn)
    if picked is None:
        return False
    strike, expiry = picked
    premium = _premium(conn, entry_date, expiry, strike, spec["option_type"])
    if premium is None:
        return False
    return paper_db.open_position({
        "source": spec["source"], "strategy": spec["strategy"], "label": spec["label"],
        "signal_date": signal_date, "underlying": "NIFTY", "option_type": spec["option_type"],
        "strike": strike, "expiry": expiry, "entry_date": entry_date, "entry_premium": premium,
        "hold_days": spec["hold_days"], "planned_exit": planned_exit,
    })


def observe(now: datetime | None = None) -> dict:
    """One evening's work. Safe to re-run: every step is idempotent."""
    now = now or datetime.now(IST)
    td, closes = _sessions()
    if len(td) < 3:
        return {"opened": [], "marked": 0, "closed": [], "note": "not enough sessions"}

    entry_date, signal_date = td[-1], td[-2]
    opened, closed = [], []

    with options_connect() as conn:
        archived = conn.execute("SELECT MAX(trade_date) AS d FROM option_bars").fetchone()["d"]
        # The entry session's premiums have to exist before anything opens.
        can_open = archived is not None and archived >= entry_date and signal_date >= FIRST_SIGNAL_DATE

        if can_open:
            research = {p["strategy"]: p for p in (load_research() or {}).get("patterns", [])}
            prox = pattern_proximity("^NSEI")
            formed = [p for p in prox["patterns"] if p.get("formed_today")] if prox["as_of"] == signal_date else []
            for p in formed:
                r = research.get(p["strategy"]) or {}
                opt = r.get("suggested_option")
                if not opt or paper_db.has_signal_date(p["strategy"], signal_date, "pattern"):
                    continue
                planned = _exit_session(td, entry_date, opt["hold_days"])
                spec = {"source": "pattern", "strategy": p["strategy"], "label": p["label"],
                        "option_type": opt["type"], "moneyness_pct": opt["moneyness_pct"],
                        "min_days_to_expiry": opt["min_days_to_expiry"], "hold_days": opt["hold_days"],
                        "spot": closes[entry_date]}
                if _open_one(conn, spec, signal_date, entry_date, planned):
                    opened.append(f"{p['label']} ({opt['type']})")

            # The control: one call and one put a week, no signal involved.
            if not _control_this_week(td, entry_date):
                for kind in ("CE", "PE"):
                    name = f"control_{kind.lower()}"
                    if paper_db.has_signal_date(name, signal_date, "control"):
                        continue
                    planned = _exit_session(td, entry_date, CONTROL["hold_days"])
                    spec = {"source": "control", "strategy": name,
                            "label": f"No signal — weekly at-the-money {'call' if kind == 'CE' else 'put'}",
                            "option_type": kind, **CONTROL, "spot": closes[entry_date]}
                    if _open_one(conn, spec, signal_date, entry_date, planned):
                        opened.append(f"control {kind}")

        marked = 0
        for t in paper_db.open_trades():
            if not t["planned_exit"]:
                planned = _exit_session(td, t["entry_date"], t["hold_days"])
                if planned:
                    paper_db.set_planned_exit(t["id"], planned)
            latest = _last_priced_session(conn, t, td)
            if latest is None:
                continue
            day, premium = latest
            exit_idx = _exit_index(td, t["entry_date"], t["hold_days"])
            if exit_idx is not None and td.index(day) >= exit_idx:
                paper_db.close_position(t["id"], td[exit_idx], _premium_on(conn, t, td[exit_idx]) or premium)
                closed.append(t["label"])
            else:
                paper_db.mark(t["id"], day, premium)
                marked += 1

    return {"opened": opened, "marked": marked, "closed": closed,
            "entry_session": entry_date, "signal_session": signal_date,
            "note": None if can_open else "waiting for the entry session's option prices"}


def _exit_index(td: list[str], entry_date: str, hold: int) -> int | None:
    if entry_date not in td:
        return None
    i = td.index(entry_date) + hold
    return i if i < len(td) else None


def _exit_session(td: list[str], entry_date: str, hold: int) -> str | None:
    i = _exit_index(td, entry_date, hold)
    return td[i] if i is not None else None


def _control_this_week(td: list[str], entry_date: str) -> bool:
    """Has a control already been opened for the week this session falls in?"""
    week = date.fromisoformat(entry_date).isocalendar()[:2]
    for t in paper_db.all_trades():
        if t["source"] == "control" and date.fromisoformat(t["entry_date"]).isocalendar()[:2] == week:
            return True
    return False


def _premium_on(conn, t: dict, day: str) -> float | None:
    return _premium(conn, day, t["expiry"], t["strike"], t["option_type"])


def _last_priced_session(conn, t: dict, td: list[str]) -> tuple[str, float] | None:
    """The most recent session this contract has a price for, up to its
    planned exit — contracts stop trading, and a stale mark is a lie."""
    stop = _exit_index(td, t["entry_date"], t["hold_days"])
    horizon = td[: stop + 1] if stop is not None else td
    for day in reversed([d for d in horizon if d >= t["entry_date"]]):
        p = _premium_on(conn, t, day)
        if p is not None:
            return day, p
    return None


def _pnl(t: dict) -> dict | None:
    premium = t["exit_premium"] if t["status"] == "CLOSED" else t["mark_premium"]
    if premium is None or not t["entry_premium"]:
        return None
    gross = (premium - t["entry_premium"]) / t["entry_premium"] * 100
    net = gross - COST_FRACTION * 100
    return {"gross_pct": round(gross, 2), "net_pct": round(net, 2),
            "profit_per_lot_rs": round(t["entry_premium"] * net / 100 * LOT_SIZE),
            "realised": t["status"] == "CLOSED"}


def report() -> dict:
    trades = [{**t, "pnl": _pnl(t)} for t in paper_db.all_trades()]

    def side(source: str) -> dict:
        rows = [t for t in trades if t["source"] == source and t["status"] == "CLOSED" and t["pnl"]]
        nets = [t["pnl"]["net_pct"] for t in rows]
        rupees = [t["pnl"]["profit_per_lot_rs"] for t in rows]
        return {"closed": len(rows),
                "avg_net_pct": round(statistics.mean(nets), 2) if nets else None,
                "total_per_lot_rs": sum(rupees) if rupees else 0,
                "win_rate": round(sum(x > 0 for x in nets) / len(nets), 3) if nets else None,
                "open": sum(1 for t in trades if t["source"] == source and t["status"] == "OPEN")}

    first = min((t["signal_date"] for t in trades), default=None)
    return {
        "trades": trades,
        "summary": {
            "observing_since": first, "started": FIRST_SIGNAL_DATE,
            "patterns": side("pattern"), "control": side("control"),
            "sessions_needed_before_this_means_anything": 15,
        },
        "note": ("Hypothetical positions at real NSE closing premiums. Nothing is ordered and no money moves. "
                 f"Costs of {COST_FRACTION:.1%} of premium are charged on every position, open or closed. A "
                 "position is only ever opened for the session that has just closed, so none of this could be "
                 "chosen knowing the outcome. The control is the same kind of option bought weekly with no "
                 "signal: that is what a pattern has to beat, here as in the backtests."),
    }
