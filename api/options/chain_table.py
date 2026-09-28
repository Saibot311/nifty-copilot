"""The NIFTY option chain, contract by contract, with a buyer's view of each.

chain_analytics.py summarises where open interest sits; this is the chain
itself — every strike NSE lists for one expiry, each call and put with the
prices NSE published — so any contract can be looked at, not only the ones
near the money.

The buyer's view is what one lot of a contract costs to buy now and what it
has to do to pay for itself: the ask, the lot, the charges both ways at the
rate card the backtests use (backtest/options_engine.py), the spread, and the
breakeven at expiry. The backtests charge an assumed 1.5% slippage a side
because the archive has no quotes; here there is a real bid and ask, so the
spread is shown as itself and no slippage is added on top.

Everything here is arithmetic over NSE's numbers. None of it says a contract
is worth buying.
"""

from datetime import date, datetime

from backtest.options_engine import LOT_SIZE, OptionsCostModel


class UnknownExpiry(ValueError):
    """An expiry NSE does not list for NIFTY."""


def _num(v) -> float | None:
    """NSE writes 0 where there was no trade, no quote or no IV. None of
    those is a zero, so they are reported as missing."""
    return float(v) if v else None


def _contract(side: dict, kind: str, strike: float, spot: float, today: date, costs: OptionsCostModel,
              lot: int) -> dict | None:
    if not side or not side.get("identifier"):
        return None  # NSE lists no contract on this side of the strike
    ltp, bid, ask = _num(side.get("lastPrice")), _num(side.get("buyPrice1")), _num(side.get("sellPrice1"))
    # Positive is out of the money, as in pattern_options: above spot for a
    # call, below it for a put.
    moneyness = ((strike - spot) if kind == "CE" else (spot - strike)) / spot * 100
    return {
        "identifier": side["identifier"],
        "ltp": ltp,
        "change": float(side.get("change") or 0) if ltp else None,
        "bid": bid, "ask": ask,
        "bid_qty": int(side.get("buyQuantity1") or 0), "ask_qty": int(side.get("sellQuantity1") or 0),
        "iv": _num(side.get("impliedVolatility")),
        "oi": int(side.get("openInterest") or 0),
        "oi_change": int(side.get("changeinOpenInterest") or 0),
        "volume": int(side.get("totalTradedVolume") or 0),
        "moneyness_pct": round(moneyness, 2),
        "itm": moneyness < 0,
        "buyer": _buyer(kind, strike, spot, ltp, bid, ask, today, costs, lot),
    }


def _buyer(kind: str, strike: float, spot: float, ltp: float | None, bid: float | None, ask: float | None,
           today: date, costs: OptionsCostModel, lot: int) -> dict | None:
    """One lot bought now: at the ask when there is one, else at the last
    trade (and it says so). No price at all, no view."""
    price, source = (ask, "ask") if ask else (ltp, "last")
    if not price:
        return None
    buy, sell = costs.buy_cost_rs(price, lot, today), costs.sell_cost_rs(price, lot, today)
    # At expiry the option is worth its intrinsic value; it has made back the
    # price and both legs' charges once that value covers them. The sale's
    # charges are taken at the price paid: at the breakeven price they differ
    # by a few rupees.
    per_unit = price + (buy + sell) / lot
    breakeven = strike + per_unit if kind == "CE" else strike - per_unit
    return {
        "price": price, "price_source": source,
        "lot_rs": round(price * lot, 2),
        "buy_charges_rs": round(buy, 2), "sell_charges_rs": round(sell, 2), "charges_rs": round(buy + sell, 2),
        "spread_rs": round((ask - bid) * lot, 2) if ask and bid else None,
        "breakeven": round(breakeven, 2),
        "needs_move_pts": round(breakeven - spot, 2),
        "needs_move_pct": round((breakeven - spot) / spot * 100, 2),
    }


def build_chain_table(data: dict, expiry: str, expiries: list[str], today: date,
                      costs: OptionsCostModel | None = None, lot: int = LOT_SIZE) -> dict:
    """Every strike of one expiry from NSE's v3 chain, in strike order."""
    costs = costs or OptionsCostModel(premium_slippage_pct=0.0)
    records = data["records"]
    spot = float(records.get("underlyingValue") or 0)
    if not spot:
        raise RuntimeError("NSE's chain carries no underlying value")
    listed = sorted((r for r in records.get("data", []) if r.get("strikePrice") is not None),
                    key=lambda r: float(r["strikePrice"]))
    if not listed:
        raise RuntimeError(f"NSE returned no strikes for {expiry}")
    atm = min((float(r["strikePrice"]) for r in listed), key=lambda s: abs(s - spot))
    rows = [{"strike": float(r["strikePrice"]), "is_atm": float(r["strikePrice"]) == atm,
             "call": _contract(r.get("CE") or {}, "CE", float(r["strikePrice"]), spot, today, costs, lot),
             "put": _contract(r.get("PE") or {}, "PE", float(r["strikePrice"]), spot, today, costs, lot)}
            for r in listed]
    return {
        "as_of": str(records.get("timestamp") or ""),
        "underlying_value": spot,
        "expiry": expiry,
        "expiries": list(expiries),
        "days_to_expiry": (datetime.strptime(expiry, "%d-%b-%Y").date() - today).days,
        "atm_strike": atm,
        "lot_size": lot,
        "strikes": len(rows),
        "rate_card": costs.summary(today),
        "rows": rows,
    }


def live_chain_table(expiry: str | None = None, today: date | None = None) -> dict:
    """The live chain for `expiry` (the nearest when not given). An expiry NSE
    does not list is refused before its chain is asked for."""
    from market_data.kite_session import IST
    from market_data.live_quote import _session

    nse = _session()
    expiries = (nse.option_chain_contract_info("NIFTY") or {}).get("expiryDates") or []
    if not expiries:
        raise RuntimeError("NSE listed no NIFTY expiries")
    target = expiry or expiries[0]
    if target not in expiries:
        raise UnknownExpiry(f"NSE lists no NIFTY expiry {target}")
    data = nse.index_option_chain("NIFTY", target)
    if not data or "records" not in data:
        raise RuntimeError("NSE returned no option-chain records")
    return build_chain_table(data, target, expiries, today or datetime.now(IST).date())
