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


def build_trade(table: dict, rules: Rules = DEFAULT_RULES) -> dict:
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
    return {
        "action": "BUY_CE" if side == "CE" else "BUY_PE",
        "reason": None,
        "trade": {
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
        },
        **base,
    }


def parse_rules(values: dict) -> Rules:
    """Rules from query values; anything not given keeps its default."""
    given = {k: v for k, v in values.items() if k in RULE_FIELDS and v is not None}
    return Rules(**{**asdict(DEFAULT_RULES), **given})


def stamp(result: dict, now: datetime, market_open: bool) -> dict:
    result["computed_at"] = now.isoformat(timespec="seconds")
    result["market_open"] = market_open
    return result
