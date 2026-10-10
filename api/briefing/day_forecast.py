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
                  daily: dict, method: str = "iv", raw_pct: float | None = None, iv_source: str = "iv30") -> dict:
    """`raw_pct` is the width the method in use gives (forecast_learning);
    without it, implied volatility alone, as the forecast began."""
    iv_raw = sigma_pct(iv, prev, target)
    raw = raw_pct if raw_pct is not None else iv_raw
    mult = 1.0
    for t in tag_list:
        mult *= cal["multipliers"].get(t, 1.0)
    sig = raw * cal["k"] * mult
    band = lambda z: [round(prev_close * math.exp(-z * sig / 100), 2), round(prev_close * math.exp(z * sig / 100), 2)]  # noqa: E731
    sess = iv * math.sqrt(1 / UNITS_PER_YEAR) * 100
    from .forecast_learning import LABELS
    return {"target": target.isoformat(), "prev": prev.isoformat(), "prev_close": round(prev_close, 2),
            "iv30": round(iv * 100, 2), "iv_source": iv_source, "sigma_raw_pct": round(raw, 3), "k": cal["k"],
            "tag_multiplier": round(mult, 3), "sigma_pct": round(sig, 3), "sigma_pts": round(prev_close * sig / 100, 1),
            "band68": band(Z68), "band95": band(Z95),
            # The day's range widens with the close band: the same ratio to plain IV.
            "expected_range_pts": round(prev_close * sess * cal["range_ratio"] * (sig / iv_raw) / 100, 1),
            "method": method, "method_label": LABELS.get(method, method),
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

def fill_from_nse(daily: dict, nse: dict) -> tuple[dict, list[date]]:
    """Sessions after the Kite archive's last, from NSE's own index report.
    On 5 Oct 2026 the Kite login had lapsed and the archive stopped at 1 Oct,
    so nothing was scored or forecast. NSE's closes match Kite's on every
    shared day; a day NSE reported without its range is not used, since a
    score needs the high and low."""
    last = max(daily) if daily else date.min
    filled = sorted(d for d, b in nse.items() if d > last and all(b.get(k) for k in ("open", "high", "low", "close")))
    return {**daily, **{d: nse[d] for d in filled}}, filled


def iv_on(day: date, iv30: dict, vix: dict) -> tuple[float | None, str | None]:
    """The 30-day implied volatility for `day`: the series built from the
    options archive, or — when that is late — India VIX, NSE's own 30-day
    implied volatility of NIFTY, scaled by its median ratio to the series
    over the last 60 days both have."""
    if day in iv30:
        return iv30[day], "iv30"
    if day not in vix:
        return None, None
    both = sorted(d for d in iv30 if d in vix and vix[d] and d < day)[-60:]
    ratio = statistics.median(iv30[d] * 100 / vix[d] for d in both) if both else 1.0
    return vix[day] / 100 * ratio, f"India VIX {vix[day]:.2f}, scaled ×{ratio:.3f} to the IV series (the series was late)"


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
    nse, vix = {}, {}
    try:
        conn = sqlite3.connect(f"file:{API_DIR / 'data' / 'nse_indices.db'}?mode=ro", uri=True)
        try:
            for name, d, o, h, lo, c in conn.execute(
                    "SELECT index_name, trade_date, open, high, low, close FROM index_daily "
                    "WHERE index_name IN ('Nifty 50', 'India VIX') AND trade_date >= ?",
                    ((today - timedelta(days=120)).isoformat(),)):
                if name == "India VIX":
                    vix[date.fromisoformat(d)] = float(c)
                else:
                    nse[date.fromisoformat(d)] = {"open": o, "high": h, "low": lo, "close": c}
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # no NSE archive: the Kite archive alone, as before
    daily, filled = fill_from_nse(daily, nse)
    return {"daily": daily, "iv30": iv30, "vix": vix, "events": events(), "expiries": set(load_expiries()),
            "filled_from_nse": [d.isoformat() for d in filled]}


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
    iv, iv_source = iv_on(last, iv30, data.get("vix", {}))
    if now < opens and target.isoformat() not in have and iv is not None:
        from . import forecast_learning as fl
        past = [r for r in rows if r["day"] <= last]
        choices = db.method_choices(db_path)
        in_use = choices[-1]["choice"]["champion"] if choices else "iv"
        choice = fl.compare(past, in_use)
        db.add_method_choice(last.isoformat(), now.isoformat(timespec="seconds"), choice, db_path)
        method = choice["champion"]
        cal = calibration(fl.method_rows(past, method))
        fc = make_forecast(last, daily[last]["close"], target, iv, cal,
                           tags(target, data["events"], data["expiries"]), daily, method=method,
                           raw_pct=fl.target_raw_sigma(past, method, iv, last, target), iv_source=iv_source)
        if db.add_forecast(target.isoformat(), now.isoformat(timespec="seconds"), fc, db_path):
            written["forecast"] = target.isoformat()
    return written


JOB_DONE_BY = time(23, 0)     # the nightly job has written tomorrow's forecast by now on a normal night


def _latest_closed(now: datetime, holidays: set) -> date:
    from market_data.nse_holidays import is_session
    d = now.date()
    if is_session(d, holidays) and now.time() >= time(15, 30):
        return d
    d -= timedelta(days=1)
    while not is_session(d, holidays):
        d -= timedelta(days=1)
    return d


def forecast_status(now: datetime, db_path, inputs: dict, holidays: set, records: list | None = None) -> dict:
    """Whether the next session has its forecast, and if not, what is missing.
    The card used to keep showing an old forecast with no word that it was old."""
    from market_data.nse_holidays import sessions_after
    from storage import day_forecast_db as db
    recs = records if records is not None else db.records(db_path)
    latest = _latest_closed(now, holidays)
    due = sessions_after(latest, 1, holidays)[0]
    opens = datetime.combine(due, time(9, 15), tzinfo=IST)
    if any(r["target_day"] == due.isoformat() for r in recs):
        return {"due": due.isoformat(), "stale": False, "waiting": False, "reasons": []}
    waiting = now.date() == latest and now.time() < JOB_DONE_BY and now < opens
    if waiting:
        return {"due": due.isoformat(), "stale": False, "waiting": True, "reasons": []}
    reasons = []
    daily = inputs["daily"]
    if latest not in daily:
        reasons.append(f"NIFTY's {latest.isoformat()} close is not in yet: the archive ends "
                       f"{max(daily).isoformat()}, and neither Kite's bars (is the login current?) nor NSE's "
                       "report has it")
    if iv_on(latest, inputs["iv30"], inputs.get("vix", {}))[0] is None:
        reasons.append(f"No implied volatility for {latest.isoformat()} yet: neither the options archive nor India VIX")
    if now >= opens:
        reasons.append(f"The {due.isoformat()} session opened before a forecast could be written")
    if not reasons:
        reasons.append("Not written yet: the forecast step has not run since the close")
    return {"due": due.isoformat(), "stale": True, "waiting": False, "reasons": reasons}


def needs_catch_up(status: dict, now: datetime, job_running: bool) -> bool:
    """A missing forecast is written outside the nightly job only while it can
    still count — before its session opens — and never while the job, which
    writes the same data, is running."""
    opens = datetime.combine(date.fromisoformat(status["due"]), time(9, 15), tzinfo=IST)
    return status["stale"] and now < opens and not job_running


def job_running(log_path) -> bool:
    """Whether the nightly job has started and not yet logged that it is done."""
    from pathlib import Path
    path = Path(log_path)
    if not path.exists():
        return False
    start = done = -1
    for i, line in enumerate(path.read_text(errors="replace").splitlines()):
        if "daily job start" in line:
            start = i
        elif "daily job done" in line:
            done = i
    return start > done


def accuracy(records: list[dict], last_n: int = 20) -> dict | None:
    """The last `last_n` scored forecasts: how often the close landed in each
    band, and whether the width ran right. The width ratio is the RMS of the
    close's error in band units: 1 is right-sized, above 1 too narrow."""
    scored = [r for r in records if r.get("outcome")][-last_n:]
    if not scored:
        return None
    n = len(scored)
    zs = [r["outcome"]["z"] for r in scored]
    ratio = round(math.sqrt(statistics.mean(z * z for z in zs)), 2)
    reading = ("running narrow: moves were bigger than the band allowed" if ratio > 1.15 else
               "running wide: moves were smaller than the band allowed" if ratio < 0.85 else "about right")
    return {"forecasts": n,
            "inside68_pct": round(sum(r["outcome"]["inside68"] for r in scored) / n * 100, 1),
            "inside95_pct": round(sum(r["outcome"]["inside95"] for r in scored) / n * 100, 1),
            "lean_hit_pct": round(sum(r["outcome"]["lean_hit"] for r in scored) / n * 100, 1),
            "width_ratio": ratio, "width_reading": reading,
            "mean_abs_move_pts": round(statistics.mean(abs(r["outcome"]["move_pts"]) for r in scored), 1),
            # The same, in counts a beginner can read: of n days, how many closes
            # landed in each range, against how many the bands are built for.
            "inside68_n": sum(r["outcome"]["inside68"] for r in scored),
            "inside95_n": sum(r["outcome"]["inside95"] for r in scored),
            "lean_n": sum(r["outcome"]["lean_hit"] for r in scored),
            "aim68_n": round(0.68 * n), "aim95_n": round(0.95 * n),
            "days": [{"day": r["target_day"], "band": "in68" if r["outcome"]["inside68"] else
                      "in95" if r["outcome"]["inside95"] else "out"} for r in scored],
            "plain": (f"Too early to judge: {n} day{'s' if n != 1 else ''} scored so far, about 20 are needed."
                      if n < 20 else
                      "Lately NIFTY has moved more than the ranges expected: they have been too narrow." if ratio > 1.15 else
                      "Lately NIFTY has moved less than the ranges expected: they have been too wide." if ratio < 0.85 else
                      "The ranges have been about the right size.")}


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
    from market_data.nse_holidays import trading_holidays
    holidays, _known = trading_holidays()
    choices = db.method_choices(db_path)
    learning = {"latest": choices[-1] if choices else None,
                "switches": [c for c in choices if c["choice"]["switched"]]}
    return {"next": pending[-1] if pending else None, "recent": list(reversed(scored[-10:])), "summary": summary,
            "status": forecast_status(datetime.now(IST), db_path, data, holidays, records=recs),
            "accuracy": accuracy(recs), "learning": learning,
            "hindcast": hindcast(rows, data["daily"]), "calibration_now": calibration(rows),
            "note": ("A forecast of how far NIFTY moves, made before the session and never edited, then scored. "
                     "The lean is a weekday base rate, unproven as an edge; nothing here is a reason to trade.")}
