"""Is every card's data as current as the market clock says it should be?

Before this, nothing checked. On 5-6 Oct 2026 the Kite login lapsed and the
day-ahead forecast, the IV series, the paper book and the Market tab's option
prices all stopped at 1 Oct, while the web server ran a build replaced under
it and open tabs stopped refreshing — and the dashboard said nothing.

Each source the dashboard reads has a rule, by kind:

  live     during a session its time may lag the clock by `max_age_min`;
           outside one it must show the last closed session
  close    it must include the last closed session once the nightly job has
           had its chance (SETTLE_BY that evening)
  nightly  research recomputed after that close, on the same clock
  self     the source reports its own staleness (the day-ahead forecast)
  manual   an on-demand study: its age is shown, it is never called behind

scripts/freshness_check.py fetches every source the way the dashboard does,
judges it here, writes data/freshness.json for /api/freshness and the page,
and runs the step that fixes a source behind for a known reason — never while
the nightly job is running.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from market_data.kite_session import IST

OPEN, CLOSE = time(9, 15), time(15, 30)
SETTLE_BY = time(23, 0)          # the nightly job has normally finished by now
RETRY_GAP = timedelta(hours=2)   # a fix is tried at most this often
NOT_IN_SESSION = {"paper"}       # fixes that write the paper book wait for the close


@dataclass(frozen=True)
class Source:
    key: str
    card: str
    path: str
    kind: str                      # live | close | nightly | self | manual
    fields: tuple[str, ...]        # dotted paths to its time; the first present is used
    max_age_min: int = 10
    fix: tuple[str, ...] = field(default=())   # named steps (scripts/freshness_check.FIXES), in order


SOURCES = (
    Source("tick", "Header price", "/api/live/tick", "live", ("as_of",), 3),
    Source("live", "Header price", "/api/live", "live", ("market_time", "fetched_at"), 5),
    Source("indicators", "Indicators", "/api/indicators", "live", ("as_of",), 10),
    Source("live_patterns", "Patterns in play", "/api/live/patterns", "live", ("as_of",), 10),
    Source("intraday", "Intraday rules", "/api/intraday", "live", ("as_of",), 10),
    Source("weekday_profile", "Where NIFTY stands", "/api/weekday_profile", "live", ("as_of",), 15),
    Source("indices", "Indices", "/api/indices", "live", ("as_of",), 10),
    Source("option_chain", "Option chain", "/api/options/chain/contracts", "live", ("as_of",), 10),
    Source("option_moves", "Option moves", "/api/options/moves", "live", ("as_of",), 15),
    Source("news", "News", "/api/news", "live", ("as_of",), 30),
    Source("strategy_fit", "Strategy fit", "/api/strategy_fit", "live", ("as_of",), 30),
    Source("recommendation", "Today's call", "/api/recommendation", "close", ("as_of",), fix=("kite_bars",)),
    Source("chart", "Today chart", "/api/chart", "close", ("as_of",), fix=("kite_bars",)),
    Source("briefing", "Briefing", "/api/briefing", "close", ("as_of",), fix=("kite_bars",)),
    Source("patterns_today", "Patterns", "/api/patterns/today", "close", ("as_of",), fix=("kite_bars",)),
    Source("similarity", "Days like this one", "/api/similarity", "close", ("as_of",), fix=("kite_bars",)),
    Source("forward_log", "Forward track record", "/api/forward_log", "close", ("entries.0.as_of",)),
    Source("iv", "Implied volatility", "/api/iv", "close", ("latest.date",), fix=("options", "iv")),
    Source("market_option_prices", "Market: option prices", "/api/market", "close",
           ("today.options_price_now.date",), fix=("options", "iv", "market")),
    Source("paper", "Paper book", "/api/paper", "close", ("last_decision.entry_session",), fix=("options", "paper")),
    Source("day_forecast", "The next session", "/api/day_forecast", "self", ("status.stale",),
           fix=("kite_bars", "options", "iv", "forecast")),
    Source("breakouts", "Breakout levels", "/api/breakouts", "live", ("as_of",), 10),
    Source("breakout_record", "Breakout record", "/api/breakouts", "nightly", ("record.computed_at",),
           fix=("breakouts",)),
    Source("pattern_options", "Pattern research", "/api/patterns/options", "nightly", ("computed_at",),
           fix=("research",)),
    Source("structural", "Structural research", "/api/structural", "nightly", ("computed_at",), fix=("research",)),
    Source("replication", "Replication", "/api/replication", "nightly", ("computed_at",), fix=("research",)),
    Source("news_research", "News research", "/api/news/research", "nightly", ("computed_at",)),
    Source("course_research", "Course strategies", "/api/course_research", "manual", ("computed_at",)),
    Source("nifty_pipeline", "NIFTY strategy pipeline", "/api/nifty_pipeline", "manual", ("computed_at",)),
)


def _is_session(d: date, holidays: set) -> bool:
    return d.weekday() < 5 and d not in holidays


def _previous_session(d: date, holidays: set) -> date:
    d -= timedelta(days=1)
    while not _is_session(d, holidays):
        d -= timedelta(days=1)
    return d


def market_clock(now: datetime, holidays: set) -> dict:
    """Where the market stands: in a session or not, the last session to have
    closed, and the last close the nightly job should have processed."""
    today = now.date()
    in_session = _is_session(today, holidays) and OPEN <= now.time() < CLOSE
    latest = today if _is_session(today, holidays) and now.time() >= CLOSE else _previous_session(today, holidays)
    settled = latest if (now.date() > latest or now.time() >= SETTLE_BY) else _previous_session(latest, holidays)
    return {"in_session": in_session, "latest_closed": latest, "settled_close": settled}


_NSE = re.compile(r"^(\d{2}-[A-Za-z]{3}-\d{4})(?: (\d{2}:\d{2}(?::\d{2})?))?$")


def parse_time(raw) -> datetime | None:
    """Any timestamp the endpoints use, as IST. A bare date (or midnight) is
    that session's close, since that is what a daily figure describes."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    m = _NSE.match(s)
    if m:
        d = datetime.strptime(m.group(1), "%d-%b-%Y")
        if not m.group(2):
            return datetime.combine(d.date(), CLOSE, tzinfo=IST)
        fmt = "%H:%M:%S" if m.group(2).count(":") == 2 else "%H:%M"
        t = datetime.strptime(m.group(2), fmt).time()
        return datetime.combine(d.date(), t, tzinfo=IST)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(s) == 10 or (dt.tzinfo is None and dt.time() == time(0, 0)):
        return datetime.combine(dt.date(), CLOSE, tzinfo=IST)
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def _dig(payload, path: str):
    cur = payload
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)] if part.isdigit() and int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _ago(minutes: float) -> str:
    return f"{minutes:.0f} min" if minutes < 120 else f"{minutes / 60:.1f} h" if minutes < 2880 else f"{minutes / 1440:.0f} days"


