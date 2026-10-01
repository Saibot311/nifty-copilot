"""What an index move does to option prices: for the strikes around the
money, the premium change if NIFTY moves 25, 50, 100 or 200 points either
way, and what each contract actually did per point today.

Two numbers, kept apart:

  model     each contract's own implied volatility, solved from its price
            now (the bid-ask middle, else the last trade) with Black-76 on
            the index, so the model reproduces today's price exactly; then
            the price again with the index moved, at each horizon: instantly,
            and at the close of today's session and the next sessions (NSE's
            holiday list decides which days are sessions), with that much
            less time left to expiry. "No move" is what the waiting alone
            costs. Volatility is held where it is now; it moves in practice,
            and a fall in it costs a buyer more.
  measured  the slope of the contract's last price on the index across the
            day's five-minute option snapshots: premium points per index
            point as it actually traded, decay and volatility changes
            included. Only for expiries the recorder keeps.

Time runs on a market clock, not the calendar: a session counts as one
unit, and each closed gap as the share of a session's movement such gaps
have carried in NIFTY's own data (2015-2026: an overnight 0.47, a two-day
gap 0.70, a weekend 0.99, a four-day break 1.04). On the calendar a holiday
weekend would cost a buyer three days of decay for one session of movement.

Options are valued against the forward the market prices them on, read
from the at-the-money call and put by put-call parity (strike + call - put),
not NSE's spot print: on 1 Oct 2026 the two differed by about 30 points, and
valuing against spot gave the call and put at one strike volatilities of 17.6%
and 13.9%. An index move is applied to that forward.

NSE's own IV column is not used for the model: NSE computes it against the
spot in a way that leaves a call and a put at one strike two to three
points apart, so it would not reproduce the prices.
"""

from datetime import date, datetime, time, timedelta

from briefing.journal import black76, implied_vol, intrinsic
from market_data.kite_session import IST

MOVES = (25, 50, 100, 200)
ROWS_EACH_SIDE = 8
MIN_SNAPSHOTS = 6
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
NEXT_SESSIONS = 2
# Variance of NIFTY's close-to-open gap as a share of a session's open-to-close
# variance, by the gap's calendar days (daily bars, 2015-01 to 2026-10).
GAP_WEIGHT = {1: 0.47, 2: 0.70, 3: 0.99, 4: 1.04}
# Market-clock units in a year: ~248 sessions and their gaps, weighted as above.
UNITS_PER_YEAR = 395.0
NSE_DATE = "%d-%b-%Y"


def years_to(expiry: date, now: datetime, holidays: set | None = None) -> float:
    """Market-clock years from `now` to the expiry's 15:30 close: the rest of
    any session in progress, each session after it, and each closed gap
    before a session at its measured weight (pro rata if part has passed)."""
    from market_data.nse_holidays import is_session
    hol = holidays or set()
    if now >= datetime.combine(expiry, SESSION_CLOSE, tzinfo=IST):
        return 0.0

    def prev_session(d: date) -> date:
        d -= timedelta(days=1)
        while not is_session(d, hol):
            d -= timedelta(days=1)
        return d
    units, day = 0.0, now.date()
    while day <= expiry:
        if is_session(day, hol):
            open_at = datetime.combine(day, SESSION_OPEN, tzinfo=IST)
            close_at = datetime.combine(day, SESSION_CLOSE, tzinfo=IST)
            if now < close_at:
                if now < open_at:
                    before = prev_session(day)
                    gap_from = datetime.combine(before, SESSION_CLOSE, tzinfo=IST)
                    share = min(1.0, (open_at - now).total_seconds() / (open_at - gap_from).total_seconds())
                    units += GAP_WEIGHT[min((day - before).days, 4)] * share + 1.0
                else:
                    units += (close_at - now).total_seconds() / (close_at - open_at).total_seconds()
        day += timedelta(days=1)
    return units / UNITS_PER_YEAR


def _price(c: dict) -> tuple[float | None, str | None]:
    bid, ask, ltp = c.get("bid"), c.get("ask"), c.get("ltp")
    if bid and ask and ask >= bid > 0:
        return (bid + ask) / 2, "mid"
    return (ltp, "last") if ltp else (None, None)


def horizons(now: datetime, expiry: date, holidays: set) -> list[dict]:
    """Instantly; today's close while today's session is still open; then the
    next sessions' closes, up to and including expiry day."""
    from market_data.nse_holidays import is_session, sessions_after
    out = [{"key": "now", "label": "Instantly", "at": now}]
    today = now.date()
    if is_session(today, holidays) and now.time() < SESSION_CLOSE and today <= expiry:
        out.append({"key": "today", "label": "By today's close", "at": datetime.combine(today, SESSION_CLOSE, tzinfo=IST)})
    for d in sessions_after(today, NEXT_SESSIONS, holidays):
        if d > expiry:
            break
        label = f"By {d.day} {d:%b} close" + (" (expiry)" if d == expiry else "")
        out.append({"key": d.isoformat(), "label": label, "at": datetime.combine(d, SESSION_CLOSE, tzinfo=IST)})
    return out


