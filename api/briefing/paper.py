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

The book takes **one position a session**, in one direction. When several
patterns form, the one with the most evidence behind it takes the slot and
the rest are reported as passed over; when none forms, the best read takes
it. Never two, and never a call and a put at once — including across
sessions: while a call is held, a put is skipped (and said so), and the
reverse.

Three policies run side by side, each on its own row, each measured
separately:

    pattern     a pattern formed -> its own tested setup
    best_read   nothing formed -> one 2% in-the-money option, in one
                direction only, taken from whichever signal has the most
                evidence behind it that day — the highest holdout t, even
                though every one of them was rejected. When no rejected
                signal fires, or none of those firing has positive evidence,
                it falls back to the 20-session trend and says so. The
                system has no proven edge here and never presents this as a
                recommendation; it exists to measure what "take something
                every day" actually costs.
    control     one call and one put a week, no signal at all — and NOT a
                position in the book. It is the yardstick the other two are
                measured against, so it is priced on the same real premiums
                but spends no allocated cash, moves no equity, and can never
                take the session's one slot. Removing it would leave nothing
                to say "the signal beat doing nothing" against.

Positions are sized against money the user allocates to the paper book
(storage.paper_db.add_funds). Nothing is sized against money that was never
allocated, and a position that does not fit the remaining cash is skipped
rather than shrunk to a fraction of a lot.
"""

import statistics
from datetime import date, datetime, timedelta, timezone

from backtest.options_engine import OptionsCostModel, select_contract
from backtest.pattern_options import LOT_SIZE, load_research
from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from quant.regime import classify_regime_series
from market_data.kite_session import IST
from storage import connect as options_connect
from storage import paper_db

_COSTS = OptionsCostModel()
# A flat round trip (~3.3%): the reserve a position is sized with, and what
# rows opened before 2026-09-24 were charged at entry.
COST_FRACTION = _COSTS.round_trip_cost_fraction()
# From 2026-09-24 each leg is charged on its own premium, as in the backtests:
# the buy on what was paid, the sale on what it sold for.
BUY_FRACTION, SELL_FRACTION = _COSTS.buy_fraction(), _COSTS.sell_fraction()
SPLIT = "split"

# Paper observation began the day the feature shipped. Nothing before this
# date may ever be opened: those signals' outcomes already exist.
FIRST_SIGNAL_DATE = "2026-09-22"
MIN_OPEN_INTEREST = 1000
# The control is a yardstick, not a position to win on: one lot a side, and
# unfunded, so it cannot take the session's one slot or spend the book's
# money. Both sides are right for a benchmark — it measures what buying an
# option blind costs, with the direction taken out — and wrong for the book,
# which is why it sits outside it.
CONTROL = {"hold_days": 5, "min_days_to_expiry": 7, "moneyness_pct": 0.0, "max_lots": 1, "funded": False}
# The daily trade is in the money by the research grid's own step, and
# one-sided: a call or a put, never both. Negative is in the money, as in
# pattern_options — above spot for a put, below it for a call.
ITM_PCT = -2.0
BEST_READ = {"hold_days": 5, "min_days_to_expiry": 7, "moneyness_pct": ITM_PCT}

# At most this share of the book goes into any one position, so a single
# premium cannot swallow it. An in-the-money option carries real intrinsic
# value — around Rs 28,000 a lot at current levels against Rs 1,000 for a far
# out-of-the-money one — so the cap has to leave room for one whole lot or the
# daily trade never opens at all.
#
# The share is of the book's *current* value, not of what was first
# allocated: a winning run sizes up and a losing one sizes down, which is the
# only honest way a paper book can be said to compound.
MAX_PER_TRADE = 0.4


def _costs(premium: float, lots: int) -> float:
    """The old convention — the whole round trip on the entry premium. Kept
    for the rows opened under it, which are never rewritten."""
    return premium * lots * LOT_SIZE * COST_FRACTION


def _entry_costs(premium: float, lots: int) -> float:
    return premium * lots * LOT_SIZE * BUY_FRACTION


def _exit_costs(premium: float, lots: int) -> float:
    return premium * lots * LOT_SIZE * SELL_FRACTION


def _lots_for(premium: float, cash: float, book_rs: float) -> int:
    """Whole lots only, inside both the cash on hand and the per-trade cap.
    `book_rs` is the book's value now — profits raise it, losses lower it."""
    per_lot = premium * LOT_SIZE * (1 + COST_FRACTION)
    budget = min(cash, book_rs * MAX_PER_TRADE) if book_rs > 0 else 0
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


