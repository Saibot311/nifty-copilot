"""Today's breakout levels: where they are, what price is doing at each, and
how breaks of each have gone — over history, lately, and from today on at
real option prices.

  levels   yesterday's high, low and close; the opening range (09:15-09:30,
           set at 09:30); last week's high and low; the day-ahead forecast's
           68% band; the strikes with the most call and put open interest at
           yesterday's close. Each from data that existed before it is used.
  break    a 5-minute bar closing across a level. A session that opens
           beyond a level has not broken it; it breaks when it crosses back
           and again. A break that closes back across within 30 minutes failed.
  scored   points beyond the level 15, 30 and 60 minutes after the break and
           at the close, in the break's direction; and, from 1 Oct 2026, the
           at-the-money option on the break's side bought at the ask when the
           bar closed and sold at the bid 15, 30 and 60 minutes later.
  record   every break since 2015 measured the same way, the last 60 sessions
           beside it, and the forward record kept from today, never edited.
           It is recomputed every night with that day's breaks in it: the
           figures learn as the record grows.

A description of how breaks have gone, not a signal: no break rule here has
been registered and judged against the evidence bar, and a level that "held
54% of the time" is close to a coin. Nothing here says to buy anything.
"""

import json
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from market_data.kite_session import IST

BAR_MIN = 5
OR_BARS = 3                    # 09:15, 09:20, 09:25: the range is set when the 09:25 bar closes
FAIL_BARS = 6                  # back across within 30 minutes
HORIZONS = (15, 30, 60)
LAST_BAR = 15 * 60 + 25        # the 15:25 bar closes the session
ON_TIME_S = 360                # a price taken more than 6 minutes after the bar is not counted
RECENT = 60
LABELS = {"pdh": "Yesterday's high", "pdl": "Yesterday's low", "pdc": "Yesterday's close",
          "orh": "Opening range high", "orl": "Opening range low",
          "pwh": "Last week's high", "pwl": "Last week's low",
          "fch": "Forecast band top (68%)", "fcl": "Forecast band bottom (68%)",
          "oic": "Most call open interest", "oip": "Most put open interest",
          "baseline": "Any level (random, the yardstick)"}
ORDER = tuple(LABELS)
BASELINE_LEVELS = 3            # random levels a session, within BASELINE_SPAN of the last close
BASELINE_SPAN = 0.01
RESEARCH_PATH = Path(__file__).parent.parent / "data" / "breakout_levels.json"


# --- levels ---------------------------------------------------------------------------

def day_levels(daily: dict, day: date, session: pd.DataFrame, extras: dict) -> list[dict]:
    """The levels for `day`: from earlier sessions, the opening range from its
    own first three bars once they have closed, and `extras` (forecast band,
    open-interest strikes) as given."""
    prev = [d for d in daily if d < day]
    out = []
    if prev:
        p = daily[max(prev)]
        out += [("pdh", p["high"]), ("pdl", p["low"]), ("pdc", p["close"])]
        monday = day - timedelta(days=day.weekday())
        week = [daily[d] for d in prev if monday - timedelta(days=7) <= d < monday]
        if week:
            out += [("pwh", max(b["high"] for b in week)), ("pwl", min(b["low"] for b in week))]
    if len(session) >= OR_BARS:
        out += [("orh", float(session["high"].iloc[:OR_BARS].max())),
                ("orl", float(session["low"].iloc[:OR_BARS].min()))]
    out += [(k, extras[k]) for k in ("fch", "fcl", "oic", "oip") if extras.get(k)]
    return [{"key": k, "label": LABELS[k], "price": round(float(v), 2), "start": OR_BARS if k in ("orh", "orl") else 0}
            for k, v in sorted(out, key=lambda kv: ORDER.index(kv[0]))]


def _end(ts: pd.Timestamp) -> pd.Timestamp:
    return ts + timedelta(minutes=BAR_MIN)


