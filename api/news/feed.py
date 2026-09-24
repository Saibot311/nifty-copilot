"""The news view: what is being reported, and when it arrived relative to
the session an option buyer can actually act in.

Three windows, because they mean different things to a buyer:

  pre_open    news since the last 15:30. The next open can act on it.
  live        news during 09:15-15:30. The session is already pricing it.
  post_close  what landed after the close — tomorrow's pre-open, really,
              which is why the archive files it against tomorrow.

The tone tally at the bottom counts how many market-moving headlines point
each way. It is a count of what is being *reported*, not a forecast and not
a signal. The backtestable part — GDELT's daily tone, 2018 onward — is
`backtest/news_research.py` (0 of 5, 2026-09-24); the headlines themselves
can only be studied forward, from this archive.
"""

from datetime import datetime, timedelta

from market_data.news import corporate_announcements, fetch_all
from storage import news_db
from storage.news_db import IST, CLOSE_T, OPEN_T

# Jev is a paid call per headline, so a page refresh judges only a few of the
# newest unjudged ones and the nightly job sweeps the rest. A judgment is
# stored once and never recomputed, so the steady-state cost is only whatever
# is genuinely new.
JUDGE_PER_REFRESH = 12
JUDGE_NIGHTLY = 120
# Above this, Jev thinks the headline is the kind of event that moves an
# index. Chosen to sit well clear of session recaps, which scored ~0.08.
MOVING_ABOVE = 0.5
# Both judgments have to agree. "Sensex, Nifty rebound in early trade" came
# back market_moving 0.71 with topic "noise" — which is Jev being right
# twice: it is about the index, and it is a recap of a move that has already
# happened rather than an event that might cause one. A recap counted as
# market-moving would put the session's own reflection in the tally.
NOT_AN_EVENT = "noise"


