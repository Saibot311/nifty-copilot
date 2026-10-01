"""NSE's trading holidays for the F&O segment, from NSE's own published list
(the same public site the option chain comes from), kept for a day.

Weekends are not in it; a session is a weekday that is not listed. When NSE
cannot be reached the list is empty and `known` says so: every weekday then
counts as a session, which a holiday would make one day wrong.
"""

from datetime import date, datetime, timedelta


def _fetch() -> set[date]:
    from market_data.live_quote import _session
    data = _session().holiday_list() or {}
    rows = data.get("FO") or data.get("CM") or []
    return {datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows if r.get("tradingDate")}


def trading_holidays() -> tuple[set[date], bool]:
    """(holidays, known)."""
    from cache import cached
    try:
        return cached("nse_trading_holidays", ttl_seconds=24 * 3600, producer=_fetch, stale_ok=True), True
    except Exception:
        return set(), False


def is_session(d: date, holidays: set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def sessions_after(d: date, n: int, holidays: set[date]) -> list[date]:
    """The next `n` sessions strictly after `d`."""
    out, day = [], d
    while len(out) < n:
        day += timedelta(days=1)
        if is_session(day, holidays):
            out.append(day)
    return out
