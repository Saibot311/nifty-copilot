"""Expiry days: the footprints manipulation leaves, measured as statistics.

A participant with a large options book can profit from moving the index on
the day those options settle, even at a loss on the trades that move it.
SEBI's July 2025 interim order against Jane Street alleged exactly this on
Bank Nifty expiry days from January 2023 to March 2025: heavy buying of the
index's stocks and futures in the morning, aggressive selling into the
afternoon, while holding options that gained from the fall. The academic
literature documents two older footprints: stocks cluster at option strike
prices on expiry (Ni, Pearson & Poteshman 2005), and prices are pushed in
the window that sets the settlement price (Comerton-Forde & Putnins 2011).

Three studies test whether NIFTY shows those footprints more on its own
expiry days than on other days:

  1. The morning-afternoon reversal: a morning move undone in the afternoon.
  2. The settlement window: the size of the last-30-minute move, the window
     NSE averages to set the closing — and so settlement — price.
  3. Pinning: expiry closes landing near a 50-point strike.

A finding here is a statistic about the market, never evidence against any
participant. Determining manipulation is SEBI's job, on order-level data
this system does not have. The Jane Street case concerned Bank Nifty; this
archive is NIFTY, and an index-wide pattern has many possible causes —
hedging and option-sellers' delta adjustments among them.
"""

import math
import sqlite3
import statistics

from backtest.intraday import load_intraday
from storage.options_db import DB_PATH as OPTIONS_DB

SPLIT_BAR = "12:15"     # morning ends at the close of the 12:15 bar (12:30)
LAST_OPEN = "15:00"     # the settlement window: 15:00 to 15:30
LAST_BAR = "15:15"
STRIKE_STEP = 50
PIN_WITHIN = 5          # points either side of a strike; 20% of closes by chance
SHARP_MORNING = 0.4     # a morning move worth calling a move, in %
REVERSAL_SHARE = 0.6    # the afternoon undoes at least this share of it
SEBI_WINDOW = ("2023-01-01", "2025-03-31")  # the period the Jane Street order covers


def expiry_dates() -> set[str]:
    conn = sqlite3.connect(OPTIONS_DB)
    try:
        return {r[0] for r in conn.execute("SELECT DISTINCT expiry_date FROM option_bars")}
    finally:
        conn.close()


def sessions() -> list[dict]:
    """Every full session: its morning, afternoon and settlement-window moves,
    and whether NIFTY options expired that day."""
    exp = expiry_dates()
    out = []
    for d, bars in sorted(load_intraday().items()):
        o, mid, close = bars["09:15"]["open"], bars[SPLIT_BAR]["close"], bars[LAST_BAR]["close"]
        out.append({
            "date": d, "expiry": d in exp,
            "morning_pct": (mid / o - 1) * 100,
            "afternoon_pct": (close / mid - 1) * 100,
            "last30_pct": (close / bars[LAST_OPEN]["open"] - 1) * 100,
            "close": close,
        })
    return [s for s in out if s["date"] >= min(exp)] if exp else out


def _sharp_reversal(s: dict) -> bool:
    m, a = s["morning_pct"], s["afternoon_pct"]
    return abs(m) >= SHARP_MORNING and m * a < 0 and abs(a) >= REVERSAL_SHARE * abs(m)


def _two_proportions(k1: int, n1: int, k2: int, n2: int) -> float | None:
    if min(n1, n2) == 0:
        return None
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return round((k1 / n1 - k2 / n2) / se, 2) if se > 0 else None


