"""The day-ahead forecast on the Today tab: how far NIFTY is likely to move
in the next session, a direction lean, and — once the session has happened —
how it turned out and, when it missed, why.

  range   the next session's expected move from the 30-day implied
          volatility at the last close (iv.db), on the market clock of
          options/move_table (a session one unit, a closed gap its measured
          share), times a calibration factor k: the realised spread of
          forecast errors over the last CAL_WINDOW sessions. Bands for the
          close at 68% and 95%, and an expected high-low range.
  lean    the share of past sessions on that weekday (2015 on, before the
          target) that closed above the previous close; up when over half.
          A base rate, not an edge: no rule tested here has called direction
          better than chance, and the lean's own record is shown beside it.
  why     when the close lands outside the 68% band or the range runs past
          1.5 times its forecast, fixed checks name what the forecast could
          not see: an overnight gap, a scheduled event, expiry day, a jump
          in implied volatility, a one-way session — or none of them.
  learn   every night k is recomputed from the latest window, and event and
          expiry days get their own width multiplier once at least TAG_MIN of
          them have been seen. A stated rule, the same for every day: it
          widens or narrows the band, it never chooses a direction.

Before the forward record had any history, the method was checked on the
past: k fitted on 2018-23 and the bands' coverage measured on 2024-26
(`hindcast`), so the first forecast was not a guess about its own width.
Written before the session, scored after, and never edited
(storage/day_forecast_db).
"""

import math
import statistics
from datetime import date, datetime, time, timedelta

from market_data.kite_session import IST
from options.move_table import GAP_WEIGHT, UNITS_PER_YEAR

CAL_WINDOW = 120
K_BOUNDS = (0.7, 1.6)
TAG_MIN = 15
TAG_BOUNDS = (0.8, 2.0)
DEV_END = date(2024, 1, 1)
LEAN_FROM = date(2015, 1, 1)
Z68, Z95 = 1.0, 1.96
ONE_WAY = 0.7                 # |close - open| at least this share of the day's range
IV_JUMP = 0.10                # 30-day IV up 10% or more by the session's close
GAP_Z = 1.5
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")  # Budget days were special Saturday sessions


def units_between(prev: date, target: date) -> float:
    """Market-clock units from `prev`'s close to `target`'s: the gap, then the session."""
    return GAP_WEIGHT[min(max((target - prev).days, 1), 4)] + 1.0


def sigma_pct(iv30: float, prev: date, target: date) -> float:
    return iv30 * math.sqrt(units_between(prev, target) / UNITS_PER_YEAR) * 100


def tags(target: date, events: dict, expiries: set) -> list[str]:
    out = []
    if target.isoformat() in events:
        out.append("event")
    if target in expiries:
        out.append("expiry")
    return out


def _clip(v: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], v))


# --- the past, session by session ------------------------------------------------------

def history(daily: dict, iv30: dict, events: dict, expiries: set, start: date = date(2018, 1, 1)) -> list[dict]:
    """Every pair of consecutive sessions from `start`: the forecast the method
    would have made at the first close, and what the second did."""
    days = sorted(d for d in daily if d >= start)
    out = []
    for d0, d1 in zip(days, days[1:]):
        iv = iv30.get(d0)
        if not iv:
            continue
        b0, b1 = daily[d0], daily[d1]
        sig = sigma_pct(iv, d0, d1)
        sess = iv * math.sqrt(1 / UNITS_PER_YEAR) * 100
        gap_sig = iv * math.sqrt(GAP_WEIGHT[min(max((d1 - d0).days, 1), 4)] / UNITS_PER_YEAR) * 100
        ret = math.log(b1["close"] / b0["close"]) * 100
        gap = (b1["open"] / b0["close"] - 1) * 100
        out.append({"day": d1, "prev": d0, "prev_close": b0["close"], "iv30": iv, "iv30_next": iv30.get(d1),
                    "sigma": sig, "ret": ret, "z": ret / sig, "gap": gap, "gap_z": gap / gap_sig,
                    "range_ratio": (b1["high"] - b1["low"]) / b0["close"] * 100 / sess,
                    "open": b1["open"], "high": b1["high"], "low": b1["low"], "close": b1["close"],
                    "tags": tags(d1, events, expiries), "weekday": d1.weekday(), "up": b1["close"] > b0["close"]})
    return out


def calibration(rows: list[dict]) -> dict:
    """k from the last CAL_WINDOW sessions; tag multipliers and the range
    ratio from all of `rows`."""
    recent = rows[-CAL_WINDOW:]
    k = _clip(math.sqrt(statistics.mean(r["z"] ** 2 for r in recent)), K_BOUNDS) if recent else 1.0
    base = math.sqrt(statistics.mean(r["z"] ** 2 for r in rows)) if rows else 1.0
    mult = {}
    for tag in ("event", "expiry"):
        tagged = [r for r in rows if tag in r["tags"]]
        mult[tag] = (round(_clip(math.sqrt(statistics.mean(r["z"] ** 2 for r in tagged)) / base, TAG_BOUNDS), 3)
                     if len(tagged) >= TAG_MIN else 1.0)
    ratio = statistics.median(r["range_ratio"] for r in rows) if rows else 1.6
    return {"k": round(k, 3), "window": len(recent), "multipliers": mult, "range_ratio": round(ratio, 3),
            "through": rows[-1]["day"].isoformat() if rows else None}