def breaks(key: str, level: float, session: pd.DataFrame, start: int = 0) -> list[dict]:
    """Every 5-minute close across `level` from bar `start`. The side it starts
    on is the open (or, for the opening range, the close that set it)."""
    c = session["close"].to_numpy(float)
    if len(c) <= start:
        return []
    ref = c[start - 1] if start else float(session["open"].iloc[0])
    pos = 1 if ref > level else -1 if ref < level else 0
    out = []
    for i in range(start, len(c)):
        side = 1 if c[i] > level else -1 if c[i] < level else 0
        if side and side != pos:
            if pos:
                end = _end(session.index[i])
                out.append({"level": key, "direction": "up" if side > 0 else "down", "i": i,
                            "at": f"{end:%H:%M}", "bar_close_at": end.isoformat(), "close": float(c[i]),
                            "level_price": level})
            pos = side
    return out


def complete(session: pd.DataFrame) -> bool:
    t = session.index[-1]
    return t.hour * 60 + t.minute >= LAST_BAR


def outcome(event: dict, session: pd.DataFrame) -> dict:
    """Points beyond the level, in the break's direction, at each horizon and
    the close; whether it failed; the best and worst within an hour."""
    c, h, lo = (session[k].to_numpy(float) for k in ("close", "high", "low"))
    i, lvl = event["i"], event["level_price"]
    d = 1 if event["direction"] == "up" else -1
    out = {}
    for m in HORIZONS:
        j = i + m // BAR_MIN
        out[f"pts_{m}"] = round(float((c[j] - lvl) * d), 2) if j < len(c) else None
    out["held_30"] = None if out["pts_30"] is None else bool(out["pts_30"] > 0)
    back = [bool((c[j] - lvl) * d < 0) for j in range(i + 1, min(i + 1 + FAIL_BARS, len(c)))]
    out["failed"] = True if any(back) else (False if len(back) == FAIL_BARS or complete(session) else None)
    hour = range(i + 1, min(i + 1 + 60 // BAR_MIN, len(c)))
    out["best_60"] = round(float(max(((h[j] if d > 0 else -lo[j]) - lvl * d) for j in hour)), 2) if len(hour) else None
    out["worst_60"] = round(float(min(((lo[j] if d > 0 else -h[j]) - lvl * d) for j in hour)), 2) if len(hour) else None
    out["pts_close"] = round(float((c[-1] - lvl) * d), 2) if complete(session) else None
    return out


def state(level: float, session: pd.DataFrame, events: list[dict], start: int = 0) -> dict:
    """Where price stands at a level now: untouched, tested, or broken (and failed)."""
    ref = (float(session["close"].iloc[start - 1]) if start else float(session["open"].iloc[0])) if len(session) > start else None
    opened = None if ref is None or ref == level else ("above" if ref > level else "below")
    if events:
        last = events[-1]
        o = outcome(last, session)
        return {"state": f"broken {last['direction']}", "since": last["at"], "failed": o["failed"], "opened": opened}
    s = session.iloc[start:]
    touched = bool(((s["low"] <= level) & (s["high"] >= level)).any()) if len(s) else False
    return {"state": "tested" if touched else "untouched", "since": None, "failed": None, "opened": opened}


# --- the record -----------------------------------------------------------------------

def _summ(evs: list[dict]) -> dict:
    o = [e["outcome"] for e in evs]
    held = [x["held_30"] for x in o if x.get("held_30") is not None]
    failed = [x["failed"] for x in o if x.get("failed") is not None]
    p30 = [x["pts_30"] for x in o if x.get("pts_30") is not None]
    pc = [x["pts_close"] for x in o if x.get("pts_close") is not None]
    return {"n": len(evs), "held_30_pct": round(sum(held) / len(held) * 100, 1) if held else None,
            "failed_pct": round(sum(failed) / len(failed) * 100, 1) if failed else None,
            "median_pts_30": round(statistics.median(p30), 1) if p30 else None,
            "median_pts_close": round(statistics.median(pc), 1) if pc else None}


def stats(events: list[dict], recent_sessions: int = RECENT) -> dict:
    """How breaks of each level have gone, in each direction: over all of
    `events`, and over the last `recent_sessions` sessions in them."""
    days = sorted({e["day"] for e in events})
    cut = days[-recent_sessions] if len(days) >= recent_sessions else (days[0] if days else "")
    out: dict = {}
    for key in ORDER:
        for d in ("up", "down"):
            evs = [e for e in events if e["level"] == key and e["direction"] == d]
            if evs:
                out.setdefault(key, {})[d] = {"all": _summ(evs), "recent": _summ([e for e in evs if e["day"] >= cut])}
    return out


def history(bars5: pd.DataFrame, daily: dict, extras_by_day: dict) -> list[dict]:
    """Every break in `bars5`, each session's levels built as they would have
    been that morning, each break scored."""
    if bars5.empty:
        return []
    out = []
    for day, session in bars5.groupby(bars5.index.date):
        if not [d for d in daily if d < day]:
            continue
        for lv in day_levels(daily, day, session, extras_by_day.get(day, {})):
            for e in breaks(lv["key"], lv["price"], session, lv["start"]):
                out.append({**{k: e[k] for k in ("level", "direction", "at", "level_price", "close")},
                            "day": day.isoformat(), "outcome": outcome(e, session)})
    return out


def baseline_history(bars5: pd.DataFrame, daily: dict) -> list[dict]:
    """The yardstick: random levels within 1% of each session's previous close,
    seeded by the date (so the same every night), broken and scored exactly as
    the real levels are. A level's record means something only beside this."""
    out = []
    if bars5.empty:
        return out
    for day, session in bars5.groupby(bars5.index.date):
        prev = [d for d in daily if d < day]
        if not prev:
            continue
        pc = daily[max(prev)]["close"]
        rng = np.random.default_rng(day.toordinal())
        for lvl in pc * (1 + rng.uniform(-BASELINE_SPAN, BASELINE_SPAN, BASELINE_LEVELS)):
            for e in breaks("baseline", round(float(lvl), 2), session, 0):
                out.append({**{k: e[k] for k in ("level", "direction", "at", "level_price", "close")},
                            "day": day.isoformat(), "outcome": outcome(e, session)})
    return out


def forecast_bands(daily: dict, iv30: dict, events: dict, expiries: set) -> dict:
    """The forecast's 68% band for each past session, as it would have been
    drawn that morning (the IV method, calibrated on earlier sessions only)."""
    from briefing.day_forecast import history as fc_history
    from briefing.forecast_learning import walk_forward
    rows = fc_history(daily, iv30, events, expiries, start=date(2015, 1, 1))
    widths = walk_forward(rows)["iv"]
    return {r["day"]: {"fch": r["prev_close"] * np.exp(w / 100), "fcl": r["prev_close"] * np.exp(-w / 100)}
            for r, w in zip(rows, widths) if w}


def oi_strikes(db_path=None) -> dict:
    """For each session, the strikes with the most call and put open interest
    in the nearest expiry at the previous session's close."""
    import sqlite3

    from storage.options_db import DB_PATH
    conn = sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True)
    try:
        df = pd.read_sql(
            "WITH near AS (SELECT trade_date, MIN(expiry_date) AS e FROM option_bars WHERE expiry_date > trade_date "
            "GROUP BY trade_date) SELECT b.trade_date, b.option_type, b.strike, b.open_interest FROM option_bars b "
            "JOIN near n ON b.trade_date = n.trade_date AND b.expiry_date = n.e", conn)
    finally:
        conn.close()
    if df.empty:
        return {}
    top = df.loc[df.groupby(["trade_date", "option_type"])["open_interest"].idxmax()]
    days = sorted(df["trade_date"].unique())
    nxt = dict(zip(days, days[1:]))
    out: dict = {}
    for r in top.itertuples():
        if r.trade_date in nxt:
            out.setdefault(date.fromisoformat(nxt[r.trade_date]), {})["oic" if r.option_type == "CE" else "oip"] = float(r.strike)
    return out


def load_research() -> dict | None:
    return json.loads(RESEARCH_PATH.read_text()) if RESEARCH_PATH.exists() else None


# --- the forward record ---------------------------------------------------------------

def record(now: datetime, chain_rows: list[dict], state_now: dict, listed: list[date], db_path=None) -> list[str]:
    """Writes each of today's breaks the first time a run sees it, with the
    at-the-money option on its side priced from the chain saved in the same
    run. A chain stamped before the bar closed is not a price the break could
    have had; the break waits for the next run."""
    from briefing.intraday_live import contract
    from storage import breakout_db as db
    day = date.fromisoformat(state_now["session"])
    have = {(e["level"], e["direction"], e["bar_close_at"]) for e in db.events(day.isoformat(), db_path)}
    prices = {(r["expiry"], float(r["strike"]), r["option_type"]): r for r in chain_rows}
    written = []
    for lv in state_now["levels"]:
        for e in lv["events"]:
            if (e["level"], e["direction"], e["bar_close_at"]) in have:
                continue
            c = contract(1 if e["direction"] == "up" else -1, e["close"], day, listed)
            q = prices.get((c["expiry"], float(c["strike"]), c["option_type"])) if c else None
            if not q:
                continue
            closed = datetime.fromisoformat(e["bar_close_at"])
            taken = datetime.fromisoformat(q["taken_at"]).replace(tzinfo=IST)
            if taken < closed:
                continue
            db.add_event({"trade_day": day.isoformat(), "level": e["level"], "direction": e["direction"],
                          "bar_close_at": e["bar_close_at"], "level_price": e["level_price"], "index_level": e["close"],
                          **c, "price_at": q["taken_at"], "bid": q.get("bid"), "ask": q.get("ask"), "ltp": q.get("ltp"),
                          "on_time": int((taken - closed).total_seconds() <= ON_TIME_S),
                          "recorded_at": now.isoformat(timespec="seconds")}, db_path)
            written.append(f"{e['level']} {e['direction']} {e['at']}")
    return written


def option_moves(event: dict, snapshots: list[dict]) -> dict:
    """The option bought at the ask when the bar closed, sold at the bid at the
    first snapshot within six minutes after each horizon: % of what was paid."""
    closed = datetime.fromisoformat(event["bar_close_at"])
    snaps = sorted(((datetime.fromisoformat(s["taken_at"]).replace(tzinfo=IST), s) for s in snapshots),
                   key=lambda x: x[0])
    out = {}
    for m in HORIZONS:
        due = closed + timedelta(minutes=m)
        hit = next((s for t, s in snaps if due <= t <= due + timedelta(seconds=ON_TIME_S)), None)
        out[f"pct_{m}"] = (round((hit["bid"] / event["ask"] - 1) * 100, 1)
                           if hit and hit.get("bid") and event.get("ask") else None)
    return out


# --- the live view --------------------------------------------------------------------

def daily_ohlc(today: date) -> dict:
    """Recent daily bars: Kite's archive, NSE's report for a session it lacks."""
    from briefing.day_forecast import fill_from_nse
    from market_data.bar_archive import ArchiveProvider
    daily = {date.fromisoformat(c.timestamp[:10]): {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
             for c in ArchiveProvider().get_ohlc("^NSEI", "1d", today - timedelta(days=30), today)}
    try:
        import sqlite3

        from backtest.course_strategies import API_DIR
        conn = sqlite3.connect(f"file:{API_DIR / 'data' / 'nse_indices.db'}?mode=ro", uri=True)
        try:
            nse = {date.fromisoformat(d): {"open": o, "high": h, "low": lo, "close": c} for d, o, h, lo, c in conn.execute(
                "SELECT trade_date, open, high, low, close FROM index_daily WHERE index_name = 'Nifty 50' "
                "AND trade_date >= ?", ((today - timedelta(days=30)).isoformat(),))}
        finally:
            conn.close()
        daily, _ = fill_from_nse(daily, nse)
    except Exception:
        pass
    return daily


def today_extras(day: date) -> dict:
    """Today's forecast band and the open-interest strikes at the last close."""
    out = {}
    try:
        from storage import day_forecast_db
        rec = next((r for r in day_forecast_db.records() if r["target_day"] == day.isoformat()), None)
        if rec:
            out["fch"], out["fcl"] = rec["forecast"]["band68"][1], rec["forecast"]["band68"][0]
    except Exception:
        pass
    try:
        out.update(oi_strikes_for(day))
    except Exception:
        pass
    return out


def oi_strikes_for(day: date, db_path=None) -> dict:
    """The open-interest strikes for `day` from the last archived session before it."""
    import sqlite3

    from storage.options_db import DB_PATH
    conn = sqlite3.connect(f"file:{db_path or DB_PATH}?mode=ro", uri=True)
    try:
        last = conn.execute("SELECT MAX(trade_date) FROM option_bars WHERE trade_date < ?", (day.isoformat(),)).fetchone()[0]
        if not last:
            return {}
        exp = conn.execute("SELECT MIN(expiry_date) FROM option_bars WHERE trade_date = ? AND expiry_date > ?",
                           (last, last)).fetchone()[0]
        out = {}
        for t, key in (("CE", "oic"), ("PE", "oip")):
            row = conn.execute("SELECT strike FROM option_bars WHERE trade_date = ? AND expiry_date = ? AND option_type = ? "
                               "ORDER BY open_interest DESC LIMIT 1", (last, exp, t)).fetchone()
            if row:
                out[key] = float(row[0])
        return out
    finally:
        conn.close()


def evaluate(session: pd.DataFrame, daily: dict, day: date, extras: dict) -> dict:
    """Every level for `day` with its breaks, each scored so far, and where price stands."""
    levels = []
    last = float(session["close"].iloc[-1]) if len(session) else None
    for lv in day_levels(daily, day, session, extras):
        evs = breaks(lv["key"], lv["price"], session, lv["start"]) if len(session) else []
        levels.append({**lv, "distance_pts": round(last - lv["price"], 1) if last is not None else None,
                       **state(lv["price"], session, evs, lv["start"]),
                       "events": [{**e, "outcome": outcome(e, session)} for e in evs]})
    return {"session": day.isoformat(), "last_close": last,
            "bars_through": f"{_end(session.index[-1]):%H:%M}" if len(session) else None, "levels": levels}


def state_now(now: datetime) -> dict:
    from briefing.intraday_live import daily_closes, five_minute_bars
    bars, source = five_minute_bars(now, daily_closes(now.date()))
    day = now.date()
    session = bars[bars.index.date == day] if len(bars) else bars
    if session.empty and len(bars):                       # before the open: the last session
        day = bars.index[-1].date()
        session = bars[bars.index.date == day]
    out = evaluate(session, daily_ohlc(now.date()), day, today_extras(day))
    return {**out, "source": source}


def build_breakouts(now: datetime | None = None) -> dict:
    from storage import breakout_db as db
    now = now or datetime.now(IST)
    st = state_now(now)
    research = load_research() or {}
    rec = research.get("stats", {})
    forward = db.summary()
    recorded = {(e["level"], e["direction"], e["bar_close_at"]): e for e in db.events(st["session"])}
    for lv in st["levels"]:
        lv["record"] = rec.get(lv["key"])
        lv["forward"] = forward.get(lv["key"])
        for e in lv["events"]:
            r = recorded.get((e["level"], e["direction"], e["bar_close_at"]))
            e["option"] = ({k: r[k] for k in ("expiry", "strike", "option_type", "ask", "bid", "price_at", "on_time")}
                           if r else None)
    return {**st, "as_of": now.isoformat(timespec="seconds"),
            "baseline": rec.get("baseline"),
            "record": {"computed_at": research.get("computed_at"), "since": research.get("since"),
                       "sessions": research.get("sessions"), "breaks": research.get("breaks")},
            "note": ("Levels from data that existed before each was used. A break is a 5-minute close across a level; "
                     "a break that closes back within 30 minutes failed. The record is every break since 2015 measured "
                     "the same way, recomputed nightly with each new day in it, and the last 60 sessions beside it. "
                     "From 6 Oct 2026 each break is also recorded at the real price of the at-the-money option on its "
                     "side. A description of how breaks have gone, not a signal: no break rule has been registered and "
                     "judged against the evidence bar.")}


# --- the nightly work -----------------------------------------------------------------

def score_forward(now: datetime, sessions: dict, snapshots_for, db_path=None) -> list[str]:
    """Scores each recorded break whose session is over: points at each horizon
    and the close from that session's bars, and the option's move from the
    snapshots (`snapshots_for(event)` gives its contract's rows)."""
    from storage import breakout_db as db
    scored = []
    for e in db.events(None, db_path):
        if e["outcome"]:
            continue
        day = date.fromisoformat(e["trade_day"])
        session = sessions.get(day)
        if session is None or session.empty or not complete(session) or (day == now.date() and now.hour * 60 + now.minute < 15 * 60 + 35):
            continue
        ends = [_end(t).isoformat() for t in session.index]
        if e["bar_close_at"] not in ends:
            continue
        ev = {"i": ends.index(e["bar_close_at"]), "direction": e["direction"], "level_price": e["level_price"]}
        body = {**outcome(ev, session), **option_moves(e, snapshots_for(e))}
        if db.add_outcome(e, now.isoformat(timespec="seconds"), body, db_path):
            scored.append(f"{e['trade_day']} {e['level']} {e['direction']}")
    return scored


def run_nightly(now: datetime | None = None) -> dict:
    """Rebuilds the record from every session since 2015 and scores the
    forward record's breaks. scripts/breakout_levels.py, nightly."""
    import sqlite3

    from briefing.day_forecast import load_inputs
    from market_data.bar_archive import ArchiveProvider
    from storage.option_snapshots_db import DB_PATH as SNAP_DB
    now = now or datetime.now(IST)
    inputs = load_inputs(now.date())
    daily = inputs["daily"]
    candles = ArchiveProvider().get_ohlc("^NSEI", "5m", date(2015, 1, 1), now.date())
    idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
    idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    bars5 = pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                          "low": [c.low for c in candles], "close": [c.close for c in candles]}, index=idx)
    finished = bars5[[(t.date() < now.date()) or (now.time().hour * 60 + now.time().minute >= 15 * 60 + 35)
                      for t in bars5.index]]
    extras: dict = {}
    for src in (forecast_bands(daily, inputs["iv30"], inputs["events"], inputs["expiries"]), oi_strikes()):
        for d, v in src.items():
            extras.setdefault(d, {}).update(v)
    hist = history(finished, daily, extras) + baseline_history(finished, daily)
    research = {"computed_at": now.isoformat(timespec="seconds"), "since": str(finished.index[0].date()) if len(finished) else None,
                "sessions": len({e["day"] for e in hist}), "breaks": len(hist), "stats": stats(hist)}
    RESEARCH_PATH.write_text(json.dumps(research, indent=1))

    sessions = {d: g for d, g in finished.groupby(finished.index.date)}

    def snapshots_for(e):
        conn = sqlite3.connect(f"file:{SNAP_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(
                "SELECT taken_at, bid, ask FROM snapshots WHERE expiry = ? AND strike = ? AND option_type = ? "
                "AND taken_at LIKE ?", (e["expiry"], e["strike"], e["option_type"], e["trade_day"] + "%"))]
        finally:
            conn.close()

    scored = score_forward(now, sessions, snapshots_for)
    return {"breaks": len(hist), "sessions": research["sessions"], "scored": scored}
