"""The option-chain trade, live: scan until one locks, then track it to its exit.

Run from scripts/snapshot_options.py every five minutes of the session.

  SCAN   Until a trade is locked for today, and from 09:20 to 14:30 IST on a
         session day, the default rules are read off the fresh chain. The
         first trade with an entry is written to the suggestions table (the
         lock, never changed). Each look, trade or not, is recorded in `scans`.
  TRACK  Once locked and not yet exited, the locked contract's bid (the last
         price when it has no bid, and it says so) and NIFTY's spot are read
         off the chain. The first of these seen ends the trade, once:
         stop, target, invalidated (NIFTY past the lock's invalidation level),
         time. When several hold in one look the order is stop, target,
         invalidated, time: the cautious reading.

Untested, like the rule itself (options/chain_trade.py). Buyer only.
"""

from datetime import datetime, time

from storage import chain_trade_db as db

SCAN_FROM, NO_NEW_LOCKS = time(9, 20), time(14, 30)
EXIT_BY, EXIT_BY_EXPIRY_DAY = time(15, 15), time(14, 30)
NSE_DATE = "%d-%b-%Y"


def session_day(now: datetime) -> bool:
    return now.weekday() < 5


def scan_window(now: datetime) -> bool:
    return session_day(now) and SCAN_FROM <= now.time() <= NO_NEW_LOCKS


def _chain(chain: dict | None, expiry: str | None) -> dict:
    """The given chain if it is for `expiry` (or none is named); else NSE's live one."""
    if chain is not None and (expiry is None or chain.get("expiry") == expiry):
        return chain
    from options.chain_table import live_chain_table
    return live_chain_table(expiry)


def _stamped_today(table: dict, now: datetime) -> bool:
    """NSE restamps the last session's chain after the close and on holidays; such a chain is no news.
    A stamp that cannot be read is given the benefit of the doubt."""
    try:
        return datetime.strptime(str(table.get("as_of")), f"{NSE_DATE} %H:%M:%S").date() == now.date()
    except ValueError:
        return True


def scan_and_track(now: datetime, chain: dict | None = None, db_path=None, holidays: set | None = None) -> dict:
    """One look. Returns what it did: {"did": "scan"|"locked"|"track"|"exit"|"idle", ...}."""
    session = now.date().isoformat()
    # A day whose trade no run saw after the close (the Mac asleep) still ends, on time, unpriced.
    for old in db.unclosed_before(session, db_path):
        db.add_exit(old, now.isoformat(timespec="seconds"), "time",
                    {"premium": None, "premium_source": None, "spot": None, "pnl_per_unit": None,
                     "pnl_per_lot": None, "note": "not seen after the close"}, db_path)
    lock = db.suggestion_for(session, db_path)
    if lock is None:
        return _scan(now, session, chain, db_path, holidays)
    if db.exit_for(session, db_path) is not None:
        return {"did": "idle", "why": "already exited"}
    return _track(now, session, lock, chain, db_path)


def _scan(now, session, chain, db_path, holidays) -> dict:
    if not scan_window(now):
        return {"did": "idle", "why": "outside the scan window"}
    from options.chain_trade import DEFAULT_RULES, build_trade, stamp
    from options.move_table import nearest_tradable
    table = chain
    if table is None:
        from options.chain_table import live_chain_table
        first = live_chain_table(None)
        expiry = nearest_tradable(first["expiries"], now.date()) or first["expiry"]
        table = first if first["expiry"] == expiry else live_chain_table(expiry)
    if not _stamped_today(table, now):
        db.add_scan(session, now.isoformat(timespec="seconds"), "NO_TRADE",
                    f"NSE's chain is stamped {table.get('as_of')}, not today.", db_path)
        return {"did": "scan", "action": "NO_TRADE"}
    result = stamp(build_trade(table, DEFAULT_RULES, None, 2.0, now, holidays), now, True)
    t = result["trade"]
    if t and t["entry"]:
        on_record = {**result, "trade": {**t, "sizing": None}}
        db.add_suggestion(session, result["computed_at"], on_record, db_path)
        db.add_scan(session, result["computed_at"], result["action"], None, db_path)
        return {"did": "locked", "action": result["action"]}
    reason = result["reason"] or "NSE shows no price for the contract, so there is no entry."
    db.add_scan(session, result["computed_at"], "NO_TRADE", reason, db_path)
    return {"did": "scan", "action": "NO_TRADE", "reason": reason}


