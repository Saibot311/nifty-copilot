"""Downloads and parses NSE's official F&O bhavcopy — the exchange's own
published daily report, not a scrape of anyone's website.

Two formats exist and both are handled:
  - Legacy (through 2024-07-05): INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,...
  - Current (from 2024-07-08):   TradDt,...,TckrSymb,XpryDt,StrkPric,...

One file per trading day contains every strike and expiry, so backfilling
history costs ~1 request per day rather than one per contract. NSE's
archive server rejects bare requests, so a browser-ish User-Agent and
Referer are required — that's not evasion, it's what their static file
host expects.
"""

import io
import zipfile
from dataclasses import dataclass
from datetime import date

import requests

FORMAT_CHANGE_DATE = date(2024, 7, 8)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "*/*",
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


@dataclass
class OptionBar:
    trade_date: str
    expiry_date: str
    strike: float
    option_type: str  # CE | PE
    open: float
    high: float
    low: float
    close: float
    settle_price: float
    contracts: float
    open_interest: float
    change_in_oi: float


def bhavcopy_url(day: date) -> str:
    if day >= FORMAT_CHANGE_DATE:
        return (
            "https://archives.nseindia.com/content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
        )
    mon = _MONTHS[day.month - 1]
    return (
        "https://archives.nseindia.com/content/historical/DERIVATIVES/"
        f"{day.year}/{mon}/fo{day:%d}{mon}{day.year}bhav.csv.zip"
    )


def _parse_legacy_date(value: str) -> str:
    """'28-Jan-2021' or '04-JAN-2021' -> '2021-01-28'."""
    dd, mon, yyyy = value.strip().split("-")
    return f"{yyyy}-{_MONTHS.index(mon.upper()) + 1:02d}-{int(dd):02d}"


def fetch_option_bars(day: date, symbol: str = "NIFTY", timeout: int = 30) -> list[OptionBar]:
    """Returns every option contract row for `symbol` on `day`.

    An empty list means no trading that day (weekend/holiday) — NSE returns
    404 for those, which is expected and not an error worth raising.
    """
    return fetch_option_bars_multi(day, (symbol,), timeout).get(symbol, [])


def fetch_option_bars_multi(day: date, symbols: tuple[str, ...], timeout: int = 30) -> dict[str, list[OptionBar]]:
    """One download, several underlyings: NSE's file for a day holds every
    index and stock option, so BANKNIFTY and MIDCPNIFTY cost no extra
    requests. An empty dict means no file for that day (404)."""
    resp = requests.get(bhavcopy_url(day), headers=_HEADERS, timeout=timeout)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8", errors="replace")
    return parse_option_bars(text, symbols)


def parse_option_bars(text: str, symbols: tuple[str, ...]) -> dict[str, list[OptionBar]]:
    """Index option rows for each symbol, from either NSE format or BSE's
    (which uses the same UDiFF columns as NSE's current one)."""
    lines = text.splitlines()
    out: dict[str, list[OptionBar]] = {s: [] for s in symbols}
    if not lines:
        return out

    header = [h.strip() for h in lines[0].split(",")]
    legacy = "INSTRUMENT" in header

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < len(header):
            continue
        row = dict(zip(header, parts))

        if legacy:
            sym = row.get("SYMBOL", "").strip()
            if sym not in out:
                continue
            if row.get("INSTRUMENT", "").strip() != "OPTIDX":
                continue
            opt_type = row.get("OPTION_TYP", "").strip()
            if opt_type not in ("CE", "PE"):
                continue
            out[sym].append(OptionBar(
                trade_date=_parse_legacy_date(row["TIMESTAMP"]),
                expiry_date=_parse_legacy_date(row["EXPIRY_DT"]),
                strike=float(row["STRIKE_PR"]),
                option_type=opt_type,
                open=float(row["OPEN"]), high=float(row["HIGH"]),
                low=float(row["LOW"]), close=float(row["CLOSE"]),
                settle_price=float(row["SETTLE_PR"]),
                contracts=float(row["CONTRACTS"] or 0),
                open_interest=float(row["OPEN_INT"] or 0),
                change_in_oi=float(row["CHG_IN_OI"] or 0),
            ))
        else:
            sym = row.get("TckrSymb", "").strip()
            if sym not in out:
                continue
            opt_type = row.get("OptnTp", "").strip()
            if opt_type not in ("CE", "PE"):
                continue
            out[sym].append(OptionBar(
                trade_date=row["TradDt"].strip(),
                expiry_date=row["XpryDt"].strip(),
                strike=float(row["StrkPric"]),
                option_type=opt_type,
                open=float(row["OpnPric"] or 0), high=float(row["HghPric"] or 0),
                low=float(row["LwPric"] or 0), close=float(row["ClsPric"] or 0),
                settle_price=float(row["SttlmPric"] or 0),
                contracts=float(row["TtlTradgVol"] or 0),
                open_interest=float(row["OpnIntrst"] or 0),
                change_in_oi=float(row["ChngInOpnIntrst"] or 0),
            ))

    return out


# --- BSE (SENSEX) ------------------------------------------------------------
# BSE publishes the same UDiFF layout. Its archive has these files from
# January 2024; earlier dates return an HTML page, not a CSV. SENSEX options
# were relaunched in May 2023 and were thinly traded before, so this loses
# little — but SENSEX can only ever add evidence to the 2024+ holdout.

_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "*/*",
}


def bse_bhavcopy_url(day: date) -> str:
    return ("https://www.bseindia.com/download/Bhavcopy/Derivative/"
            f"BhavCopy_BSE_FO_0_0_0_{day:%Y%m%d}_F_0000.CSV")


def fetch_bse_option_bars(day: date, symbol: str = "SENSEX", timeout: int = 30) -> list[OptionBar] | None:
    """SENSEX option rows for `day`. None when BSE has no CSV for the day
    (holiday, not yet published, or before its archive begins)."""
    resp = requests.get(bse_bhavcopy_url(day), headers=_BSE_HEADERS, timeout=timeout)
    if resp.status_code == 404 or not resp.text.startswith("TradDt"):
        return None
    resp.raise_for_status()
    return parse_option_bars(resp.text, (symbol,))[symbol]