def lean(daily: dict, target: date) -> dict:
    """The share of past sessions on the target's weekday, before it, that closed up."""
    days = sorted(d for d in daily if LEAN_FROM <= d < target)
    same = [(a, b) for a, b in zip(days, days[1:]) if b.weekday() == target.weekday()]
    ups = sum(1 for a, b in same if daily[b]["close"] > daily[a]["close"])
    p = ups / len(same) if same else 0.5
    return {"side": "up" if p > 0.5 else "down", "p_up": round(p * 100, 1), "sessions": len(same),
            "basis": f"{WEEKDAYS[target.weekday()]}s since {LEAN_FROM.year} that closed above the previous close"}


def make_forecast(prev: date, prev_close: float, target: date, iv: float, cal: dict, tag_list: list[str],
                  daily: dict) -> dict:
    raw = sigma_pct(iv, prev, target)
    mult = 1.0
    for t in tag_list:
        mult *= cal["multipliers"].get(t, 1.0)
    sig = raw * cal["k"] * mult
    band = lambda z: [round(prev_close * math.exp(-z * sig / 100), 2), round(prev_close * math.exp(z * sig / 100), 2)]  # noqa: E731
    sess = iv * math.sqrt(1 / UNITS_PER_YEAR) * 100
    return {"target": target.isoformat(), "prev": prev.isoformat(), "prev_close": round(prev_close, 2),
            "iv30": round(iv * 100, 2), "sigma_raw_pct": round(raw, 3), "k": cal["k"], "tag_multiplier": round(mult, 3),
            "sigma_pct": round(sig, 3), "sigma_pts": round(prev_close * sig / 100, 1),
            "band68": band(Z68), "band95": band(Z95),
            "expected_range_pts": round(prev_close * sess * cal["range_ratio"] * cal["k"] * mult / 100, 1),
            "tags": tag_list, "lean": lean(daily, target), "calibration": cal}


def reasons(r: dict, fc: dict) -> list[str]:
    """What the forecast could not see, by fixed checks, when it missed."""
    out = []
    if abs(r["gap_z"]) >= GAP_Z:
        out.append(f"It opened {r['gap']:+.2f}% from the close, a {abs(r['gap_z']):.1f}σ gap: news while the "
                   "market was shut.".replace("-", "−"))
    if "event" in r["tags"]:
        out.append("A scheduled event day (RBI policy, Budget or election results).")
    if "expiry" in r["tags"]:
        out.append("Weekly expiry day.")
    if r.get("iv30_next") and r["iv30_next"] / r["iv30"] - 1 >= IV_JUMP:
        out.append(f"Implied volatility rose {(r['iv30_next'] / r['iv30'] - 1) * 100:.0f}% by the close: the market "
                   "repriced risk that day.")
    rng = r["high"] - r["low"]
    if rng > 0 and abs(r["close"] - r["open"]) >= ONE_WAY * rng:
        out.append("A one-way session: it closed near its " + ("high." if r["close"] > r["open"] else "low."))
    if not out:
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(r["z_used"]) / math.sqrt(2)))) * 100
        out.append(f"None of the recorded causes. A move this size comes about {p:.0f}% of the time by chance alone.")
    return out


def score(fc: dict, r: dict) -> dict:
    """How the session went against its forecast."""
    z_used = r["ret"] / fc["sigma_pct"]
    rng = r["high"] - r["low"]
    inside68 = fc["band68"][0] <= r["close"] <= fc["band68"][1]
    out = {"open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
           "move_pts": round(r["close"] - fc["prev_close"], 1), "move_pct": round(r["ret"], 3),
           "z": round(z_used, 2), "inside68": inside68,
           "inside95": fc["band95"][0] <= r["close"] <= fc["band95"][1],
           "range_pts": round(rng, 1), "range_vs_expected": round(rng / fc["expected_range_pts"], 2) if fc["expected_range_pts"] else None,
           "lean_hit": (r["close"] > fc["prev_close"]) == (fc["lean"]["side"] == "up")}
    missed = not inside68 or (out["range_vs_expected"] or 0) > 1.5
    out["missed"] = missed
    out["why"] = reasons({**r, "z_used": z_used}, fc) if missed else []
    return out


# --- the past as a test of the method -----------------------------------------------------

