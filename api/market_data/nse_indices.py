"""NSE's daily all-index report: open, high, low and close for every NSE
index, published by the exchange each evening (ind_close_all_DDMMYYYY.csv).

It is the source of record for index levels. Two things need it: the Midcap
Select index, which Yahoo does not carry at all, and the forward log, which
must record each day's verdict that evening — and Yahoo is sometimes still
missing that day's close at 19:30 (21 Sep 2026 was lost that way).
"""

import sqlite3

from storage.sqlite_open import open_db
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
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


# --- reading the archive back -------------------------------------------------

ARCHIVE_PATH = Path(__file__).parent.parent / "data" / "nse_indices.db"
# Yahoo symbol -> the index NSE reports daily.
YAHOO_TO_UNDERLYING = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY"}


def load_archive(underlying: str, db_path: Path | None = None) -> pd.DataFrame:
    """Daily bars for an option underlying, from the local archive. Days NSE
    reported with a close only have NaN open/high/low."""
    path = db_path or ARCHIVE_PATH
    if not path.exists():
        return pd.DataFrame()
    conn = open_db(path)
    try:
        df = pd.read_sql("SELECT trade_date, open, high, low, close FROM index_daily WHERE index_name = ? "
                         "ORDER BY trade_date", conn, params=(INDEX_NAMES[underlying],))
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()
    if df.empty:
        return df
    df.index = pd.to_datetime(df.pop("trade_date"))
    return df


def top_up(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Append any final sessions NSE has published that Yahoo has not.

    Yahoo is sometimes a day late with the close — it cost the forward log a
    day on 21 Sep 2026, and left the snapshot and the briefing showing an
    older session than the rest of the dashboard. Only sessions after the
    last one in `df` are added, so history stays a single source.
    """
    underlying = YAHOO_TO_UNDERLYING.get(symbol)
    if underlying is None or df.empty:
        return df
    try:
        nse = load_archive(underlying)
    except Exception:
        return df
    if nse.empty:
        return df
    last = df.index[-1].normalize()
    extra = nse[(nse.index > last) & nse[["open", "high", "low"]].notna().all(axis=1)]
    if extra.empty:
        return df
    for col in df.columns:
        if col not in extra.columns:
            extra = extra.assign(**{col: False if df[col].dtype == bool else 0.0})
    extra = extra[df.columns]
    extra.index = extra.index.astype(df.index.dtype)
    extra.index.name = df.index.name
    return pd.concat([df, extra])