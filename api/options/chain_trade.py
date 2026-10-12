"""One option to buy today, read off the live chain: the owner's exception to
"never advise a trade" (12 Oct 2026), scoped to this block alone.

UNTESTED. Nothing here has been backtested: open-interest build-up, PCR and IV
are read the way traders commonly read them, not the way the evidence says
(there is no evidence yet either way). The card says so, and every trade it
suggests under the default rules is logged before its outcome exists
(storage/chain_trade_db.py) so it builds its own record.

The rule, in words:
  1. Near the money (the ATM strike and `near_strikes` either side), compare
     the open interest added today on puts with that added on calls, as a
     share of the open interest held there. Puts written faster than calls is
     read as support below (buy a call); calls written faster, as a ceiling
     above (buy a put). A skew under `min_skew_pct` is no trade.
  2. PCR must not contradict it: at least `pcr_ce_min` for a call, at most
     `pcr_pe_max` for a put.
  3. The bought option's IV must be at most `iv_max`: past that the premium
     is dear for a buyer. A missing IV is said, not guessed, and does not block.
  4. The strike is the ATM, or `strike_offset` steps out of the money.
  5. Entry is the ask (the last trade when there is no ask, and it says so);
     target and stop-loss are `target_pct` and `stop_pct` of that premium.

Every threshold is a setting (Rules); the defaults are starting points, not
findings. Buyer only: the trade is always a bought CE or PE.
"""

import math
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

TICK = 0.05


@dataclass(frozen=True)
class Rules:
    near_strikes: int = 5
    min_skew_pct: float = 2.0
    pcr_ce_min: float = 0.8
    pcr_pe_max: float = 1.2
    iv_max: float = 30.0
    strike_offset: int = 0
    target_pct: float = 40.0
    stop_pct: float = 25.0

    def is_default(self) -> bool:
        return self == Rules()


DEFAULT_RULES = Rules()
RULE_FIELDS = tuple(f.name for f in fields(Rules))


def _tick(price: float) -> float:
    # In decimal: 101.3 * 0.75 is 75.97499... in binary, which would round down.
    ticks = (Decimal(str(round(price, 6))) / Decimal(str(TICK))).quantize(Decimal(1), ROUND_HALF_UP)
    return float(ticks * Decimal(str(TICK)))


def _no_trade(reason: str, **extra) -> dict:
    return {"action": "NO_TRADE", "reason": reason, "trade": None, **extra}


