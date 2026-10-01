"""How NIFTY moves through a session on this weekday, point by point, and
how today compares (the Today tab's "This weekday" card).

Descriptive, not a signal. For the weekday of the session shown, over every
session in the 5-minute archive (January 2015 on, more than ten years): how
far it typically went up and down from the open,
which way the first swing went and how big it and the swing back were, when
the first swing ended, and where the index typically stood, in points from
the open, at each hour. Then today's path so far against that, and the past
same-weekday sessions whose path so far looked most like today's, with what
each did for the rest of the day — shown as a spread of outcomes, never as
a forecast. The "why" lines are measured here, not asserted.

A swing ends when the index reverses by SWING_PCT from its extreme (0.25%,
about 55 points at 22,000): a fixed, stated definition, not a fitted one.

NIFTY was near 8,000 in 2015 and 22,000+ in 2026, so points from different
years cannot be pooled as they are. Every session is measured in % of its
own open and shown as points at today's level (the reference), with the %.
"""

import math
import statistics
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from market_data.kite_session import IST

SWING_PCT = 0.25
LONG_FROM = date(2015, 1, 1)               # the 5-minute archive's start
WEEKLY_FROM = date(2019, 2, 11)            # NIFTY's weekly expiries began (expiry-day figures)
SIMILAR_K = 5
# Where the index stood at each hour, as the close of the 5-minute bar ending then.
CHECKPOINTS = ("10:15", "11:15", "12:15", "13:15", "14:15", "15:30")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def _bar_for(checkpoint: str) -> str:
    """The stamp of the 5-minute bar that closes at `checkpoint`."""
    h, m = map(int, checkpoint.split(":"))
    t = h * 60 + m - 5
    return f"{t // 60:02d}:{t % 60:02d}"


def swings(times: list, highs: list, lows: list, open_: float, pct: float = SWING_PCT) -> list[dict]:
    """The session's swings from the open: each ends when price reverses by
    `pct`% from its extreme. The last one may still be running."""
    rev = pct / 100
    direction, ext, ext_t, start, out = 0, open_, None, open_, []
    for t, h, lo in zip(times, highs, lows):
        if direction == 0:
            if h >= open_ * (1 + rev):
                direction, ext, ext_t = 1, h, t
            elif lo <= open_ * (1 - rev):
                direction, ext, ext_t = -1, lo, t
            continue
        if direction == 1:
            if h > ext:
                ext, ext_t = h, t
            elif lo <= ext * (1 - rev):
                out.append({"dir": 1, "points": ext - start, "ends": ext_t, "done": True})
                start, direction, ext, ext_t = ext, -1, lo, t
        else:
            if lo < ext:
                ext, ext_t = lo, t
            elif h >= ext * (1 + rev):
                out.append({"dir": -1, "points": start - ext, "ends": ext_t, "done": True})
                start, direction, ext, ext_t = ext, 1, h, t
    if direction:
        out.append({"dir": direction, "points": abs(ext - start), "ends": ext_t, "done": False})
    return out


def session(g: pd.DataFrame, prev_close: float | None, expiry: bool) -> dict:
    """One session's shape, from its 5-minute bars (those closed so far)."""
    o = float(g["open"].iloc[0])
    stamps = [ts.strftime("%H:%M") for ts in g.index]
    closes = dict(zip(stamps, g["close"].astype(float)))
    sw = swings(stamps, g["high"].astype(float).tolist(), g["low"].astype(float).tolist(), o)
    d = g.index[0].date()
    return {"date": d, "weekday": WEEKDAYS[d.weekday()], "expiry": expiry, "open": o,
            "up": float(g["high"].max()) - o, "down": o - float(g["low"].min()),
            "now": float(g["close"].iloc[-1]) - o, "through": stamps[-1],
            "complete": stamps[-1] == "15:25", "gap_pct": (o / prev_close - 1) * 100 if prev_close else None,
            "path": {cp: closes[_bar_for(cp)] - o for cp in CHECKPOINTS if _bar_for(cp) in closes},
            "swings": sw}


