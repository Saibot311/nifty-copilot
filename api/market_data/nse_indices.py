"""NSE's daily all-index report: open, high, low and close for every NSE
index, published by the exchange each evening (ind_close_all_DDMMYYYY.csv).

It is the source of record for index levels. Two things need it: the Midcap
Select index, which Yahoo does not carry at all, and the forward log, which
must record each day's verdict that evening — and Yahoo is sometimes still
missing that day's close at 19:30 (21 Sep 2026 was lost that way).
"""

from dataclasses import dataclass
from datetime import date

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "*/*",
}

# NSE's names for the indices this project reads, keyed by option symbol.
INDEX_NAMES = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "MIDCPNIFTY": "Nifty Midcap Select"}


@dataclass
class IndexDay:
    index_name: str
    trade_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float


def url(day: date) -> str:
    return f"https://archives.nseindia.com/content/indices/ind_close_all_{day:%d%m%Y}.csv"


def _num(v: str) -> float | None:
    v = v.strip()
    return None if v in ("", "-") else float(v)


def parse(text: str, trade_date: str) -> list[IndexDay]:
    lines = text.splitlines()
    if not lines or not lines[0].startswith("Index Name"):
        return []
    header = [h.strip() for h in lines[0].split(",")]
    out = []
    for line in lines[1:]:
        row = dict(zip(header, line.split(",")))
        name = (row.get("Index Name") or "").strip()
        close = _num(row.get("Closing Index Value", "") or "")
        if not name or close is None:
            continue
        o, h, l_ = (_num(row.get(k, "") or "") for k in ("Open Index Value", "High Index Value", "Low Index Value"))
        out.append(IndexDay(name, trade_date, o, h, l_, close))
    return out


def fetch_day(day: date, timeout: int = 30) -> list[IndexDay] | None:
    """Every index on `day`, or None when NSE has no file (holiday, or not
    published yet)."""
    resp = requests.get(url(day), headers=_HEADERS, timeout=timeout)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    rows = parse(resp.text, day.isoformat())
    return rows or None