def _why_not(conn, spec: dict, entry_date: str, planned_exit: str | None) -> str | None:
    """Why a position did not open. A silent skip looks identical to a quiet
    market, and the usual cause — one lot costing more than the per-trade cap
    — is worth saying out loud."""
    spot = spec["spot"]
    picked = select_contract(entry_date, spot, spec["option_type"],
                             _strike_offset(spot, spec["moneyness_pct"], spec["option_type"]),
                             spec["min_days_to_expiry"], planned_exit or entry_date, MIN_OPEN_INTEREST, conn)
    if picked is None:
        return f"{spec['strategy']}: no contract in the archive for that strike and expiry"
    premium = _premium(conn, entry_date, picked[1], picked[0], spec["option_type"])
    if premium is None:
        return f"{spec['strategy']}: that contract has no closing price"
    book = cash_and_equity()
    lot = premium * LOT_SIZE * (1 + COST_FRACTION)
    if not book["allocated_rs"]:
        return f"{spec['strategy']}: no paper funds allocated"
    return (f"{spec['strategy']}: one lot costs ₹{lot:,.0f} — more than the ₹{book['max_per_trade_rs']:,} "
            f"per-trade cap ({int(MAX_PER_TRADE * 100)}% of the ₹{book['equity_rs']:,} book) "
            f"or the ₹{book['cash_rs']:,} cash")


def _strike_offset(spot: float, moneyness_pct: float, option_type: str) -> float:
    """Direction-aware: a positive percentage is out of the money, which is
    above spot for a call and below it for a put."""
    return spot * moneyness_pct / 100 * (1 if option_type == "CE" else -1)


def cash_and_equity(marks: dict[int, float] | None = None) -> dict:
    """What the paper book is worth: allocated money, minus what open
    positions cost, plus what they are marked at now."""
    allocated_rs = paper_db.allocated()
    # The yardstick is priced, not held: it never spends the book's cash and
    # never moves its equity.
    trades = [t for t in paper_db.all_trades() if t.get("funded", 1)]
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
        value = mark * (t.get("lots") or 1) * LOT_SIZE
        # What it would fetch if sold now: the sale's costs are not paid yet.
        open_value += value * (1 - SELL_FRACTION) if t.get("cost_model") == SPLIT else value
    cash = allocated_rs + realised - spent
    return {"allocated_rs": round(allocated_rs), "cash_rs": round(cash),
            "open_positions_value_rs": round(open_value), "equity_rs": round(cash + open_value),
            "realised_rs": round(realised),
            "return_pct": round((cash + open_value - allocated_rs) / allocated_rs * 100, 2) if allocated_rs else None,
            "max_per_trade_rs": round(max(cash + open_value, 0) * MAX_PER_TRADE)}


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
    funded = spec.get("funded", True)
    if funded:
        book = cash_and_equity()
        lots = _lots_for(premium, book["cash_rs"], book["equity_rs"])
    else:
        # A yardstick is a fixed size by definition: sizing it off a book it
        # is not in would make it measure the book instead of the market.
        lots = spec.get("max_lots") or 1
    if spec.get("max_lots"):
        lots = min(lots, spec["max_lots"])
    if lots < 1:
        return False  # no allocated funds, or this premium does not fit
    return paper_db.open_position({
        "funded": 1 if funded else 0,
        "source": spec["source"], "strategy": spec["strategy"], "label": spec["label"],
        "signal_date": signal_date, "underlying": "NIFTY", "option_type": spec["option_type"],
        "strike": strike, "expiry": expiry, "entry_date": entry_date, "entry_premium": premium,
        "hold_days": spec["hold_days"], "planned_exit": planned_exit,
        "lots": lots, "entry_cost_rs": round(_entry_costs(premium, lots), 2), "cost_model": SPLIT,
    })


