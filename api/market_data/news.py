"""Market news from a fixed list of trusted publishers.

What this is for: context. `market_engine/drivers.py` already answers "what
moved NIFTY today" the measurable way — a regression on the S&P, the rupee
and Brent, fitted only on earlier sessions. It says so bluntly: financial
news always has a reason for yesterday's move, supplied after the fact.

This does not replace that and does not argue with it. It answers a
different question — "what is being reported right now" — which is worth
seeing before the open and after the close, and which the attribution
cannot tell you because it only knows prices.

Nothing here is a signal. Whether any of it predicts anything is a separate,
pre-registered, forward-only study (`backtest/news_research.py`), and until
that study has enough sessions the honest answer is that nobody knows.

Sources are a closed list, chosen because each publishes a dated market or
policy feed and is accountable for what it prints. The list is deliberately
short: a wider net is mostly syndicated copies of the same wire story, which
would make one event look like ten. Moneycontrol's feeds were tested and
dropped — they stopped updating in April 2024, and a stale feed presented as
current news is exactly the kind of quiet lie this project tries not to tell.

RSS is parsed with the standard library rather than a feed package. The
format is simple enough that a dependency would buy nothing.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

IST = timezone(timedelta(hours=5, minutes=30))
TIMEOUT_S = 12

# tier 1 = a wire or the regulator itself: it reports the event.
# tier 2 = a market desk writing about the event.
# The tier is shown, never used to weight anything — a reader deciding how
# much to trust a headline is doing something the code must not do for them.
SOURCES = {
    "rbi": {
        "name": "RBI press releases",
        "url": "https://www.rbi.org.in/pressreleases_rss.xml",
        "tier": 1,
        "about": "policy, rates, liquidity — the regulator's own wire",
    },
    "et_markets": {
        "name": "Economic Times — Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "tier": 2,
        "about": "Indian equity market desk",
    },
    "bs_markets": {
        "name": "Business Standard — Markets",
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "tier": 2,
        "about": "Indian equity market desk",
    },
    "mint_markets": {
        "name": "Mint — Markets",
        "url": "https://www.livemint.com/rss/markets",
        "tier": 2,
        "about": "Indian equity market desk",
    },
    "bl_markets": {
        "name": "BusinessLine — Markets",
        "url": "https://www.thehindubusinessline.com/markets/feeder/default.rss",
        "tier": 2,
        "about": "Indian equity market desk",
    },
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml",
}

_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    """Feed summaries arrive with markup and entities in them."""
    if not text:
        return ""
    import html

    return _SPACE.sub(" ", _TAGS.sub(" ", html.unescape(text))).strip()


def _published(item: ET.Element) -> str | None:
    """The item's own timestamp in IST, or None.

    None rather than now(): a headline with no date is not a headline from
    this minute, and stamping it with one would put undated old copy at the
    top of a feed the reader is using to see what is new.
    """
    raw = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)  # Indian feeds that omit an offset mean IST
    return dt.astimezone(IST).isoformat(timespec="seconds")


def _norm_title(title: str) -> str:
    """For spotting the same wire story republished under a tweaked headline."""
    return _SPACE.sub(" ", re.sub(r"[^a-z0-9 ]", "", title.lower())).strip()


def fetch_source(key: str, timeout: int = TIMEOUT_S) -> list[dict]:
    """One feed's items. Raises — the caller decides what a dead feed means."""
    src = SOURCES[key]
    resp = requests.get(src["url"], headers=_HEADERS, timeout=timeout)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    out = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title"))
        if not title:
            continue
        out.append({
            "title": title,
            "summary": _clean(item.findtext("description"))[:400],
            "url": (item.findtext("link") or "").strip(),
            "published_at": _published(item),
            "source": key,
            "source_name": src["name"],
            "tier": src["tier"],
        })
    return out


def fetch_all(keys: list[str] | None = None, timeout: int = TIMEOUT_S) -> dict:
    """Every source, deduplicated, newest first.

    A source that fails is named in `failed` rather than dropped in silence:
    a short news list because two feeds were down looks identical to a quiet
    day, and those are not the same thing.
    """
    keys = keys or list(SOURCES)
    items, failed = [], {}
    for key in keys:
        try:
            items.extend(fetch_source(key, timeout))
        except Exception as e:
            failed[key] = f"{type(e).__name__}"

    seen_url, seen_title, unique = set(), set(), []
    for it in items:
        norm = _norm_title(it["title"])
        if (it["url"] and it["url"] in seen_url) or norm in seen_title:
            continue
        if it["url"]:
            seen_url.add(it["url"])
        seen_title.add(norm)
        unique.append(it)

    # Undated items sort last rather than being guessed into position.
    unique.sort(key=lambda i: (i["published_at"] is None, i["published_at"] or ""), reverse=True)
    unique.sort(key=lambda i: i["published_at"] is None)
    return {
        "items": unique,
        "failed": failed,
        "fetched_at": datetime.now(IST).isoformat(timespec="seconds"),
        "sources": {k: SOURCES[k] for k in keys},
    }


def corporate_announcements(limit: int = 20) -> list[dict]:
    """NSE's own filings wire — what companies told the exchange today.

    Tier 1 by construction: it is the disclosure, not a report of it.
    """
    # The shared session, not a new one. Building an NSELive per call is
    # what got this machine throttled by NSE in the first place — see the
    # note at the top of live_quote.py.
    from .live_quote import _session

    rows = _session().corporate_announcements()
    out = []
    for r in (rows or [])[:limit]:
        desc, name = _clean(r.get("desc")), _clean(r.get("sm_name"))
        if not (desc and name):
            continue
        out.append({
            "title": f"{name} — {desc}",
            "summary": _clean(r.get("attchmntText"))[:400],
            "url": (r.get("attchmntFile") or "").strip(),
            "published_at": (r.get("an_dt") or "").strip() or None,
            "source": "nse_filings",
            "source_name": "NSE corporate filings",
            "tier": 1,
        })
    return out
