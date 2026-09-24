"""Deterministic analytics computed from the LIVE NIFTY option chain.

Every number here is arithmetic over data NSE published — put-call ratios,
open-interest concentrations, at-the-money implied volatility. Nothing is
estimated or inferred by a language model.

Worth being clear about interpretation: max-OI strikes are widely treated
as support/resistance, and PCR as a sentiment gauge, but this project has
NOT yet tested whether either actually predicts anything on NIFTY. They
are reported as measurements, not as signals, until backtested.
"""

from dataclasses import dataclass, field

# Strikes either side of the money to report in the ladder. NIFTY trades in
# 50-point strikes, so this is roughly +/- 600 points — wide enough to hold
# the week's action and narrow enough that the profile is readable.
LADDER_EACH_SIDE = 12
# ...but never so narrow that it leaves out the strikes the card names. The
# heaviest call open interest sat at 24,000 with spot at 23,063 — nineteen
# strikes away, so the summary pointed at a level the profile did not show.
# The window stretches to cover both, up to this many strikes in total.
LADDER_MAX_ROWS = 41


@dataclass
class ChainAnalytics:
    as_of: str
    underlying_value: float
    expiry: str
    atm_strike: float
    atm_iv_call: float | None
    atm_iv_put: float | None
    total_call_oi: float
    total_put_oi: float
    pcr_oi: float | None
    max_call_oi_strike: float | None
    max_put_oi_strike: float | None
    strikes_analysed: int
    ladder: list[dict] = field(default_factory=list)
    call_oi_added: float = 0.0
    put_oi_added: float = 0.0
    notes: list[str] = field(default_factory=list)


def fetch_live_chain(symbol: str = "NIFTY") -> dict:
    """Raw live chain from NSE. Raises on failure rather than returning a
    fabricated structure — a missing chain must surface as missing.

    Uses the shared NSE session rather than building one per call: a new
    session repeats NSE's cookie handshake and opens a socket, which is
    what got this machine throttled and left twelve connections in
    CLOSE_WAIT (see market_data/live_quote.py).
    """
    from market_data.live_quote import _session

    data = _session().index_option_chain(symbol)
    if not data or "records" not in data:
        raise RuntimeError("NSE returned no option-chain records")
    return data