def observe(now: datetime | None = None) -> dict:
    """One evening's work. Safe to re-run: every step is idempotent."""
    now = now or datetime.now(IST)
    td, closes = _sessions()
    if len(td) < 3:
        return {"opened": [], "marked": 0, "closed": [], "note": "not enough sessions"}

    entry_date, signal_date = td[-1], td[-2]
    # `opened` is the book: at most one a session. `benchmark` is the
    # yardstick, reported apart from it — counting the two together is what
    # made a single session look like two trades.
    opened, closed, skipped, passed_over, benchmark = [], [], [], [], []

    with options_connect() as conn:
        archived = conn.execute("SELECT MAX(trade_date) AS d FROM option_bars").fetchone()["d"]
        # The entry session's premiums have to exist before anything opens.
        can_open = archived is not None and archived >= entry_date and signal_date >= FIRST_SIGNAL_DATE

        if can_open:
            # ONE position a session, in one direction. The gate is the book
            # itself: if this session already holds something, nothing else
            # opens, however good it looks. Re-running the evening's job
            # therefore cannot add a second position either.
            if paper_db.funded_on(entry_date) == 0:
                held = _held_sides(td, entry_date)
                research = {p["strategy"]: p for p in (load_research() or {}).get("patterns", [])}
                formed = _formed_on(signal_date)
                # Strongest evidence first, on the same measure the best read
                # ranks by — the holdout t against buying with no signal. A
                # pattern with no measured t sorts last rather than winning
                # by being unmeasured.
                formed.sort(key=lambda q: (
                    (research.get(q["strategy"]) or {}).get("holdout_t_stat") is None,
                    -((research.get(q["strategy"]) or {}).get("holdout_t_stat") or 0.0)))

                chosen = None
                for p in formed:
                    r = research.get(p["strategy"]) or {}
                    opt = r.get("suggested_option")
                    if not opt or paper_db.has_signal_date(p["strategy"], signal_date, "pattern"):
                        continue
                    against = _against(held, opt["type"])
                    if against:
                        skipped.append(f"{p['label']}: {against}")
                        continue
                    planned = _exit_session(td, entry_date, opt["hold_days"])
                    spec = {"source": "pattern", "strategy": p["strategy"], "label": p["label"],
                            "option_type": opt["type"], "moneyness_pct": opt["moneyness_pct"],
                            "min_days_to_expiry": opt["min_days_to_expiry"], "hold_days": opt["hold_days"],
                            "spot": closes[entry_date]}
                    if _open_one(conn, spec, signal_date, entry_date, planned):
                        chosen = p
                        opened.append(f"{p['label']} ({opt['type']})")
                        break
                    skipped.append(_why_not(conn, spec, entry_date, planned))

                # The ones that also formed and did not get the slot. Said
                # out loud: a pattern silently dropped looks the same as a
                # pattern that never formed.
                if chosen is not None:
                    passed_over = [q["label"] for q in formed if q is not chosen]

                # Nothing formed: take one 2% in-the-money option anyway, in
                # a single direction, from the best-evidenced signal firing
                # that day. No proven edge — the row says so — and the point
                # is to measure what taking something every day actually
                # costs.
                if chosen is None and not formed and not paper_db.has_signal_date("best_read", signal_date, "best_read"):
                    read = _confident_read(signal_date, closes, td)
                    against = _against(held, read["direction"]) if read else None
                    if against:
                        skipped.append(f"best read ({read['why']}): {against}")
                        read = None
                    if read:
                        kind = read["direction"]
                        planned = _exit_session(td, entry_date, BEST_READ["hold_days"])
                        spec = {"source": "best_read", "strategy": "best_read",
                                "label": f"Most confident signal — {read['why']}", "option_type": kind,
                                **BEST_READ, "spot": closes[entry_date]}
                        if _open_one(conn, spec, signal_date, entry_date, planned):
                            opened.append(f"best read {kind} 2% ITM ({read['why']})")
                        else:
                            skipped.append(_why_not(conn, spec, entry_date, planned))

            # The control: one call and one put a week, no signal involved.
            # Outside the gate on purpose — it is not a position in the book
            # and so cannot consume the session's slot.
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
                        benchmark.append(f"control {kind}")

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
                # The sale is charged on what it sold for; rows from before
                # 2026-09-24 paid the whole round trip at entry.
                exit_cost = (_exit_costs(exit_premium, t.get("lots") or 1)
                             if t.get("cost_model") == SPLIT else 0.0)
                paper_db.close_position(t["id"], td[exit_idx], exit_premium, exit_cost_rs=round(exit_cost, 2))
                closed.append(t["label"])
            else:
                paper_db.mark(t["id"], day, premium)
                marked += 1

    if can_open:
        note = None
    elif signal_date < FIRST_SIGNAL_DATE:
        note = f"the signal session ({signal_date}) is before paper observation began ({FIRST_SIGNAL_DATE})"
    else:
        note = "waiting for the entry session's option prices"
    out = {"opened": opened, "marked": marked, "closed": closed, "skipped": [s for s in skipped if s],
           "passed_over": passed_over, "benchmark_opened": benchmark,
           "entry_session": entry_date, "signal_session": signal_date, "note": note}
    try:
        paper_db.record_decision(out)
    except Exception:
        pass  # the record of a decision must never stop the decision
    return out


