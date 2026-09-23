"""The journal's arithmetic and its comparison with the system (Phase 13).

"Followed" means the user's decision matched the system's verdict for that
session: took a trade in the direction it said, or stayed out on NO TRADE.
Anything else is an override — and whether overrides help or hurt is the
thing this exists to measure, once there are enough of them."""

import statistics

from backtest.options_engine import OptionsCostModel
from storage import journal_db
from storage.forward_log_db import all_recommendations

COST_FRACTION = OptionsCostModel().round_trip_cost_fraction()


def system_action_for(trade_date: str) -> str | None:
    """The verdict the forward log recorded for that session, if any."""
    for r in all_recommendations():
        if r["as_of"] == trade_date:
            return r["action"]
    return None


def pnl(e: dict) -> dict | None:
    """Rupees on a closed, bought option, after the backtests' cost model."""
    if e["decision"] != "TOOK" or e.get("exit_premium") is None or not e.get("entry_premium") or not e.get("quantity"):
        return None
    gross = (e["exit_premium"] - e["entry_premium"]) * e["quantity"]
    costs = COST_FRACTION * e["entry_premium"] * e["quantity"]
    return {"gross_rs": round(gross), "costs_rs": round(costs), "net_rs": round(gross - costs),
            "return_pct": round(100 * (gross - costs) / (e["entry_premium"] * e["quantity"]), 1)}


def followed(e: dict) -> bool | None:
    sys_action = e.get("system_action")
    if not sys_action:
        return None
    if sys_action == "NO_TRADE":
        return e["decision"] != "TOOK"
    wanted = "CE" if sys_action == "CONSIDER_CALL" else "PE"
    return e["decision"] == "TOOK" and e.get("option_type") == wanted


def report() -> dict:
    entries = []
    for e in journal_db.all_entries():
        # A decision logged during the session has no verdict yet — the
        # forward log writes it that evening. Look it up on every read so the
        # comparison appears once it exists, rather than staying blank for a
        # row that was simply logged early. Still never typed by the user.
        if not e.get("system_action"):
            e = {**e, "system_action": system_action_for(e["trade_date"])}
        entries.append({**e, "pnl": pnl(e), "followed_system": followed(e)})
    closed = [e for e in entries if e["pnl"]]
    net = [e["pnl"]["net_rs"] for e in closed]

    def group(flag):
        g = [e["pnl"]["net_rs"] for e in closed if e["followed_system"] is flag]
        return {"trades": len(g), "net_rs": sum(g), "avg_rs": round(statistics.mean(g)) if g else None}

    return {
        "entries": entries,
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
                 f"(about {COST_FRACTION:.1%} of premium). Followed means your decision matched the system's "
                 "verdict for that session. With few trades, these totals are a record, not evidence."),
    }