def analyse_chain(data: dict, expiry: str | None = None) -> ChainAnalytics:
    records = data["records"]
    rows = records.get("data", [])
    underlying = float(records.get("underlyingValue") or 0)
    expiries = records.get("expiryDates") or []

    target_expiry = expiry or (expiries[0] if expiries else None)
    if target_expiry is None:
        raise RuntimeError("No expiry dates present in option chain")

    subset = [r for r in rows if r.get("expiryDate") == target_expiry]
    if not subset:
        # NSE mixes date formats between fields; fall back to the other key.
        subset = [r for r in rows if r.get("expiryDates") == target_expiry]
    if not subset:
        raise RuntimeError(f"No option rows found for expiry {target_expiry}")

    total_call_oi = sum(float(r.get("CE", {}).get("openInterest") or 0) for r in subset)
    total_put_oi = sum(float(r.get("PE", {}).get("openInterest") or 0) for r in subset)

    strikes = [float(r["strikePrice"]) for r in subset if r.get("strikePrice") is not None]
    atm_strike = min(strikes, key=lambda s: abs(s - underlying)) if strikes else 0.0

    def _oi(side: str, row: dict) -> float:
        return float(row.get(side, {}).get("openInterest") or 0)

    call_rows = [r for r in subset if _oi("CE", r) > 0]
    put_rows = [r for r in subset if _oi("PE", r) > 0]
    max_call = max(call_rows, key=lambda r: _oi("CE", r), default=None)
    max_put = max(put_rows, key=lambda r: _oi("PE", r), default=None)

    atm_row = next((r for r in subset if float(r.get("strikePrice", -1)) == atm_strike), None)
    atm_iv_call = atm_iv_put = None
    if atm_row:
        ce_iv = atm_row.get("CE", {}).get("impliedVolatility")
        pe_iv = atm_row.get("PE", {}).get("impliedVolatility")
        atm_iv_call = float(ce_iv) if ce_iv else None
        atm_iv_put = float(pe_iv) if pe_iv else None

    # The ladder: strikes either side of the money, which is where the
    # open interest that matters actually sits. Everything far out is a
    # rounding error against it and would flatten the profile.
    def _chg(side: str, row: dict) -> float:
        return float(row.get(side, {}).get("changeinOpenInterest") or 0)

    ordered = sorted((r for r in subset if r.get("strikePrice") is not None),
                     key=lambda r: float(r["strikePrice"]))
    atm_i = next((i for i, r in enumerate(ordered) if float(r["strikePrice"]) == atm_strike), None)
    window = []
    if atm_i is not None:
        lo, hi = atm_i - LADDER_EACH_SIDE, atm_i + LADDER_EACH_SIDE
        for peak in (max_call, max_put):
            if peak is None:
                continue
            j = next((i for i, r in enumerate(ordered)
                      if float(r["strikePrice"]) == float(peak["strikePrice"])), None)
            if j is not None:
                lo, hi = min(lo, j), max(hi, j)
        # Keep it readable: trim from whichever end is further from the money.
        while hi - lo + 1 > LADDER_MAX_ROWS:
            if atm_i - lo >= hi - atm_i:
                lo += 1
            else:
                hi -= 1
        window = ordered[max(0, lo): hi + 1]
    ladder = [{
        "strike": float(r["strikePrice"]),
        "call_oi": _oi("CE", r), "call_oi_change": _chg("CE", r),
        "put_oi": _oi("PE", r), "put_oi_change": _chg("PE", r),
        "is_atm": float(r["strikePrice"]) == atm_strike,
    } for r in window]

    notes = []
    if atm_iv_call in (None, 0) and atm_iv_put in (None, 0):
        notes.append("NSE reported zero/absent IV at the ATM strike — common outside market hours.")
    if total_call_oi == 0 or total_put_oi == 0:
        notes.append("One side has zero total open interest; PCR is not meaningful here.")

    return ChainAnalytics(
        as_of=str(records.get("timestamp") or ""),
        underlying_value=underlying,
        expiry=target_expiry,
        atm_strike=atm_strike,
        atm_iv_call=atm_iv_call,
        atm_iv_put=atm_iv_put,
        total_call_oi=total_call_oi,
        total_put_oi=total_put_oi,
        pcr_oi=round(total_put_oi / total_call_oi, 3) if total_call_oi else None,
        max_call_oi_strike=float(max_call["strikePrice"]) if max_call else None,
        max_put_oi_strike=float(max_put["strikePrice"]) if max_put else None,
        strikes_analysed=len(subset),
        ladder=ladder,
        call_oi_added=sum(_chg("CE", r) for r in subset),
        put_oi_added=sum(_chg("PE", r) for r in subset),
        notes=notes,
    )


def live_chain_analytics(symbol: str = "NIFTY", expiry: str | None = None) -> dict:
    data = fetch_live_chain(symbol)
    result = analyse_chain(data, expiry)
    return {
        "as_of": result.as_of,
        "underlying_value": result.underlying_value,
        "expiry": result.expiry,
        "available_expiries": data["records"].get("expiryDates", [])[:8],
        "atm_strike": result.atm_strike,
        "atm_iv": {"call": result.atm_iv_call, "put": result.atm_iv_put},
        "open_interest": {
            "total_call": result.total_call_oi,
            "total_put": result.total_put_oi,
            "pcr": result.pcr_oi,
            "max_call_oi_strike": result.max_call_oi_strike,
            "max_put_oi_strike": result.max_put_oi_strike,
            # Today's build-up: contracts opened minus closed since the last
            # close. The level says where positions sit; the change says
            # where they were put on today, which is the part that is news.
            "call_oi_added": result.call_oi_added,
            "put_oi_added": result.put_oi_added,
            "ladder": result.ladder,
            "ladder_each_side": LADDER_EACH_SIDE,
            # True when a named peak still fell outside the window after
            # trimming, so the card can say so rather than look inconsistent.
            "peaks_shown": all(
                any(row["strike"] == peak for row in result.ladder)
                for peak in (result.max_call_oi_strike, result.max_put_oi_strike) if peak),
        },
        "strikes_analysed": result.strikes_analysed,
        "notes": result.notes,
        "interpretation_caveat": (
            "Max-OI strikes are commonly read as resistance (calls) and support (puts), and PCR as "
            "a sentiment gauge. This project has not yet backtested whether either predicts anything "
            "on NIFTY — they are reported here as measurements, not validated signals."
        ),
    }
