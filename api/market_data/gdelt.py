"""Historical news tone from GDELT — the archive that makes a news backtest
possible at all.

No free source publishes dated Indian market *headlines* back to 2018, which
is why the headline archive in storage/news_db.py can only run forward. But
GDELT has monitored world news since 2015 and its Doc API returns a daily
average *tone* for a query, free and without a key, over any window back to
2017. Tested here: every month sampled from 2018 to 2026 returned a full
set of daily points, none of them empty.

Tone is GDELT's own measure — roughly, positive minus negative language
across every article matching the query that day, on a scale where 0 is
neutral and the everyday range is about -3 to +3. It is a property of the
*coverage*, not of the market.

Two things this is not, and the research has to respect both:

  * It is not a headline. A day's tone cannot be read back to the story that
    caused it, so nothing here can say "this event moved the market".
  * Much of a day's Indian market coverage is *about that day's move*.
    "Sensex sinks 800 points" is negative tone caused by the fall, not a
    cause of it. Tone on day D is therefore partly a mirror of day D's
    return, and using it to explain day D would be circular. The research
    only ever uses a completed day's tone to trade a *later* session, which
    is also the project's standing convention: a signal read off one close,
    entered at the next.

The query is frozen. Changing which words are searched after seeing a result
is the same sin as changing a pattern's parameters after seeing its return,
so a changed query is a new QUERY_SET with its own stored series, never an
edit of this one.
"""

import time
from datetime import date, timedelta

import requests

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

# --- frozen: do not edit. A different query is a new key below. -------------
QUERIES = {
    "india_equities_v1": '(nifty OR sensex OR "indian stock market") sourcecountry:india',
}
QUERY_SET = "india_equities_v1"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
TIMEOUT_S = 90
# GDELT answers 429 when pushed, and its cooldown is measured in minutes
# rather than seconds — a backfill that retried after 15s simply collected
# more 429s. These are one-off settings, chosen to be a polite guest rather
# than to finish quickly: a whole-history backfill is nine requests.
PAUSE_S = 60.0
RETRIES = 5
BACKOFF = 2.0


class GdeltUnavailable(RuntimeError):
    pass


def _stamp(d: date) -> str:
    return d.strftime("%Y%m%d%H%M%S")


def fetch_window(start: date, end: date, mode: str = "timelinetone",
                 query_set: str = QUERY_SET, pause: float = PAUSE_S) -> list[dict]:
    """Daily points for [start, end). Retries a 429 with a widening pause."""
    query = QUERIES[query_set]
    last = None
    for attempt in range(RETRIES):
        try:
            resp = requests.get(ENDPOINT, headers=_HEADERS, timeout=TIMEOUT_S, params={
                "query": query, "mode": mode, "format": "json",
                "startdatetime": _stamp(start), "enddatetime": _stamp(end)})
            if resp.status_code == 200 and resp.content[:1] in (b"{", b"["):
                timeline = resp.json().get("timeline") or []
                return timeline[0].get("data", []) if timeline else []
            last = f"HTTP {resp.status_code}"
        except Exception as e:
            last = type(e).__name__
        if attempt < RETRIES - 1:
            # Exponential, not linear: a 429 here means "come back in a few
            # minutes", and asking again in fifteen seconds earns another.
            time.sleep(pause * (BACKOFF ** attempt))
    raise GdeltUnavailable(f"GDELT did not answer for {start}..{end} ({last})")


def windows(first: date, last: date, months: int = 12):
    """Request boundaries.

    A year at a time, not a month: GDELT still returns one point per day for
    a twelve-month window — tested, 366 points for 2019 — and a month-by-month
    backfill of eight years is 105 requests, which earns an HTTP 429 after
    about three. Nine requests do not.
    """
    cur = date(first.year, first.month, 1)
    while cur <= last:
        y, m = divmod((cur.month - 1) + months, 12)
        nxt = date(cur.year + y, m + 1, 1)
        yield cur, min(nxt, last + timedelta(days=1))
        cur = nxt


def parse_points(points: list[dict]) -> list[tuple[str, float]]:
    """(UTC date, value). GDELT stamps a day as YYYYMMDDT000000Z."""
    out = []
    for p in points:
        raw, val = str(p.get("date", "")), p.get("value")
        if len(raw) < 8 or val is None:
            continue
        out.append((f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}", float(val)))
    return out
