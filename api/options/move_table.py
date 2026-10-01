"""What an index move does to option prices: for the strikes around the
money, the premium change if NIFTY moves 25, 50, 100 or 200 points either
way, and what each contract actually did per point today.

Two numbers, kept apart:

  model     each contract's own implied volatility, solved from its price
            now (the bid-ask middle, else the last trade) with Black-76 on
            the index, so the model reproduces today's price exactly; then
            the price again with the index moved and nothing else changed.
            An instant move: a move that takes a day also pays a day of decay
            and meets a different volatility.
  measured  the slope of the contract's last price on the index across the
            day's five-minute option snapshots: premium points per index
            point as it actually traded, decay and volatility changes
            included. Only for expiries the recorder keeps.

NSE's own IV column is not used for the model: NSE computes it against the
spot in a way that leaves a call and a put at one strike two to three
points apart, so it would not reproduce the prices.
"""

from datetime import date, datetime, time

from briefing.journal import black76, implied_vol
from market_data.kite_session import IST

MOVES = (25, 50, 100, 200)
ROWS_EACH_SIDE = 8
MIN_SNAPSHOTS = 6
NSE_DATE = "%d-%b-%Y"


def years_to(expiry: date, now: datetime) -> float:
    close = datetime.combine(expiry, time(15, 30), tzinfo=IST)
    return max((close - now).total_seconds(), 0.0) / (365 * 24 * 3600)


def _price(c: dict) -> tuple[float | None, str | None]:
    bid, ask, ltp = c.get("bid"), c.get("ask"), c.get("ltp")
    if bid and ask and ask >= bid > 0:
        return (bid + ask) / 2, "mid"
    return (ltp, "last") if ltp else (None, None)


def leg(c: dict | None, kind: str, strike: float, spot: float, years: float) -> dict | None:
    """One contract: its price now, its own implied volatility, its delta,
    and its modelled price change for each move up and down."""
    if not c:
        return None
    price, basis = _price(c)
    if not price:
        return None
    iv = implied_vol(price, spot, strike, years, kind)
    out = {"price": round(price, 2), "basis": basis, "iv": round(iv * 100, 2) if iv else None,
           "delta": None, "up": {}, "down": {}}
    if iv is None:
        return out          # at or below intrinsic: no time value to solve for, no model
    model = lambda s: black76(s, strike, years, iv, kind)  # noqa: E731
    out["delta"] = round((model(spot + 1) - model(spot - 1)) / 2, 3)
    out["up_pct"], out["down_pct"] = {}, {}
    for m in MOVES:
        up, down = model(spot + m) - price, model(spot - m) - price
        out["up"][str(m)], out["down"][str(m)] = round(up, 2), round(down, 2)
        out["up_pct"][str(m)], out["down_pct"][str(m)] = round(up / price * 100, 1), round(down / price * 100, 1)
    return out


def slope(points: list[tuple[float, float]]) -> float | None:
    """Least-squares premium points per index point."""
    if len(points) < MIN_SNAPSHOTS:
        return None
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx < 1e-9:
        return None
    return round(sum((x - mx) * (y - my) for x, y in points) / sxx, 3)


def measured(expiry: date, strikes: list[float], db_path=None) -> dict:
    """Per (strike, CE/PE): the slope across the latest recorded session's
    snapshots of this expiry, and which session that was."""
    import sqlite3

    from storage.option_snapshots_db import DB_PATH
    path = db_path or DB_PATH
    if not path.exists():
        return {"session": None, "slopes": {}}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT max(substr(taken_at, 1, 10)) FROM snapshots WHERE expiry = ?",
                           (expiry.isoformat(),)).fetchone()
        day = row[0] if row else None
        if not day:
            return {"session": None, "slopes": {}}
        found: dict[tuple, list] = {}
        for strike, kind, spot, ltp in conn.execute(
                "SELECT strike, option_type, spot, ltp FROM snapshots WHERE expiry = ? AND taken_at LIKE ? "
                "AND ltp > 0 ORDER BY taken_at", (expiry.isoformat(), f"{day}%")):
            if float(strike) in strikes:
                found.setdefault((float(strike), kind), []).append((float(spot), float(ltp)))
    finally:
        conn.close()
    return {"session": day, "snapshots": max((len(v) for v in found.values()), default=0),
            "slopes": {f"{k[0]:g}{k[1]}": slope(v) for k, v in found.items()}}


def build_move_table(chain: dict, now: datetime, db_path=None) -> dict:
    """The strikes around the money from one expiry's chain (options/chain_table)."""
    spot = float(chain["underlying_value"])
    expiry = datetime.strptime(chain["expiry"], NSE_DATE).date()
    years = years_to(expiry, now)
    rows = chain["rows"]
    k = next(i for i, r in enumerate(rows) if r["is_atm"])
    near = rows[max(0, k - ROWS_EACH_SIDE):k + ROWS_EACH_SIDE + 1]
    real = measured(expiry, [r["strike"] for r in near], db_path)
    out_rows = []
    for r in near:
        s = r["strike"]
        out_rows.append({"strike": s, "is_atm": r["is_atm"],
                         "call": leg(r["call"], "CE", s, spot, years), "put": leg(r["put"], "PE", s, spot, years),
                         "call_measured": real["slopes"].get(f"{s:g}CE"), "put_measured": real["slopes"].get(f"{s:g}PE")})
    return {
        "as_of": chain["as_of"], "spot": spot, "expiry": expiry.isoformat(), "expiries": chain["expiries"],
        "days_to_expiry": chain["days_to_expiry"], "years": round(years, 5), "moves": list(MOVES),
        "rows": out_rows, "measured_session": real["session"], "measured_snapshots": real.get("snapshots", 0),
        "note": ("Model: each contract's own volatility, solved from its price now, and the price again with the "
                 "index moved instantly and nothing else changed — a move that takes a day also pays a day of "
                 "decay. Measured: premium points per index point across the session's five-minute snapshots, "
                 "as the contract actually traded."),
    }


def nearest_tradable(expiries: list[str], today: date) -> str | None:
    """The nearest NSE expiry that does not expire today (the pipeline's contract)."""
    later = sorted((datetime.strptime(e, NSE_DATE).date(), e) for e in expiries
                   if datetime.strptime(e, NSE_DATE).date() > today)
    return later[0][1] if later else None