def build_trade(table: dict, rules: Rules = DEFAULT_RULES, capital: float | None = None,
                risk_pct: float = 2.0, now: datetime | None = None, holidays: set | None = None) -> dict:
    """The trade (or no trade) for one expiry's chain table (options/chain_table.py)."""
    rows = table["rows"]
    atm_i = next((i for i, r in enumerate(rows) if r["is_atm"]), None)
    oi = table.get("open_interest") or {}
    inputs = {"expiry": table["expiry"], "as_of": table.get("as_of"), "spot": table["underlying_value"],
              "atm_strike": table.get("atm_strike"), "pcr": oi.get("pcr")}
    base = {"inputs": inputs, "rules": asdict(rules), "default_rules": rules.is_default()}
    if atm_i is None:
        return {**_no_trade("The chain has no at-the-money strike."), **base}

    near = rows[max(0, atm_i - rules.near_strikes): atm_i + rules.near_strikes + 1]
    call_add = sum(r["call"]["oi_change"] for r in near if r["call"])
    put_add = sum(r["put"]["oi_change"] for r in near if r["put"])
    held = sum(r["call"]["oi"] for r in near if r["call"]) + sum(r["put"]["oi"] for r in near if r["put"])
    skew = round((put_add - call_add) / held * 100, 2) if held else None
    inputs.update({"near_from": near[0]["strike"], "near_to": near[-1]["strike"],
                   "call_oi_added": call_add, "put_oi_added": put_add, "skew_pct": skew})

    if skew is None:
        return {**_no_trade("No open interest is held near the money, so there is no build-up to read."), **base}
    if abs(skew) < rules.min_skew_pct:
        leans = "puts" if skew > 0 else "calls"
        return {**_no_trade(f"Today's build-up near the money leans {abs(skew):.1f}% toward {leans}, "
                            f"under the {rules.min_skew_pct:g}% bar."), **base}

    side = "CE" if skew > 0 else "PE"
    pcr = oi.get("pcr")
    if pcr is None:
        return {**_no_trade("PCR is missing, so the build-up cannot be checked against it."), **base}
    if side == "CE" and pcr < rules.pcr_ce_min:
        return {**_no_trade(f"Puts were added faster, but PCR {pcr:.2f} is under the call bar of "
                            f"{rules.pcr_ce_min:g}."), **base}
    if side == "PE" and pcr > rules.pcr_pe_max:
        return {**_no_trade(f"Calls were added faster, but PCR {pcr:.2f} is over the put bar of "
                            f"{rules.pcr_pe_max:g}."), **base}

    # Out of the money is up the strikes for a call, down them for a put.
    j = atm_i + rules.strike_offset if side == "CE" else atm_i - rules.strike_offset
    if not 0 <= j < len(rows):
        return {**_no_trade(f"No strike {rules.strike_offset} steps out of the money is listed."), **base}
    row = rows[j]
    contract = row["call"] if side == "CE" else row["put"]
    if not contract:
        return {**_no_trade(f"NSE lists no {side} at {row['strike']:g}."), **base}

    iv = contract.get("iv")
    if iv is not None and iv > rules.iv_max:
        return {**_no_trade(f"The {row['strike']:g} {side}'s IV is {iv:.1f}%, over the {rules.iv_max:g}% "
                            f"bar: the premium is dear for a buyer."), **base}

    buyer = contract.get("buyer")
    entry = buyer["price"] if buyer else None
    who = "Put" if side == "CE" else "Call"
    reads = "support below" if side == "CE" else "a ceiling above"
    rationale = (f"{who} writers added {abs(skew):.1f}% more of near-the-money open interest today, "
                 f"read as {reads}; PCR {pcr:.2f}"
                 + (f", IV {iv:.1f}%." if iv is not None else ", IV not reported."))
    trade = {
        "side": side, "strike": row["strike"], "expiry": table["expiry"], "identifier": contract["identifier"],
        "entry": entry, "entry_source": buyer["price_source"] if buyer else None,
        "target": _tick(entry * (1 + rules.target_pct / 100)) if entry else None,
        "stop": _tick(entry * (1 - rules.stop_pct / 100)) if entry else None,
        "iv": iv, "oi": contract["oi"], "oi_change": contract["oi_change"],
        "lot_size": table.get("lot_size"),
        "lot_rs": buyer["lot_rs"] if buyer else None,
        "charges_rs": buyer["charges_rs"] if buyer else None,
        "breakeven": buyer["breakeven"] if buyer else None,
        "rationale": rationale,
    }
    trade["sizing"] = size_position(trade, capital, risk_pct)
    trade["levels"] = build_levels(trade, table, rows, near, atm_i, row, contract, now, holidays)
    return {"action": "BUY_CE" if side == "CE" else "BUY_PE", "reason": None, "trade": trade, **base}


def _inr(v: float) -> str:
    return f"₹{v:,.0f}"


def size_position(trade: dict, capital: float | None, risk_pct: float = 2.0) -> dict | None:
    """Lots the owner's money allows: the fewer of what is affordable and what
    keeps the loss at the stop within `risk_pct` of capital. The card's charges
    figure (both ways) is counted in full against both, the cautious way."""
    entry, stop, target = trade["entry"], trade["stop"], trade["target"]
    lot, lot_rs, charges = trade["lot_size"], trade["lot_rs"], trade["charges_rs"]
    if not capital or capital <= 0 or not entry or not lot or lot_rs is None or charges is None:
        return None
    lot_cost = lot_rs + charges
    affordable = math.floor(capital / lot_cost)
    risk_per_lot = (entry - stop) * lot + charges
    by_risk = math.floor(capital * risk_pct / 100 / risk_per_lot) if risk_per_lot > 0 else 0
    lots = max(0, min(affordable, by_risk))
    note = None
    if affordable == 0:
        note = f"{_inr(capital)} buys no lot: one lot costs {_inr(lot_cost)}."
    elif lots == 0:
        note = (f"One lot would risk {_inr(risk_per_lot)} at the stop, more than {risk_pct:g}% "
                f"of {_inr(capital)} ({_inr(capital * risk_pct / 100)}).")
    return {
        "capital": capital, "risk_pct": risk_pct,
        "lot_cost_rs": round(lot_cost, 2), "affordable_lots": affordable,
        "risk_per_lot_rs": round(risk_per_lot, 2), "lots_by_risk": by_risk, "lots": lots,
        "quantity": lots * lot, "deployed_rs": round(lots * lot_cost, 2),
        "max_loss_rs": round(lots * risk_per_lot, 2),
        "profit_at_target_rs": round(lots * ((target - entry) * lot - charges), 2),
        "limited_by": None if lots == 0 else ("risk" if by_risk < affordable else "money"),
        "note": note,
    }