def judge(src: Source, payload, now: datetime, holidays: set) -> dict:
    """One source's verdict: current, behind, unavailable or on demand."""
    out = {"key": src.key, "card": src.card, "path": src.path, "kind": src.kind, "fix": list(src.fix)}
    if payload is None:
        return {**out, "status": "unavailable", "as_of": None, "reason": "the API did not answer for it"}
    if src.kind == "self":
        st = _dig(payload, "status") or {}
        if "stale" not in st:
            return {**out, "status": "unavailable", "as_of": None, "reason": "it reported no status"}
        return {**out, "status": "behind" if st["stale"] else "current", "as_of": st.get("due"),
                "reason": "; ".join(st.get("reasons") or []) if st["stale"] else ""}
    raw = next((v for v in (_dig(payload, f) for f in src.fields) if v not in (None, "")), None)
    when = parse_time(raw)
    if when is None:
        return {**out, "status": "unavailable", "as_of": None, "reason": f"no time in {', '.join(src.fields)}"}
    out["as_of"] = when.isoformat(timespec="minutes")
    if src.kind == "manual":
        return {**out, "status": "on demand", "reason": f"computed {_ago((now - when).total_seconds() / 60)} ago, when asked for"}
    clock = market_clock(now, holidays)
    if src.kind == "live":
        if clock["in_session"]:
            lag = (now - when).total_seconds() / 60
            ok = lag <= src.max_age_min
            return {**out, "status": "current" if ok else "behind",
                    "reason": "" if ok else f"{_ago(lag)} old in a session; at most {src.max_age_min} min expected"}
        need = clock["latest_closed"]
    else:
        need = clock["settled_close"]
    # Research must have been computed after that close; a daily figure must be from it.
    ok = when >= datetime.combine(need, CLOSE, tzinfo=IST) if src.kind == "nightly" else when.date() >= need
    reason = "" if ok else (f"shows {when.date().isoformat()}; the {need.isoformat()} close should be in by now"
                           if src.kind != "nightly" else
                           f"computed {when.date().isoformat()}, before the {need.isoformat()} close it should include")
    return {**out, "status": "current" if ok else "behind", "reason": reason}


def evaluate(payloads: dict, now: datetime, holidays: set) -> dict:
    """Every source judged; counts for the page's status line."""
    rows = [judge(s, payloads.get(s.path), now, holidays) for s in SOURCES]
    count = lambda st: sum(1 for r in rows if r["status"] == st)  # noqa: E731
    return {"checked_at": now.isoformat(timespec="seconds"), "sources": rows, "current": count("current"),
            "behind": count("behind"), "unavailable": count("unavailable"), "on_demand": count("on demand"),
            "clock": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in market_clock(now, holidays).items()}}


def may_fix(fix: str, now: datetime, job_running: bool, last_tried: datetime | None) -> bool:
    """A fix runs outside the nightly job, at most every RETRY_GAP, and one
    that writes the paper book never during market hours."""
    if job_running:
        return False
    if last_tried and now - last_tried < RETRY_GAP:
        return False
    if fix in NOT_IN_SESSION and now.weekday() < 5 and time(9, 0) <= now.time() < time(15, 45):
        return False
    return True


RESTART_GRACE = timedelta(minutes=2)   # ps gives whole seconds; a landing writes and restarts within one


def service_behind(process_started: datetime, newest_on_disk: datetime) -> bool:
    """A service started before its code or build last changed is running old code."""
    return newest_on_disk > process_started + RESTART_GRACE


def restart_now(now: datetime, holidays: set) -> bool:
    """Services restart outside market hours; during a session the watchdog only says so."""
    return not (_is_session(now.date(), holidays) and time(9, 10) <= now.time() < time(15, 35))


# Data first, then what is computed from it; the paper book last, after the
# options archive has the entry session's prices.
FIX_ORDER = ("kite_bars", "options", "iv", "research", "market", "forecast", "breakouts", "paper")


def plan_fixes(evaluation: dict) -> list[str]:
    """The named fixes the behind sources call for, each once, in FIX_ORDER."""
    wanted = {f for s in evaluation["sources"] if s["status"] == "behind" for f in s.get("fix", [])}
    return [f for f in FIX_ORDER if f in wanted]