def history(bars: pd.DataFrame, closes: dict, expiries: set) -> list[dict]:
    """Every complete regular session in `bars`."""
    out = []
    days = sorted(closes)
    prev = {d: closes[days[k - 1]] for k, d in enumerate(days) if k}
    for d, g in bars.groupby(bars.index.date):
        if len(g) < 70 or g.index[0].strftime("%H:%M") != "09:15" or d.weekday() > 4:
            continue
        s = session(g, prev.get(d), d in expiries)
        if s["complete"]:
            out.append(s)
    return out


def _med(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _q(xs, q) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.percentile(xs, q)), 1) if xs else None


def _clock(stamps: list[str]) -> str | None:
    if not stamps:
        return None
    m = statistics.median(int(s[:2]) * 60 + int(s[3:]) + 5 for s in stamps)   # a bar's end, not its stamp
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


def _at(r: dict, v: float | None, ref: float) -> float | None:
    """A session's points, as % of its own open, in points at `ref`."""
    return None if v is None else v / r["open"] * ref


def profile(rows: list[dict], ref: float) -> dict | None:
    """The typical shape of these sessions, each in % of its own open, shown
    as points at `ref` (today's level)."""
    if not rows:
        return None
    first = [r["swings"][0] for r in rows if r["swings"]]
    up_first = [r for r in rows if r["swings"] and r["swings"][0]["dir"] == 1]
    down_first = [r for r in rows if r["swings"] and r["swings"][0]["dir"] == -1]
    back = lambda rs: [_at(r, r["swings"][1]["points"], ref) for r in rs if len(r["swings"]) > 1]  # noqa: E731
    rng = [(r["up"] + r["down"]) / r["open"] * 100 for r in rows]
    return {
        "sessions": len(rows), "since": min(r["date"] for r in rows).isoformat(), "ref": round(ref, 2),
        "range": _med(_at(r, r["up"] + r["down"], ref) for r in rows),
        "range_pct": round(statistics.median(rng), 3),
        "up_from_open": _med(_at(r, r["up"], ref) for r in rows),
        "down_from_open": _med(_at(r, r["down"], ref) for r in rows),
        "open_to_close": _med(_at(r, r["now"], ref) for r in rows),
        "up_first_pct": round(100 * len(up_first) / max(1, len(up_first) + len(down_first))),
        "first_up": _med(_at(r, r["swings"][0]["points"], ref) for r in up_first),
        "back_after_up": _med(back(up_first)),
        "first_down": _med(_at(r, r["swings"][0]["points"], ref) for r in down_first),
        "back_after_down": _med(back(down_first)),
        "first_swing_ends": _clock([s["ends"] for s in first if s["done"]]),
        "swings_per_day": _med(len(r["swings"]) for r in rows),
        "path": [{"at": cp, "median": _med(_at(r, r["path"].get(cp), ref) for r in rows),
                  "p25": _q([_at(r, r["path"].get(cp), ref) for r in rows], 25),
                  "p75": _q([_at(r, r["path"].get(cp), ref) for r in rows], 75)} for cp in CHECKPOINTS],
    }