def build_levels(trade: dict, table: dict, rows: list, near: list, atm_i: int, row: dict, contract: dict,
                 now: datetime | None, holidays: set | None) -> dict:
    """Where to enter and exit in NIFTY terms, beside the premium levels.
    Support/ceiling: the strike with the most put/call OI added today on the
    right side of spot among the near strikes. Index equivalents of the premium
    target and stop go through the contract's delta: a first-order guide, not a
    promise (delta moves, and so does time value)."""
    side, entry, target, stop = trade["side"], trade["entry"], trade["target"], trade["stop"]
    spot = float(table["underlying_value"])
    below = [r for r in near if r["strike"] < spot and r["put"] and r["put"]["oi_change"] > 0]
    above = [r for r in near if r["strike"] > spot and r["call"] and r["call"]["oi_change"] > 0]
    support = max(below, key=lambda r: r["put"]["oi_change"])["strike"] if below else None
    ceiling = max(above, key=lambda r: r["call"]["oi_change"])["strike"] if above else None
    is_call = side == "CE"

    delta, expiry_today = None, False
    try:
        expiry_date = datetime.strptime(table["expiry"], "%d-%b-%Y").date()
        if now is not None and entry:
            from options.move_table import forward_from, leg, years_to
            expiry_today = expiry_date == now.date()
            fwd, _ = forward_from(rows[atm_i], spot)
            lg = leg(contract, side, row["strike"], fwd, years_to(expiry_date, now, holidays or set()))
            delta = lg["delta"] if lg else None
    except Exception:
        delta = None
    if delta is not None and abs(delta) < 0.02:
        delta = None

    guard = support if is_call else ceiling
    enter_at = guard if guard is not None else round(spot * (0.9975 if is_call else 1.0025))
    entry_condition = (f"Consider entering while NIFTY holds {'above' if is_call else 'below'} {enter_at:,.0f}"
                       + ("" if guard is not None else " (0.25% from now; the chain shows no clear level)"))
    max_prem = _tick(entry * 1.03) if entry else None
    target_idx = stop_idx = None
    if delta is not None and target and stop:
        sign = 1 if is_call else -1
        target_idx = round(spot + sign * (target - entry) / abs(delta))
        stop_idx = round(spot - sign * (entry - stop) / abs(delta))
    exit_by = "14:30" if expiry_today else "15:15"
    t_txt = s_txt = None
    if target and stop:
        t_txt = f"Exit at ₹{target:.2f} (about NIFTY {target_idx:,.0f}) for the target" if target_idx else \
            f"Exit at ₹{target:.2f} for the target (premium levels only: the index equivalent could not be worked out)"
        s_txt = f"Exit at ₹{stop:.2f} (about NIFTY {stop_idx:,.0f}) to cap the loss" if stop_idx else \
            f"Exit at ₹{stop:.2f} to cap the loss (premium levels only)"
    return {
        "support": support, "ceiling": ceiling, "delta": delta, "spot": spot,
        "enter_above" if is_call else "enter_below": enter_at,
        "entry_condition": entry_condition,
        "entry_max_premium": max_prem,
        "entry_max_text": f"Consider not paying more than ₹{max_prem:.2f} (3% over the ask)" if max_prem else None,
        "exit_target_index": target_idx, "exit_stop_index": stop_idx,
        "exit_target_text": t_txt, "exit_stop_text": s_txt,
        "invalidation_index": guard,
        "invalidation_text": (f"or if a 5-minute NIFTY bar closes {'below' if is_call else 'above'} {guard:,.0f}"
                              if guard is not None else None),
        "time_exit": f"Exit by {exit_by} {'(expiry day) ' if expiry_today else ''}today if neither is hit",
        "time_exit_by": exit_by,
    }


def parse_rules(values: dict) -> Rules:
    """Rules from query values; anything not given keeps its default."""
    given = {k: v for k, v in values.items() if k in RULE_FIELDS and v is not None}
    return Rules(**{**asdict(DEFAULT_RULES), **given})


def stamp(result: dict, now: datetime, market_open: bool) -> dict:
    result["computed_at"] = now.isoformat(timespec="seconds")
    result["market_open"] = market_open
    return result
