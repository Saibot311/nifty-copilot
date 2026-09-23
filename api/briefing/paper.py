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

Three policies run side by side, each on its own row, each measured
separately:

    pattern     a pattern formed -> its own tested setup
    best_read   nothing formed -> one 2% out-of-the-money option, in one
                direction only, taken from whichever signal has the most
                evidence behind it that day — the highest holdout t, even
                though every one of them was rejected. When no rejected
                signal fires, or none of those firing has positive evidence,
                it falls back to the 20-session trend and says so. The
                system has no proven edge here and never presents this as a
                recommendation; it exists to measure what "take something
                every day" actually costs.
    control     one call and one put a week, no signal at all

Positions are sized against money the user allocates to the paper book
(storage.paper_db.add_funds). Nothing is sized against money that was never
allocated, and a position that does not fit the remaining cash is skipped
rather than shrunk to a fraction of a lot.
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
# The daily trade is out of the money by the research grid's own step, and
# one-sided: a call or a put, never both.
OTM_PCT = 2.0
BEST_READ = {"hold_days": 5, "min_days_to_expiry": 7, "moneyness_pct": OTM_PCT}

# At most this share of the allocated funds goes into any one position, so a
# single expensive premium cannot swallow the book.
MAX_PER_TRADE = 0.2


def _costs(premium: float, lots: int) -> float:
    """The whole round trip, charged on the entry premium — exactly the
    convention the backtests use, so a paper result can be put beside a
    researched one without an asterisk."""
    return premium * lots * LOT_SIZE * COST_FRACTION