def current_mark(table: dict, trade: dict) -> dict:
    """The locked contract's bid now (last price, labelled, when it has no bid) and NIFTY's spot."""
    spot = float(table["underlying_value"])
    key = "call" if trade["side"] == "CE" else "put"
    row = next((r for r in table["rows"] if r["strike"] == trade["strike"]), None)
    c = row.get(key) if row else None
    if c is None:
        return {"premium": None, "source": None, "spot": spot}
    if c.get("bid"):
        return {"premium": c["bid"], "source": "bid", "spot": spot}
    if c.get("ltp"):
        return {"premium": c["ltp"], "source": "last", "spot": spot}
    return {"premium": None, "source": None, "spot": spot}


def pnl(trade: dict, premium: float) -> dict:
    """Per unit (before charges) and per lot (net of the lock's round-trip charges)."""
    lot, charges = trade.get("lot_size"), trade.get("charges_rs") or 0.0
    out = {"pnl_per_unit": round(premium - trade["entry"], 2), "pnl_per_lot": None}
    if lot:
        out["pnl_per_lot"] = round((premium - trade["entry"]) * lot - charges, 2)
    return out


def exit_kind(trade: dict, now: datetime, premium: float | None, spot: float) -> str | None:
    """Why the trade ends now, if it does. Stop before target: when both
    hold in one look the cautious reading wins."""
    if premium is not None and trade["stop"] is not None and premium <= trade["stop"]:
        return "stop"
    if premium is not None and trade["target"] is not None and premium >= trade["target"]:
        return "target"
    inv = (trade.get("levels") or {}).get("invalidation_index")
    if inv is not None and ((trade["side"] == "PE" and spot > inv) or (trade["side"] == "CE" and spot < inv)):
        return "invalidated"
    try:
        expiry_today = datetime.strptime(trade["expiry"], NSE_DATE).date() == now.date()
    except (ValueError, KeyError):
        expiry_today = False
    if now.time() >= (EXIT_BY_EXPIRY_DAY if expiry_today else EXIT_BY):
        return "time"
    return None


def _track(now, session, lock, chain, db_path) -> dict:
    trade = lock["trade"]
    if not session_day(now):
        return {"did": "idle", "why": "not a session day"}
    table = _chain(chain, trade["expiry"])
    if not _stamped_today(table, now):
        return {"did": "idle", "why": "chain not stamped today"}
    m = current_mark(table, trade)
    kind = exit_kind(trade, now, m["premium"], m["spot"])
    if kind is None:
        return {"did": "track", **m}
    if m["premium"] is None:
        # Ended by the clock or NIFTY with no price for the contract: say so rather than invent one.
        body = {"premium": None, "premium_source": None, "spot": m["spot"], "pnl_per_unit": None, "pnl_per_lot": None}
    else:
        body = {"premium": m["premium"], "premium_source": m["source"], "spot": m["spot"], **pnl(trade, m["premium"])}
    db.add_exit(session, now.isoformat(timespec="seconds"), kind, body, db_path)
    return {"did": "exit", "kind": kind, **body}


def live_block(now: datetime, table: dict | None, capital: float | None, risk_pct: float, db_path=None) -> dict:
    """What the endpoint shows; every number is computed here. `table` is the chain now (None if unavailable)."""
    from options.chain_trade import size_position
    session = now.date().isoformat()
    lock, ex = db.suggestion_for(session, db_path), db.exit_for(session, db_path)
    scan = db.last_scan(session, db_path)
    if lock is None:
        if not scan_window(now):
            return {"phase": "not_trading", "last_scan": scan,
                    "message": "Not trading now: the live trade scans 09:20–14:30 IST on session days."}
        return {"phase": "scanning", "last_scan": scan, "next_check_minutes": 5,
                "message": "Scanning the chain for a trade."}
    trade = lock["trade"]
    base = {"locked_at": lock["made_at"], "trade": trade}
    if ex is not None:
        return {"phase": "closed", **base, "exit": ex, "last_scan": scan}
    out = {"phase": "locked", **base, "last_scan": scan, "mark": None}
    if table is not None:
        m = current_mark(table, trade)
        out["mark"] = m
        if m["premium"] is not None and trade["entry"]:
            out.update(pnl(trade, m["premium"]))
            lo, hi = trade["stop"], trade["target"]
            out["position"] = (round(min(1.0, max(0.0, (m["premium"] - lo) / (hi - lo))), 3)
                               if lo is not None and hi is not None and hi > lo else None)
    if capital:
        out["sizing"] = size_position(trade, capital, risk_pct)
        lots = (out["sizing"] or {}).get("lots")
        if lots and out.get("pnl_per_lot") is not None:
            out["pnl_for_plan"] = round(lots * out["pnl_per_lot"], 2)
    return out