def similar(today: dict, past: list[dict], k: int = SIMILAR_K) -> dict | None:
    """The past sessions whose path so far, in % of the open at the hours
    today has reached, was closest to today's; and what each did after."""
    reached = [cp for cp in CHECKPOINTS[:-1] if cp in today["path"]]
    if not reached:
        return None
    mine = [today["path"][cp] / today["open"] * 100 for cp in reached]
    last = reached[-1]
    scored = []
    for r in past:
        if not all(cp in r["path"] for cp in reached):
            continue
        theirs = [r["path"][cp] / r["open"] * 100 for cp in reached]
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(mine, theirs)) / len(reached))
        after_pct = (r["now"] - r["path"][last]) / r["open"] * 100      # from that hour to the close
        scored.append((dist, r, after_pct))
    scored.sort(key=lambda x: x[0])
    picks = scored[:k]
    if not picks:
        return None
    scale = today["open"] / 100
    days = [{"date": r["date"].isoformat(), "match_pct": round(dist, 2),
             "at_last": round(r["path"][last] / r["open"] * 100 * scale, 1),
             "after": round(after * scale, 1), "expiry": r["expiry"]} for dist, r, after in picks]
    rose = sum(1 for d in days if d["after"] > 0)
    return {"through": last, "days": days, "rose_after": rose, "fell_after": len(days) - rose,
            "note": (f"Of the {len(days)} closest, {rose} rose and {len(days) - rose} fell after {last}. Past paths "
                     "that start alike end differently; this is the spread, not a forecast.")}


def _signed(v: float, nd: int = 2) -> str:
    """+0.10 / −0.06, with a true minus sign as everywhere on the page."""
    return f"{v:+.{nd}f}".replace("-", "\u2212")


def _t(xs: list[float]) -> tuple[float, float]:
    m = statistics.mean(xs)
    return m, m / (statistics.stdev(xs) / math.sqrt(len(xs)))


def why(long_rows: list[dict], ref: float) -> list[str]:
    """Measured explanations, each with its numbers."""
    out = []
    gaps = [r["gap_pct"] for r in long_rows if r["gap_pct"] is not None]
    oc = [r["now"] / r["open"] * 100 for r in long_rows]
    if len(gaps) > 30:
        g, gt = _t(gaps)
        m, mt = _t(oc)
        since = min(r["date"] for r in long_rows).year
        out.append(f"Since {since} NIFTY's rise has come overnight: the open has been {_signed(g)}% from the previous close "
                   f"on average (t {_signed(gt, 1)}), while open to close has averaged {_signed(m)}% (t {_signed(mt, 1)}). "
                   "A gap up is "
                   "often given back during the day, on every weekday.")
    firsts = [r["swings"][0]["ends"] for r in long_rows if r["swings"] and r["swings"][0]["done"]]
    if firsts:
        early = sum(1 for s in firsts if int(s[:2]) * 60 + int(s[3:]) + 5 <= 10 * 60 + 15) / len(firsts) * 100
        out.append(f"The first swing usually ends early: median {_clock(firsts)}, and {early:.0f}% end by 10:15. The "
                   "opening auction and overnight news (GIFT Nifty, US markets) are absorbed in the first hour.")
    weekly = [r for r in long_rows if r["date"] >= WEEKLY_FROM]
    exp, other = [r for r in weekly if r["expiry"]], [r for r in weekly if not r["expiry"]]
    if len(exp) > 10 and len(other) > 10:
        dn = lambda rs: _med(_at(r, r["down"], ref) for r in rs)  # noqa: E731
        up = lambda rs: _med(_at(r, r["up"], ref) for r in rs)  # noqa: E731
        out.append(f"On the {len(exp)} weekly expiry days since February 2019 the index went {dn(exp):.0f} points "
                   f"below the open and {up(exp):.0f} above (median, at today's level), against "
                   f"{dn(other):.0f} and {up(other):.0f} on other days. NIFTY's "
                   "weekly expiry moved from Thursday to Tuesday in September 2025, so weekday and expiry overlap.")
    return out


def indicators_tested() -> list[dict]:
    """The intraday 'can it be seen coming' rules already judged, from the study."""
    from backtest.nifty_pipeline import load_nifty_pipeline
    out = []
    for h in (load_nifty_pipeline() or {}).get("hypotheses", []):
        if h["name"] in ("opening_range_5m", "noise_band", "last_half_hour"):
            out.append({"label": h["label"], "verdict": h["verdict"],
                        "holdout_t": (h.get("holdout") or {}).get("t_vs_baseline"), "required_t": h.get("required_t")})
    return out