def _welch(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(b) < 3:
        return None
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    return round((statistics.mean(a) - statistics.mean(b)) / se, 2) if se > 0 else None


def _corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 10:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx, vy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
    return round(cov / math.sqrt(vx * vy), 3) if vx and vy else None


def _compare(rows: list[dict]) -> dict:
    e = [r for r in rows if r["expiry"]]
    n = [r for r in rows if not r["expiry"]]
    ke, kn = sum(_sharp_reversal(r) for r in e), sum(_sharp_reversal(r) for r in n)
    pe = sum(_pin_distance(r["close"]) <= PIN_WITHIN for r in e)
    pn = sum(_pin_distance(r["close"]) <= PIN_WITHIN for r in n)
    le, ln = [abs(r["last30_pct"]) for r in e], [abs(r["last30_pct"]) for r in n]
    return {
        "expiry_sessions": len(e), "other_sessions": len(n),
        "reversal": {
            "expiry_share": round(ke / len(e), 3) if e else None,
            "other_share": round(kn / len(n), 3) if n else None,
            "z": _two_proportions(ke, len(e), kn, len(n)),
            "morning_afternoon_corr_expiry": _corr([r["morning_pct"] for r in e], [r["afternoon_pct"] for r in e]),
            "morning_afternoon_corr_other": _corr([r["morning_pct"] for r in n], [r["afternoon_pct"] for r in n]),
        },
        "settlement_window": {
            "expiry_avg_abs_move_pct": round(statistics.mean(le), 3) if le else None,
            "other_avg_abs_move_pct": round(statistics.mean(ln), 3) if ln else None,
            "t": _welch(le, ln),
        },
        "pinning": {
            "expiry_share_near_strike": round(pe / len(e), 3) if e else None,
            "other_share_near_strike": round(pn / len(n), 3) if n else None,
            "chance": round(2 * PIN_WITHIN / STRIKE_STEP, 2),
            "z": _two_proportions(pe, len(e), pn, len(n)),
        },
    }


def _pin_distance(close: float) -> float:
    r = close % STRIKE_STEP
    return min(r, STRIKE_STEP - r)


def study() -> dict:
    """The three footprints, overall and split around the period SEBI's
    Jane Street order covers. |z| >= 2 is the usual line for 'more than
    chance'; three studies run at once make one false alarm unsurprising."""
    rows = sessions()
    a, b = SEBI_WINDOW
    return {
        "all": _compare(rows),
        "before_jan_2023": _compare([r for r in rows if r["date"] < a]),
        "jan_2023_to_mar_2025": _compare([r for r in rows if a <= r["date"] <= b]),
        "after_mar_2025": _compare([r for r in rows if r["date"] > b]),
        "definitions": {
            "reversal": (f"a morning move (09:15 to 12:30) of at least {SHARP_MORNING}% that the afternoon "
                         f"undoes by at least {int(REVERSAL_SHARE * 100)}% of its size"),
            "settlement_window": "the index move from 15:00 to 15:30, the window NSE averages for the closing price",
            "pinning": f"a close within {PIN_WITHIN} points of a {STRIKE_STEP}-point strike",
        },
        "caveat": ("Statistics about the whole market on expiry days, not evidence about any participant. "
                   "The Jane Street order concerned Bank Nifty; this is NIFTY. Hedging by option sellers "
                   "produces some of these same footprints lawfully."),
    }


def _percentile(value: float, history: list[float]) -> int | None:
    if not history:
        return None
    return round(100 * sum(1 for h in history if h <= value) / len(history))


def latest_session_flags() -> dict:
    """The most recent archived session, placed against history of its own
    kind (expiry days against expiry days)."""
    rows = sessions()
    if not rows:
        return {"available": False}
    last = rows[-1]
    same = [r for r in rows[:-1] if r["expiry"] == last["expiry"]]
    exp = sorted(d for d in expiry_dates() if d > last["date"])
    return {
        "available": True, "date": last["date"], "was_expiry": last["expiry"],
        "next_expiry": exp[0] if exp else None,
        "morning_pct": round(last["morning_pct"], 2), "afternoon_pct": round(last["afternoon_pct"], 2),
        "last30_pct": round(last["last30_pct"], 2),
        "sharp_reversal": _sharp_reversal(last),
        "last30_percentile": _percentile(abs(last["last30_pct"]), [abs(r["last30_pct"]) for r in same]),
        "reversal_size_percentile": _percentile(abs(last["afternoon_pct"]) if last["morning_pct"] * last["afternoon_pct"] < 0 else 0,
                                                [abs(r["afternoon_pct"]) if r["morning_pct"] * r["afternoon_pct"] < 0 else 0
                                                 for r in same]),
        "pin_distance_points": round(_pin_distance(last["close"]), 1),
        "compared_with": f"{len(same)} earlier {'expiry' if last['expiry'] else 'non-expiry'} sessions",
    }


MONEYNESS_STEP = 0.25  # % of spot


def _shares(conn, trade_date: str, expiry: str, spot: float) -> dict:
    """Each strike's share of that expiry's contracts that day, keyed by
    moneyness bucket and type. Shares rather than counts: lot sizes changed
    (November 2024, and since), and overall activity swings with the market."""
    rows = conn.execute("SELECT strike, option_type, contracts FROM option_bars "
                        "WHERE trade_date=? AND expiry_date=?", (trade_date, expiry)).fetchall()
    total = sum(r[2] or 0 for r in rows)
    out = {}
    if not total:
        return out
    for strike, kind, vol in rows:
        bucket = round(round((strike / spot - 1) * 100 / MONEYNESS_STEP) * MONEYNESS_STEP, 2)
        key = (bucket, kind)
        out[key] = out.get(key, 0.0) + (vol or 0) / total
    return out


def _parity_spot(conn, trade_date: str, expiry: str) -> float | None:
    """The forward read off that expiry's own put-call parity. A few days
    from expiry it is spot to within a few points, and it needs no other
    source to have caught up — the option archive often has a day the price
    feeds do not yet."""
    from backtest.iv_research import _years, chain
    from options.iv import fit_forward

    calls, puts = chain(conn, trade_date, expiry)
    both = set(calls) & set(puts)
    if not both:
        return None
    guess = min(both, key=lambda k: abs(calls[k] - puts[k]))
    fit = fit_forward(calls, puts, guess, max(_years(trade_date, expiry), 1 / 365))
    return fit.forward if fit.method != "fallback" else None


# Chosen by measuring how often each threshold fires on ordinary sessions
# (60 sessions of 2025-26): z >= 3 flagged 40% of them, 4 flagged 18%, 5
# flagged 8%, 6 flagged 3%. Share-of-volume has fat tails, so the textbook
# "3 sigma is rare" is not true here. At 5 a flag appears about once in
# twelve sessions — rare enough to mean something.
UNUSUAL_Z = 5.0


def unusual_option_activity(top: int = 5, z_min: float = UNUSUAL_Z, cycles: int = 20, min_share: float = 0.02,
                            as_of: str | None = None) -> dict:
    """Where trading concentrated in the nearest expiry on the last archived
    day, against the same point — the same number of days before expiry, the
    same distance from spot — in the previous `cycles` expiries.

    The first version compared each strike with its own earlier days, and
    flagged everything the day before expiry, because volume always floods
    into the nearest strikes as expiry approaches. Comparing like with like
    is the only fair baseline. A flag means someone wanted that exposure more
    than usual; it is not evidence of anything more."""
    from datetime import date, timedelta

    conn = sqlite3.connect(OPTIONS_DB)
    conn.row_factory = sqlite3.Row
    spot: dict[str, float] = {}
    try:
        last = as_of or conn.execute("SELECT MAX(trade_date) FROM option_bars").fetchone()[0]
        expiry = conn.execute("SELECT MIN(expiry_date) FROM option_bars WHERE trade_date=? AND expiry_date>=?",
                              (last, last)).fetchone()[0]
        if expiry is None:
            return {"available": False, "reason": f"no option chain archived for {last}"}
        s0 = _parity_spot(conn, last, expiry)
        if s0 is None:
            return {"available": False, "reason": f"could not read spot from the {last} option chain"}
        spot[last] = s0
        dte = (date.fromisoformat(expiry) - date.fromisoformat(last)).days
        today = _shares(conn, last, expiry, spot[last])
        past_expiries = [r[0] for r in conn.execute(
            "SELECT DISTINCT expiry_date FROM option_bars WHERE expiry_date < ? ORDER BY expiry_date DESC", (expiry,))]
        baseline: dict = {}
        used = 0
        for e in past_expiries:
            d = (date.fromisoformat(e) - timedelta(days=dte)).isoformat()
            sd_ = _parity_spot(conn, d, e)
            if sd_ is None:
                continue
            spot[d] = sd_
            sh = _shares(conn, d, e, spot[d])
            if not sh:
                continue
            for k, v in sh.items():
                baseline.setdefault(k, []).append(v)
            used += 1
            if used == cycles:
                break
    finally:
        conn.close()

    flags = []
    for k, share in today.items():
        h = baseline.get(k, []) + [0.0] * (used - len(baseline.get(k, [])))
        if used < 8 or share < min_share:
            continue
        mu, sd = statistics.mean(h), statistics.pstdev(h)
        if sd > 0 and (share - mu) / sd >= z_min:
            flags.append({"moneyness_pct": k[0], "type": k[1],
                          "strike_near": int(round(spot[last] * (1 + k[0] / 100) / 50) * 50),
                          "share_of_volume": round(share, 3), "usual_share": round(mu, 3),
                          "z": round((share - mu) / sd, 1)})
    flags.sort(key=lambda f: -f["z"])
    return {"available": True, "date": last, "expiry": expiry, "days_to_expiry": dte, "cycles_compared": used,
            "spot_from_parity": round(spot[last], 1),
            "unusual": flags[:top],
            "note": (f"Each strike's share of the day's contracts in the nearest expiry, against the same distance "
                     f"from spot at the same {dte} day(s) before expiry in the previous {used} expiries. A flag "
                     "means someone wanted that exposure more than usual — not that anything improper happened.")}