def leg(c: dict | None, kind: str, strike: float, spot: float, years: float,
        later: list[dict] | None = None, expiry: date | None = None, holidays: set | None = None) -> dict | None:
    """One contract: its price now, its own implied volatility, its delta,
    and its modelled price change for each move up and down, instantly and
    at each later horizon (with that much less time left)."""
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
    out["at"] = {}
    for h in later or []:
        left = years_to(expiry, h["at"], holidays) if expiry else 0.0
        value = (lambda s: black76(s, strike, left, iv, kind)) if left > 0 else (lambda s: intrinsic(kind, strike, s))
        cell = {"flat": round(value(spot) - price, 2), "flat_pct": round((value(spot) - price) / price * 100, 1),
                "up": {}, "down": {}, "up_pct": {}, "down_pct": {}}
        for m in MOVES:
            up, down = value(spot + m) - price, value(spot - m) - price
            cell["up"][str(m)], cell["down"][str(m)] = round(up, 2), round(down, 2)
            cell["up_pct"][str(m)], cell["down_pct"][str(m)] = round(up / price * 100, 1), round(down / price * 100, 1)
        out["at"][h["key"]] = cell
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


def forward_from(row: dict, spot: float) -> tuple[float, str]:
    """Strike + call - put at the money (put-call parity), else the spot."""
    c, _ = _price(row.get("call") or {})
    p, _ = _price(row.get("put") or {})
    if c and p:
        return row["strike"] + c - p, "put-call parity at the money"
    return spot, "NSE's spot (no two-sided price at the money)"


def build_move_table(chain: dict, now: datetime, db_path=None, holidays: set | None = None,
                     holidays_known: bool = True) -> dict:
    """The strikes around the money from one expiry's chain (options/chain_table)."""
    index = float(chain["underlying_value"])
    expiry = datetime.strptime(chain["expiry"], NSE_DATE).date()
    years = years_to(expiry, now, holidays)
    hz = horizons(now, expiry, holidays or set())
    rows = chain["rows"]
    k = next(i for i, r in enumerate(rows) if r["is_atm"])
    spot, forward_basis = forward_from(rows[k], index)
    near = rows[max(0, k - ROWS_EACH_SIDE):k + ROWS_EACH_SIDE + 1]
    real = measured(expiry, [r["strike"] for r in near], db_path)
    out_rows = []
    for r in near:
        s = r["strike"]
        out_rows.append({"strike": s, "is_atm": r["is_atm"],
                         "call": leg(r["call"], "CE", s, spot, years, hz, expiry, holidays),
                         "put": leg(r["put"], "PE", s, spot, years, hz, expiry, holidays),
                         "call_measured": real["slopes"].get(f"{s:g}CE"), "put_measured": real["slopes"].get(f"{s:g}PE")})
    return {
        "as_of": chain["as_of"], "spot": index, "forward": round(spot, 2), "forward_basis": forward_basis, "expiry": expiry.isoformat(), "expiries": chain["expiries"],
        "days_to_expiry": chain["days_to_expiry"], "years": round(years, 5), "moves": list(MOVES),
        "horizons": [{"key": h["key"], "label": h["label"], "at": h["at"].isoformat(timespec="minutes"),
                      "hours_from_now": round((h["at"] - now).total_seconds() / 3600, 1)} for h in hz],
        "holidays_known": holidays_known,
        "rows": out_rows, "measured_session": real["session"], "measured_snapshots": real.get("snapshots", 0),
        "note": ("Model: each contract's own volatility, solved from its price now, and the price again with the "
                 "index moved — instantly, or by a session's close with that much less time to expiry, so the "
                 "decay is paid; time runs on a market clock (a session is one unit, a closed gap the share of a "
                 "session's movement such gaps have carried since 2015: a weekend about one). \"No move\" is the "
                 "decay alone. Volatility is held where it is now; if it falls, "
                 "a buyer loses more than shown. Measured: premium points per index point across the session's "
                 "five-minute snapshots, as the contract actually traded."
                 + ("" if holidays_known else " NSE's holiday list could not be read, so every weekday counts as a session."))
    }


def nearest_tradable(expiries: list[str], today: date) -> str | None:
    """The nearest NSE expiry that does not expire today (the pipeline's contract)."""
    later = sorted((datetime.strptime(e, NSE_DATE).date(), e) for e in expiries
                   if datetime.strptime(e, NSE_DATE).date() > today)
    return later[0][1] if later else None