def phase_now(now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    t = now.timetz().replace(tzinfo=None)
    if t < OPEN_T:
        phase, says = "pre_open", "Before the open — this is what the session has to price in."
    elif t <= CLOSE_T:
        phase, says = "live", "Market open — the session is pricing this as it goes."
    else:
        phase, says = "post_close", "After the close — an option bought today cannot act on this until tomorrow."
    return {"phase": phase, "says": says, "as_of": now.isoformat(timespec="seconds"),
            "session_date": now.date().isoformat()}


def refresh(now: datetime | None = None, judge: int = JUDGE_PER_REFRESH,
            with_filings: bool = True) -> dict:
    """Pull every feed, archive what is new, judge a few of the newest.

    Archiving happens whether or not Jev is reachable: the archive is the
    thing that cannot be rebuilt later, and a judgment can always be added
    to a stored headline afterwards.
    """
    now = now or datetime.now(IST)
    got = fetch_all()
    items = list(got["items"])
    failed = dict(got["failed"])
    if with_filings:
        try:
            items.extend(corporate_announcements())
        except Exception as e:
            failed["nse_filings"] = type(e).__name__

    new = news_db.save_many(items, now=now)
    judged, judge_error = 0, None
    if judge:
        judged, judge_error = judge_pending(limit=judge, now=now)
    return {"fetched": len(items), "new": new, "judged": judged,
            "judge_error": judge_error, "failed": failed,
            "fetched_at": now.isoformat(timespec="seconds")}


def judge_pending(limit: int = JUDGE_PER_REFRESH, now: datetime | None = None) -> tuple[int, str | None]:
    """Sends the newest unjudged headlines to Jev. Returns (judged, error).

    Fails soft, like every other Jev call in this project: an unjudged
    headline is shown as unjudged. It is never defaulted to neutral, because
    "no opinion" and "judged to be nothing" are different facts.
    """
    from copilot import jev

    from .classify import QUESTION_SET, judge_one

    if not jev.available():
        return 0, "no TYPESAFE_API_KEY — headlines are archived but not judged"
    pending = news_db.unjudged(QUESTION_SET, limit=limit)
    done = 0
    for h in pending:
        try:
            verdict = judge_one(h["title"], h.get("summary"))
        except jev.JevUnavailable as e:
            return done, str(e)
        news_db.save_judgment(h["id"], QUESTION_SET, verdict, now=now)
        done += 1
    return done, None


def is_moving(r: dict) -> bool:
    """Both judgments must agree: likely to move an index, and not a recap."""
    return (r.get("market_moving") or 0) >= MOVING_ABOVE and r.get("topic") != NOT_AN_EVENT


def _tone(rows: list[dict]) -> dict:
    """How many market-moving headlines point each way.

    A count, not a score. Nothing is averaged into a single number, because
    a single number is what a reader would mistake for a signal.
    """
    moving = [r for r in rows if is_moving(r)]
    by_dir = {d: sum(1 for r in moving if r.get("direction") == d) for d in ("higher", "lower", "unclear")}
    topics: dict[str, int] = {}
    for r in moving:
        if r.get("topic"):
            topics[r["topic"]] = topics.get(r["topic"], 0) + 1
    return {
        "market_moving": len(moving),
        "of_total": len(rows),
        "pointing": by_dir,
        "topics": dict(sorted(topics.items(), key=lambda kv: -kv[1])),
        "unjudged": sum(1 for r in rows if r.get("market_moving") is None),
    }


def _window(rows: list[dict], limit: int) -> list[dict]:
    """Market-moving first, then the rest — but spread across publishers.

    Ranking on score alone filled the whole card with one desk: BusinessLine
    publishes most often, so its headlines were judged first and took every
    slot. Five sources were chosen so the reader sees more than one newsroom,
    and a sort that quietly undoes that is worse than not having them. So the
    strongest item from each source goes first, then the next from each, and
    so on — which keeps the best story at the top and still shows the spread.
    """
    ordered = sorted(rows, key=lambda r: (not is_moving(r),
                                          -(r.get("market_moving") or 0),
                                          r["first_seen"]))
    by_source: dict[str, list[dict]] = {}
    for r in ordered:
        by_source.setdefault(r["source"], []).append(r)

    out, rank = [], 0
    while len(out) < limit and any(len(v) > rank for v in by_source.values()):
        tier = [v[rank] for v in by_source.values() if len(v) > rank]
        tier.sort(key=lambda r: (not is_moving(r), -(r.get("market_moving") or 0), r["first_seen"]))
        out.extend(tier[: limit - len(out)])
        rank += 1
    return out


# A story first seen here more than this long after its publisher dated it is
# old copy the feed is still carrying (and this archive has just met), not
# today's news. It stays in the archive; it is not shown as new.
OLD_COPY_HOURS = 72


def _last_close_before(now: datetime) -> datetime:
    """The most recent weekday 15:30 before today — Friday's, on a Monday.
    It does not know NSE holidays; after one the window starts a day late."""
    d = now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return datetime.combine(d, CLOSE_T, tzinfo=IST)


def _is_old_copy(r: dict) -> bool:
    try:
        published = datetime.fromisoformat(r["published_at"])
        seen = datetime.fromisoformat(r["first_seen"])
    except (TypeError, ValueError, KeyError):
        return False  # undated or unparseable: shown, and its date says so
    if published.tzinfo is None:
        published = published.replace(tzinfo=IST)
    return (seen - published).total_seconds() > OLD_COPY_HOURS * 3600


def _panel(rows: list[dict], limit: int, label: str, means: str) -> dict:
    fresh = [r for r in rows if not _is_old_copy(r)]
    shown = [{**r, "moving": is_moving(r)} for r in _window(fresh, limit)]
    return {"label": label, "rows": shown, "tone": _tone(fresh), "means": means,
            "older_copy_hidden": len(rows) - len(fresh)}


def _study_line() -> str:
    """What the pre-registered news-tone study found, read from its output."""
    try:
        from backtest.news_research import load_news_research
        r = load_news_research()
    except Exception:
        r = None
    if not r:
        return "The pre-registered news-tone study has not been run on this machine yet."
    hs = r.get("hypotheses", [])
    approved = sum(1 for h in hs if h.get("status") == "APPROVED")
    return (f"The pre-registered study of GDELT's daily news tone, 2018 onward, found {approved} of {len(hs)} "
            "ideas worth anything to an option buyer (Research tab).")


def view(now: datetime | None = None, limit: int = 12) -> dict:
    """What the dashboard shows. Reads the archive; never invents a headline.

    Windows are cut by when this system first saw each headline, not by the
    calendar label stored beside it: that label files Friday evening under
    Saturday, so Monday's "before the open" used to miss the weekend."""
    now = now or datetime.now(IST)
    here = phase_now(now)
    today = now.date()
    open_t = datetime.combine(today, OPEN_T, tzinfo=IST)
    close_t = datetime.combine(today, CLOSE_T, tzinfo=IST)
    from .classify import QUESTION_SET
    pre = news_db.seen_between(_last_close_before(now), open_t)
    live = news_db.seen_between(open_t - timedelta(seconds=1), close_t + timedelta(seconds=1))
    post = news_db.seen_between(close_t, close_t + timedelta(days=1))
    windows = {
        "pre_open": _panel(pre, limit, "Before today's open", "News the session had to price in at 09:15."),
        "live": _panel(live, limit, "During the session",
                       "Arrived while the market was open; the session is pricing it as it goes."),
        "post_close": _panel(post, limit, "After the close — for tomorrow",
                             "An option bought today cannot act on this. It is tomorrow's open that can."),
    }
    return {
        **here,
        "windows": windows,
        "sources": {k: v for k, v in _sources().items()},
        "archive": {"headlines": news_db.count(), "sessions": news_db.sessions_archived(),
                    "question_set": QUESTION_SET},
        "judged_by": "TypeSafe Jev — a typed judgment per headline, not a text model's opinion",
        "note": ("What is being reported, and when it arrived. Jev reads each headline and says whether it is the "
                 "kind of event that moves an index and which way it would push — a description of the news, not a "
                 "forecast. The counts below are counts, not a score. " + _study_line() + " The headlines "
                 "themselves have no free dated archive, so whether they predict anything can only be measured "
                 "forward, from this archive, and it is too young to say."),
    }


def _sources() -> dict:
    from market_data.news import SOURCES

    out = {k: {"name": v["name"], "tier": v["tier"], "about": v["about"]} for k, v in SOURCES.items()}
    out["nse_filings"] = {"name": "NSE corporate filings", "tier": 1,
                          "about": "what companies told the exchange — the disclosure itself"}
    return out