# --- data, cached -----------------------------------------------------------------------

def _archive_bars(start: date, end: date) -> pd.DataFrame:
    from market_data.bar_archive import ArchiveProvider
    candles = ArchiveProvider().get_ohlc("^NSEI", "5m", start, end)
    idx = pd.DatetimeIndex([pd.Timestamp(c.timestamp) for c in candles])
    idx = idx.tz_localize(IST) if idx.tz is None else idx.tz_convert(IST)
    return pd.DataFrame({"open": [c.open for c in candles], "high": [c.high for c in candles],
                         "low": [c.low for c in candles], "close": [c.close for c in candles]}, index=idx)


def _history_for(today: date) -> dict:
    from backtest.course_strategies import load_expiries
    from market_data.bar_archive import ArchiveProvider
    closes = {date.fromisoformat(c.timestamp[:10]): float(c.close)
              for c in ArchiveProvider().get_ohlc("^NSEI", "1d", LONG_FROM - timedelta(days=10), today)}
    bars = _archive_bars(LONG_FROM, today - timedelta(days=1))
    rows = history(bars, closes, set(load_expiries()))
    return {"rows": rows, "closes": closes}


def build_weekday_profile(now: datetime | None = None) -> dict:
    from briefing.intraday_live import expiries, five_minute_bars
    from cache import cached
    now = now or datetime.now(IST)
    today = now.date()
    hist = cached(f"weekday_history:{today.isoformat()}", 6 * 3600, lambda: _history_for(today))
    rows = [r for r in hist["rows"] if r["date"] < today]

    bars, source = five_minute_bars(now, hist["closes"])
    todays = bars[bars.index.date == today]
    day = today
    while day.weekday() > 4:
        day += timedelta(days=1)
    listed = expiries(today)
    is_expiry = day in set(listed)
    me = None
    if not todays.empty and todays.index[0].strftime("%H:%M") == "09:15":
        prev = max((d for d in hist["closes"] if d < today), default=None)
        me = session(todays, hist["closes"].get(prev), is_expiry)
    weekday = WEEKDAYS[day.weekday()]
    same = [r for r in rows if r["weekday"] == weekday]
    last_close = hist["closes"][max(d for d in hist["closes"] if d <= today)] if hist["closes"] else None
    ref = me["open"] if me else last_close

    today_out = None
    if me:
        sw = me["swings"]
        today_out = {"open": round(me["open"], 2), "through": _clock([me["through"]]), "up": round(me["up"], 1),
                     "down": round(me["down"], 1), "now": round(me["now"], 1),
                     "path": [{"at": cp, "points": round(me["path"][cp], 1)} for cp in CHECKPOINTS if cp in me["path"]],
                     "swings": [{"dir": s["dir"], "points": round(s["points"], 1), "ends": _clock([s["ends"]]),
                                 "done": s["done"]} for s in sw]}
    return {
        "as_of": now.isoformat(timespec="seconds"), "session": day.isoformat(), "weekday": weekday,
        "expiry": is_expiry, "bars_source": source or "the archive", "swing_pct": SWING_PCT,
        "reference": {"level": round(ref, 2) if ref else None, "is": "today's open" if me else "the last close"},
        "profile": profile(same, ref), "all_days": profile(rows, ref),
        "expiry_profile": profile([r for r in rows if r["expiry"] and r["date"] >= WEEKLY_FROM], ref) if is_expiry else None,
        "today": today_out, "similar": similar(me, same) if me else None,
        "why": why(rows, ref), "indicators": indicators_tested(),
        "note": (f"Medians over every {weekday} since January 2015 ({len(same)} sessions), each measured in % of its "
                 f"own open and shown as points at today's level; a swing ends on a "
                 f"{SWING_PCT}% reversal. A description of past sessions, not a signal: the intraday rules that "
                 "tried to see these moves coming are listed with their verdicts."),
    }