def hindcast(rows: list[dict], daily: dict) -> dict:
    """k fitted on 2018-23 only, then the bands' coverage on 2024-26 at that k;
    and the lean's record on 2024-26 from earlier years only."""
    dev = [r for r in rows if r["day"] < DEV_END]
    hold = [r for r in rows if r["day"] >= DEV_END]
    if not dev or not hold:
        return {}
    cal = calibration(dev)
    cal["k"] = round(_clip(math.sqrt(statistics.mean(r["z"] ** 2 for r in dev)), K_BOUNDS), 3)
    zs = [r["z"] / cal["k"] for r in hold]
    lean_hits = []
    by_weekday: dict[int, list] = {}
    for r in rows:
        if r["day"] >= DEV_END:
            past = by_weekday.get(r["weekday"], [])
            p = sum(past) / len(past) if past else 0.5
            lean_hits.append(r["up"] == (p > 0.5))
        by_weekday.setdefault(r["weekday"], []).append(r["up"])
    return {"k_dev": cal["k"], "dev_sessions": len(dev), "holdout_sessions": len(hold),
            "holdout_inside68_pct": round(sum(abs(z) <= Z68 for z in zs) / len(zs) * 100, 1),
            "holdout_inside95_pct": round(sum(abs(z) <= Z95 for z in zs) / len(zs) * 100, 1),
            "holdout_lean_hit_pct": round(sum(lean_hits) / len(lean_hits) * 100, 1),
            "note": ("k fitted on 2018-23 only; the bands' coverage measured on 2024-26 at that k (68% and 95% if "
                     "calibrated). The lean on 2024-26 used only earlier sessions.")}


# --- data, and the nightly run ------------------------------------------------------------

def load_inputs(today: date) -> dict:
    import sqlite3

    from backtest.course_strategies import API_DIR, load_expiries
    from briefing.pipeline_candidates import events
    from market_data.bar_archive import ArchiveProvider
    daily = {date.fromisoformat(c.timestamp[:10]): {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
             for c in ArchiveProvider().get_ohlc("^NSEI", "1d", LEAN_FROM - timedelta(days=10), today)}
    conn = sqlite3.connect(f"file:{API_DIR / 'data' / 'iv.db'}?mode=ro", uri=True)
    try:
        iv30 = {date.fromisoformat(d): float(v) for d, v in conn.execute(
            "SELECT trade_date, iv_30d FROM iv_daily WHERE iv_30d > 0")}
    finally:
        conn.close()
    return {"daily": daily, "iv30": iv30, "events": events(), "expiries": set(load_expiries())}


def run_day_forecast(now: datetime | None = None, db_path=None, inputs: dict | None = None,
                     holidays: set | None = None) -> dict:
    """Score every forecast whose session has closed, then forecast the next
    session if it has not opened yet. Returns what was written."""
    from market_data.nse_holidays import sessions_after, trading_holidays
    from storage import day_forecast_db as db
    now = now or datetime.now(IST)
    data = inputs or load_inputs(now.date())
    if holidays is None:
        holidays, _known = trading_holidays()
    daily, iv30 = data["daily"], data["iv30"]
    rows = history(daily, iv30, data["events"], data["expiries"])
    by_day = {r["day"].isoformat(): r for r in rows}
    written = {"scored": [], "forecast": None}

    for rec in db.records(db_path):
        if rec["outcome"] is None and rec["target_day"] in by_day:
            db.add_outcome(rec["target_day"], now.isoformat(timespec="seconds"),
                           score(rec["forecast"], by_day[rec["target_day"]]), db_path)
            written["scored"].append(rec["target_day"])

    last = max(d for d in daily if d <= now.date())
    target = sessions_after(last, 1, holidays)[0]
    opens = datetime.combine(target, time(9, 15), tzinfo=IST)
    have = {r["target_day"] for r in db.records(db_path)}
    if now < opens and target.isoformat() not in have and last in iv30:
        cal = calibration([r for r in rows if r["day"] <= last])
        fc = make_forecast(last, daily[last]["close"], target, iv30[last], cal,
                           tags(target, data["events"], data["expiries"]), daily)
        if db.add_forecast(target.isoformat(), now.isoformat(timespec="seconds"), fc, db_path):
            written["forecast"] = target.isoformat()
    return written


def view(db_path=None, inputs: dict | None = None) -> dict:
    """The next forecast, the record so far, and the hindcast, for the card."""
    from storage import day_forecast_db as db
    recs = db.records(db_path)
    data = inputs or load_inputs(datetime.now(IST).date())
    rows = history(data["daily"], data["iv30"], data["events"], data["expiries"])
    scored = [r for r in recs if r["outcome"]]
    pending = [r for r in recs if not r["outcome"]]
    summary = None
    if scored:
        n = len(scored)
        summary = {"forecasts": n,
                   "inside68_pct": round(sum(r["outcome"]["inside68"] for r in scored) / n * 100, 1),
                   "inside95_pct": round(sum(r["outcome"]["inside95"] for r in scored) / n * 100, 1),
                   "lean_hit_pct": round(sum(r["outcome"]["lean_hit"] for r in scored) / n * 100, 1),
                   "first": scored[0]["target_day"]}
    return {"next": pending[-1] if pending else None, "recent": list(reversed(scored[-10:])), "summary": summary,
            "hindcast": hindcast(rows, data["daily"]), "calibration_now": calibration(rows),
            "note": ("A forecast of how far NIFTY moves, made before the session and never edited, then scored. "
                     "The lean is a weekday base rate, unproven as an edge; nothing here is a reason to trade.")}