def _lots_for(premium: float, cash: float, allocated_rs: float) -> int:
    """Whole lots only, inside both the cash on hand and the per-trade cap."""
    per_lot = premium * LOT_SIZE * (1 + COST_FRACTION)
    budget = min(cash, allocated_rs * MAX_PER_TRADE) if allocated_rs else cash
    return int(budget // per_lot) if per_lot > 0 else 0


def _sessions() -> tuple[list[str], dict[str, float]]:
    """Final sessions only. Today's bar is still forming while the market is
    open, and a signal read off a half-finished candle is not a signal."""
    df, _ = load_daily_data("^NSEI", 400)
    if "provisional" in df.columns:
        df = df[~df["provisional"].astype(bool)]
    td = [str(d.date()) for d in df.index]
    return td, {d: float(c) for d, c in zip(td, df["close"])}


def _premium(conn, trade_date: str, expiry: str, strike: float, option_type: str) -> float | None:
    row = conn.execute(
        """SELECT close FROM option_bars WHERE trade_date = ? AND expiry_date = ?
           AND strike = ? AND option_type = ?""", (trade_date, expiry, strike, option_type)).fetchone()
    return float(row["close"]) if row and row["close"] else None


def _strike_offset(spot: float, moneyness_pct: float, option_type: str) -> float:
    """Direction-aware: a positive percentage is out of the money, which is
    above spot for a call and below it for a put."""
    return spot * moneyness_pct / 100 * (1 if option_type == "CE" else -1)


def cash_and_equity(marks: dict[int, float] | None = None) -> dict:
    """What the paper book is worth: allocated money, minus what open
    positions cost, plus what they are marked at now."""
    allocated_rs = paper_db.allocated()
    trades = paper_db.all_trades()
    spent = sum((t["entry_premium"] * (t.get("lots") or 1) * LOT_SIZE
                 + (t.get("entry_cost_rs") or _costs(t["entry_premium"], t.get("lots") or 1)))
                for t in trades if t["status"] == "OPEN")
    realised = 0.0
    for t in trades:
        if t["status"] == "CLOSED" and t["exit_premium"] is not None:
            gross = (t["exit_premium"] - t["entry_premium"]) * (t.get("lots") or 1) * LOT_SIZE
            realised += gross - (t.get("entry_cost_rs") or 0) - (t.get("exit_cost_rs") or 0)
    open_value = 0.0
    for t in trades:
        if t["status"] != "OPEN":
            continue
        mark = (marks or {}).get(t["id"], t["mark_premium"] if t["mark_premium"] is not None else t["entry_premium"])
        open_value += mark * (t.get("lots") or 1) * LOT_SIZE
    cash = allocated_rs + realised - spent
    return {"allocated_rs": round(allocated_rs), "cash_rs": round(cash),
            "open_positions_value_rs": round(open_value), "equity_rs": round(cash + open_value),
            "realised_rs": round(realised),
            "return_pct": round((cash + open_value - allocated_rs) / allocated_rs * 100, 2) if allocated_rs else None,
            "max_per_trade_rs": round(allocated_rs * MAX_PER_TRADE) if allocated_rs else 0}


def _open_one(conn, spec: dict, signal_date: str, entry_date: str, planned_exit: str | None) -> bool:
    """Buys the setup's option at the entry session's close, as the research
    does. Skips silently when the archive has no usable contract — a paper
    trade priced off a guess would be worse than no paper trade."""
    spot = spec["spot"]
    offset = _strike_offset(spot, spec["moneyness_pct"], spec["option_type"])
    picked = select_contract(entry_date, spot, spec["option_type"], offset, spec["min_days_to_expiry"],
                             planned_exit or entry_date, MIN_OPEN_INTEREST, conn)
    if picked is None:
        return False
    strike, expiry = picked
    premium = _premium(conn, entry_date, expiry, strike, spec["option_type"])
    if premium is None:
        return False
    book = cash_and_equity()
    lots = _lots_for(premium, book["cash_rs"], book["allocated_rs"])
    if lots < 1:
        return False  # no allocated funds, or this premium does not fit
    return paper_db.open_position({
        "source": spec["source"], "strategy": spec["strategy"], "label": spec["label"],
        "signal_date": signal_date, "underlying": "NIFTY", "option_type": spec["option_type"],
        "strike": strike, "expiry": expiry, "entry_date": entry_date, "entry_premium": premium,
        "hold_days": spec["hold_days"], "planned_exit": planned_exit,
        "lots": lots, "entry_cost_rs": round(_costs(premium, lots), 2),
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

            # Nothing formed: take one 2% out-of-the-money option anyway, in
            # a single direction, from the best-evidenced signal firing that
            # day. No proven edge — the row says so — and the point is to
            # measure what taking something every day actually costs.
            if not formed and not paper_db.has_signal_date("best_read", signal_date, "best_read"):
                read = _confident_read(signal_date, closes, td)
                if read:
                    kind = read["direction"]
                    planned = _exit_session(td, entry_date, BEST_READ["hold_days"])
                    spec = {"source": "best_read", "strategy": "best_read",
                            "label": f"Most confident signal — {read['why']}", "option_type": kind,
                            **BEST_READ, "spot": closes[entry_date]}
                    if _open_one(conn, spec, signal_date, entry_date, planned):
                        opened.append(f"best read {kind} 2% OTM ({read['why']})")

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
                exit_premium = _premium_on(conn, t, td[exit_idx]) or premium
                # Costs were charged in full at entry, as in the backtests.
                paper_db.close_position(t["id"], td[exit_idx], exit_premium, exit_cost_rs=0.0)
                closed.append(t["label"])
            else:
                paper_db.mark(t["id"], day, premium)
                marked += 1

    return {"opened": opened, "marked": marked, "closed": closed,
            "entry_session": entry_date, "signal_session": signal_date,
            "note": None if can_open else "waiting for the entry session's option prices"}


def _trend_read(signal_date: str, closes: dict[str, float], td: list[str]) -> tuple[str, str] | None:
    """The fallback when no rejected signal fires: above the 20-session
    close, a call; below it, a put."""
    if signal_date not in td:
        return None
    i = td.index(signal_date)
    if i < 20:
        return None
    now, then = closes[td[i]], closes[td[i - 20]]
    if now == then:
        return None
    return ("CE", "20-session trend up") if now > then else ("PE", "20-session trend down")


def _confidence_by_name() -> dict[str, float]:
    """Each rejected hypothesis's holdout t — how far its 2024-26 result
    stood out from buying the same option with no signal. Every one of these
    is below its bar; this ranks them anyway, which is the point."""
    from backtest.structural_research import load_structural_research
    r = load_structural_research() or {}
    return {h["name"]: h["holdout"].get("t") for h in r.get("hypotheses", [])
            if h["holdout"].get("t") is not None}


def _confident_read(signal_date: str, closes: dict[str, float], td: list[str]) -> dict | None:
    """One direction, from the best-evidenced signal firing that day.

    Candidates are the structural hypotheses that fired — each rejected, but
    each with a measured t against the no-signal baseline. The highest
    positive t wins. A negative t is evidence the signal did *worse* than
    doing nothing, so those are not followed; if nothing positive fires, the
    trend fallback is used and the row says which it was."""
    from backtest.structural_research import signals_on

    try:
        fired = signals_on(signal_date)
    except Exception:
        fired = {}
    confidence = _confidence_by_name()
    ranked = sorted(
        ({"source": name, "direction": kind, "confidence": confidence[name]}
         for name, kind in fired.items() if name in confidence),
        key=lambda c: c["confidence"], reverse=True)
    best = next((c for c in ranked if c["confidence"] > 0), None)
    if best:
        pretty = best["source"].replace("_", " ")
        return {**best, "why": f"{pretty}, the strongest signal firing (t {best['confidence']}, still rejected)"}

    trend = _trend_read(signal_date, closes, td)
    if trend is None:
        return None
    kind, why = trend
    reason = "no rejected signal fired" if not ranked else "every signal firing did worse than no signal"
    return {"direction": kind, "confidence": None, "source": "trend",
            "why": f"{why} — {reason}"}


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


def _pnl(t: dict, mark: float | None = None) -> dict | None:
    """Rupees on the lots actually held, after both legs of the cost model.
    `mark` is a live price when one is available; otherwise the last close."""
    premium = mark if mark is not None else (t["exit_premium"] if t["status"] == "CLOSED" else t["mark_premium"])
    if premium is None or not t["entry_premium"]:
        return None
    lots = t.get("lots") or 1
    gross_rs = (premium - t["entry_premium"]) * lots * LOT_SIZE
    # Costs are always applied (I3). A row that never recorded one gets it
    # computed rather than waived — a free trade is not a thing.
    costs = (t["entry_cost_rs"] if t.get("entry_cost_rs") else _costs(t["entry_premium"], lots)) \
        + (t.get("exit_cost_rs") or 0)
    net_rs = gross_rs - costs
    invested = t["entry_premium"] * lots * LOT_SIZE
    return {"gross_pct": round((premium - t["entry_premium"]) / t["entry_premium"] * 100, 2),
            "net_pct": round(net_rs / invested * 100, 2) if invested else None,
            "profit_rs": round(net_rs), "invested_rs": round(invested), "lots": lots,
            "profit_per_lot_rs": round(net_rs / lots),
            "realised": t["status"] == "CLOSED", "live": mark is not None}


def live_marks() -> dict:
    """Open positions priced now, not at last night's close, when a Kite
    session exists. Falls back to the closing mark, and says which it is."""
    from market_data.kite_quotes import last_prices, option_tokens

    trades = paper_db.open_trades()
    contracts = [{"id": t["id"], "underlying": t["underlying"], "expiry": t["expiry"],
                  "strike": t["strike"], "option_type": t["option_type"]} for t in trades]
    tokens = option_tokens(contracts)
    quotes = last_prices(list(tokens.values()))
    marks = {tid: quotes["by_token"].get(token) for tid, token in tokens.items()}
    marks = {tid: p for tid, p in marks.items() if p is not None}
    priced = {t["id"]: marks.get(t["id"]) for t in trades}
    book = cash_and_equity(marks)
    return {
        "index": quotes.get("index"), "source": quotes.get("source"),
        "marks": {str(tid): p for tid, p in marks.items()},
        "paper": {**book, "open_positions": len(trades),
                  "live_priced": sum(1 for v in priced.values() if v is not None),
                  "unrealised_rs": round(sum((_pnl(t, marks.get(t["id"])) or {}).get("profit_rs", 0) for t in trades))},
    }


def report(marks: dict[int, float] | None = None) -> dict:
    trades = [{**t, "pnl": _pnl(t, (marks or {}).get(t["id"]))} for t in paper_db.all_trades()]

    def side(source: str) -> dict:
        rows = [t for t in trades if t["source"] == source and t["status"] == "CLOSED" and t["pnl"]]
        nets = [t["pnl"]["net_pct"] for t in rows]
        rupees = [t["pnl"]["profit_rs"] for t in rows]
        return {"closed": len(rows),
                "avg_net_pct": round(statistics.mean(nets), 2) if nets else None,
                "total_rs": sum(rupees) if rupees else 0,
                "total_per_lot_rs": sum(t["pnl"]["profit_per_lot_rs"] for t in rows) if rows else 0,
                "win_rate": round(sum(x > 0 for x in nets) / len(nets), 3) if nets else None,
                "open": sum(1 for t in trades if t["source"] == source and t["status"] == "OPEN")}

    first = min((t["signal_date"] for t in trades), default=None)
    return {
        "trades": trades,
        "account": {**cash_and_equity(marks), "flows": paper_db.fund_flows(),
                    "max_per_trade_share": MAX_PER_TRADE},
        "summary": {
            "observing_since": first, "started": FIRST_SIGNAL_DATE,
            "patterns": side("pattern"), "best_read": side("best_read"), "control": side("control"),
            "sessions_needed_before_this_means_anything": 15,
        },
        "note": ("Hypothetical positions at real NSE closing premiums. Nothing is ordered and no money moves. "
                 f"Costs of {COST_FRACTION:.1%} of premium are charged on every position, open or closed. A "
                 "position is only ever opened for the session that has just closed, so none of this could be "
                 "chosen knowing the outcome. The control is the same kind of option bought weekly with no "
                 "signal: that is what a pattern has to beat, here as in the backtests."),
    }