def _held_sides(td: list[str], entry_date: str) -> set[str]:
    """CE/PE of the book's positions still held after this close. One sold at
    this very close is not: it goes out as the new one comes in."""
    sides = set()
    for t in paper_db.open_trades():
        if not t.get("funded", 1):
            continue
        exit_idx = _exit_index(td, t["entry_date"], t["hold_days"])
        if exit_idx is not None and td[exit_idx] <= entry_date:
            continue
        sides.add(t["option_type"])
    return sides


def _against(held: set[str], kind: str) -> str | None:
    """One direction at a time: a put while a call is held (or the reverse)
    is both sides of the same bet, which is what "a call or a put, not both"
    rules out. A second position the same way on a later session is allowed."""
    other = held - {kind}
    if not other:
        return None
    name = {"CE": "call", "PE": "put"}
    return f"a {name[kind]} would bet against the open {name[other.pop()]}"


def _formed_on(signal_date: str) -> list[dict]:
    """The patterns that formed on the close of `signal_date`, judged on
    history that ends at that close.

    The evening job runs after the *entry* session has closed, so the newest
    final bar is the entry session, not the signal one, and the dashboard's
    pattern scan is dated to it. This used to take that scan and keep it only
    when its date equalled the signal date, which at 19:30 it never does, so
    no pattern position could ever open and the best read said "nothing
    formed" on days a pattern had. Reading each rule off the truncated
    history answers the question actually being asked, and cannot see the
    entry session (I1).
    """
    df, _ = load_daily_data("^NSEI", 1400)
    cut = df[df.index <= signal_date]
    if cut.empty or str(cut.index[-1].date()) != signal_date:
        return []
    regime = classify_regime_series(cut)
    formed = []
    for name, spec in STRATEGY_REGISTRY.items():
        if bool(spec["fn"](cut, regime, **spec["params"]).astype(bool).iloc[-1]):
            formed.append({"strategy": name, "label": spec.get("label", name)})
    return formed


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
    is below its bar; this ranks them anyway, which is the point.

    Structural and news hypotheses are pooled because they are measured the
    same way, against the same baseline, on the same holdout. A news signal
    therefore earns its place here only by its record, exactly like the
    others — it is not given one for being newer or for having Jev behind it.
    """
    from backtest.structural_research import load_structural_research

    out: dict[str, float] = {}
    loaders = [load_structural_research]
    try:
        from backtest.news_research import load_news_research
        loaders.append(load_news_research)
    except Exception:
        pass  # the news study is optional; the book works without it
    for load in loaders:
        try:
            r = load() or {}
        except Exception:
            continue
        for h in r.get("hypotheses", []):
            t = (h.get("holdout") or {}).get("t")
            if t is not None:
                out[h["name"]] = t
    return out


def _confident_read(signal_date: str, closes: dict[str, float], td: list[str]) -> dict | None:
    """One direction, from the best-evidenced signal firing that day.

    Candidates are the structural hypotheses that fired — each rejected, but
    each with a measured t against the no-signal baseline. The highest
    positive t wins. A negative t is evidence the signal did *worse* than
    doing nothing, so those are not followed; if nothing positive fires, the
    trend fallback is used and the row says which it was."""
    from backtest.structural_research import signals_on

    try:
        fired = dict(signals_on(signal_date))
    except Exception:
        fired = {}
    # News signals join the same pool. They are ranked by the same measured
    # t as everything else, so a news read can only win by having the better
    # record — never by being the newest idea in the file.
    try:
        from backtest.news_research import signals_on as news_signals_on
        fired.update(news_signals_on(signal_date))
    except Exception:
        pass
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
    if t.get("cost_model") == SPLIT:
        entry_cost = t["entry_cost_rs"] if t.get("entry_cost_rs") else _entry_costs(t["entry_premium"], lots)
        settled = t["status"] == "CLOSED" and mark is None and t.get("exit_cost_rs") is not None
        # Open: the sale it would take to realise this mark, charged on the mark.
        costs = entry_cost + (t["exit_cost_rs"] if settled else _exit_costs(premium, lots))
    else:
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
    # Every open row is priced — the yardstick needs a live mark to be worth
    # reading — but the book's own figures count only what the book holds.
    held = [t for t in trades if t.get("funded", 1)]
    return {
        "index": quotes.get("index"), "source": quotes.get("source"), "quote_at": quotes.get("quote_at"),
        "marks": {str(tid): p for tid, p in marks.items()},
        "paper": {**book, "open_positions": len(held),
                  "live_priced": sum(1 for t in held if priced.get(t["id"]) is not None),
                  "unrealised_rs": round(sum((_pnl(t, marks.get(t["id"])) or {}).get("profit_rs", 0) for t in held))},
    }


def equity_curve(marks: dict[int, float] | None = None) -> list[dict]:
    """The book's value after each event, oldest first: money allocated,
    then every closed trade's profit or loss, then today's open marks.

    Money is added when a trade wins and taken away when it loses — that is
    the whole curve, and it is the only scoreboard this project keeps that
    goes up and down with money rather than with evidence."""
    events: list[tuple[str, float, str]] = []
    for f in reversed(paper_db.fund_flows()):
        events.append((f["ts"][:10], float(f["amount"]), "funded" if f["amount"] > 0 else "withdrawn"))
    trades = [t for t in paper_db.all_trades() if t.get("funded", 1)]
    for t in trades:
        if t["status"] == "CLOSED" and t["exit_premium"] is not None:
            pnl = _pnl(t)
            if pnl:
                events.append((t["exit_date"] or t["entry_date"], float(pnl["profit_rs"]), t["strategy"]))
    events.sort(key=lambda e: e[0])

    # `pnl_rs` is what trades have made, cumulatively. Money moved in or out
    # changes the book's value but not that: a withdrawal is not a loss.
    running, pnl, curve = 0.0, 0.0, []
    for day, amount, what in events:
        running += amount
        if what not in ("funded", "withdrawn"):
            pnl += amount
        curve.append({"date": day, "equity_rs": round(running), "change_rs": round(amount), "what": what,
                      "pnl_rs": round(pnl)})
    unrealised = sum((_pnl(t, (marks or {}).get(t["id"])) or {}).get("profit_rs", 0)
                     for t in trades if t["status"] == "OPEN")
    if curve and unrealised:
        curve.append({"date": "now", "equity_rs": round(running + unrealised),
                      "change_rs": round(unrealised), "what": "open positions, marked",
                      "pnl_rs": round(pnl + unrealised)})
    return curve


def objective(curve: list[dict], book: dict) -> dict:
    """What the book is trying to do, and how it is doing at it.

    Stated plainly because the goal is a real one — grow the money allocated
    to it — and stating it is also how it stays contained: this scoreboard
    moves the paper book only. It has no path into the recommendation, which
    still says NO TRADE unless something clears the evidence bar. A system
    that could talk itself into a signal to make its own number go up would
    be worth nothing.
    """
    allocated = book["allocated_rs"]
    equity = book["equity_rs"]
    # Measured on what trades made, never on the balance: the balance also
    # moves when money is put in or taken out, and "high ₹1,00,000 · −₹50,000
    # from it" once described two withdrawals and not a single trade.
    made = [p.get("pnl_rs", 0) for p in curve] or [0]
    pnl_now = made[-1]
    pnl_high = max(0, max(made))
    return {
        "goal": "Grow what has been allocated to the paper book, without inventing a signal to do it.",
        "allocated_rs": allocated,
        "equity_rs": equity,
        "profit_rs": round(equity - allocated),
        "growth_pct": round((equity - allocated) / allocated * 100, 2) if allocated else None,
        "pnl_high_rs": round(pnl_high),
        "below_high_water_rs": round(max(pnl_high - pnl_now, 0)),
        "sizing_note": (f"Positions are sized off the book as it stands (₹{equity:,}), not off what was first "
                        f"put in: a win raises the next position, a loss lowers it. At most "
                        f"{int(MAX_PER_TRADE * 100)}% of the book goes into one position."),
        "containment": ("This number moves the paper book alone. The recommendation on the Today tab "
                        "is computed from the evidence bar and never from how the paper book is doing."),
    }


def report(marks: dict[int, float] | None = None) -> dict:
    rows_all = [{**t, "pnl": _pnl(t, (marks or {}).get(t["id"]))} for t in paper_db.all_trades()]
    # The book is what it holds. The yardstick is measured beside it, not
    # inside it — two rows of a benchmark are not two trades.
    trades = [t for t in rows_all if t.get("funded", 1)]
    benchmark = [t for t in rows_all if not t.get("funded", 1)]

    def side(source: str) -> dict:
        rows = [t for t in rows_all if t["source"] == source and t["status"] == "CLOSED" and t["pnl"]]
        nets = [t["pnl"]["net_pct"] for t in rows]
        rupees = [t["pnl"]["profit_rs"] for t in rows]
        return {"closed": len(rows),
                "avg_net_pct": round(statistics.mean(nets), 2) if nets else None,
                "total_rs": sum(rupees) if rupees else 0,
                "total_per_lot_rs": sum(t["pnl"]["profit_per_lot_rs"] for t in rows) if rows else 0,
                "win_rate": round(sum(x > 0 for x in nets) / len(nets), 3) if nets else None,
                "open": sum(1 for t in rows_all if t["source"] == source and t["status"] == "OPEN")}

    first = min((t["signal_date"] for t in rows_all), default=None)
    book = cash_and_equity(marks)
    curve = equity_curve(marks)
    return {
        "trades": trades,
        "benchmark": benchmark,
        # The latest evening's decision, with what it did not do and why.
        "last_decision": paper_db.last_decision(),
        "account": {**book, "flows": paper_db.fund_flows(), "max_per_trade_share": MAX_PER_TRADE,
                    "one_a_session": True},
        "equity_curve": curve,
        "objective": objective(curve, book),
        "summary": {
            "observing_since": first, "started": FIRST_SIGNAL_DATE,
            "patterns": side("pattern"), "best_read": side("best_read"), "control": side("control"),
            # The book's own trades — the yardstick is not part of the count.
            "book_closed": sum(1 for t in trades if t["status"] == "CLOSED"),
            "sessions_needed_before_this_means_anything": 15,
        },
        "note": ("Hypothetical positions at real NSE closing premiums. Nothing is ordered and no money moves. "
                 f"Costs are charged on every position, open or closed: {BUY_FRACTION:.1%} of the premium paid "
                 f"and {SELL_FRACTION:.1%} of the premium it sells for (on an open one, of its mark). A "
                 "position is only ever opened for the session that has just closed, so none of this could be "
                 "chosen knowing the outcome. The book takes one position a session, in one direction: when "
                 "several patterns form, the one with the strongest holdout evidence takes it. The control — "
                 "a call and a put bought weekly with no signal — sits outside the book. It spends none of "
                 "the allocated money and cannot take the session's slot; it is only there because a result "
                 "with nothing to compare it against means nothing."),
    }
