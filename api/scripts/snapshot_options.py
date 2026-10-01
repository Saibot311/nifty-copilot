"""Records NIFTY's option chain every five minutes of the session.

    cd api && .venv/bin/python scripts/snapshot_options.py

The LaunchAgent com.niftycopilot.snapshots runs this as each 5-minute bar
closes (:00, :05, ... and SETTLE_S seconds for the bar to be served; see
scripts/install_app_services.sh). Outside 09:15-15:35 IST on a weekday it
exits at once, asking nothing.

After saving, the same run follows the three intraday rules on the bar that
just closed and writes any entry or exit to the intraday forward record,
priced from the chain it has just saved (briefing/intraday_live.record). A
failure there is printed and never costs the snapshot.

Each run reads NSE's public chain (the one the Today tab's option chain
shows) for the two nearest expiries and the nearest monthly, and keeps the
strikes within 5% of the index. A chain is saved only if NSE's own timestamp
for it is today, inside the session: after the close, and on a holiday, NSE
keeps restamping the last session's chain (15:40 on 30 Sep 2026), and saving
those would record the close again as if it were new.
"""

import sys
import time as _time
from datetime import datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from market_data.kite_session import IST  # noqa: E402
from options.chain_table import build_chain_table  # noqa: E402
from storage import option_snapshots_db as db  # noqa: E402

OPEN, LAST_RUN, CLOSE = time(9, 15), time(15, 35), time(15, 30, 59)
WINDOW_PCT = 5.0
SETTLE_S = 20
# When the chain a rule needs is stamped before the rule's bar closed, ask
# again this many times, this far apart.
RETRIES, RETRY_GAP_S = 3, 30
NSE_DATE = "%d-%b-%Y"


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and OPEN <= now.time() <= LAST_RUN


def pick_expiries(expiries: list[str]) -> list[str]:
    """The two nearest, and the nearest monthly: the last expiry NSE lists in
    the first expiry's month."""
    dated = sorted((datetime.strptime(e, NSE_DATE).date(), e) for e in expiries)
    if not dated:
        return []
    month = dated[0][0].strftime("%Y-%m")
    monthly = max(d for d in dated if d[0].strftime("%Y-%m") == month)
    chosen = []
    for d in dated[:2] + [monthly]:
        if d[1] not in chosen:
            chosen.append(d[1])
    return chosen


def rows_from(table: dict, expiry_iso: str) -> list[dict]:
    spot = float(table["underlying_value"])
    taken_at = datetime.strptime(table["as_of"], f"{NSE_DATE} %H:%M:%S").isoformat()
    lo, hi = spot * (1 - WINDOW_PCT / 100), spot * (1 + WINDOW_PCT / 100)
    out = []
    for r in table["rows"]:
        if not lo <= r["strike"] <= hi:
            continue
        for kind, side in (("CE", r["call"]), ("PE", r["put"])):
            if side:
                out.append({"taken_at": taken_at, "expiry": expiry_iso, "strike": r["strike"], "option_type": kind,
                            "spot": spot, "ltp": side["ltp"], "bid": side["bid"], "ask": side["ask"],
                            "bid_qty": side["bid_qty"], "ask_qty": side["ask_qty"], "iv": side["iv"],
                            "oi": side["oi"], "volume": side["volume"]})
    return out


def main(now: datetime | None = None, nse=None) -> int:
    now = now or datetime.now(IST)
    if not in_session(now):
        return 0
    try:
        if nse is None:
            from market_data.live_quote import _session
            nse = _session()
        expiries = (nse.option_chain_contract_info("NIFTY") or {}).get("expiryDates") or []
        rows, stale = fetch(nse, now, expiries, pick_expiries(expiries))
        if not rows:
            db.log_run("closed", 0, "; ".join(stale) or "NSE listed no expiries")
            print(f"{now:%H:%M} nothing saved: {'; '.join(stale) or 'no expiries'}")
            return 0
        new = db.save(rows)
        db.log_run("saved", new, f"{len(rows)} rows seen")
        print(f"{now:%H:%M} {new} new of {len(rows)}")
        record_intraday(now, rows, lambda wanted: fetch(nse, now, expiries, wanted))
        return 0
    except Exception as e:  # noqa: BLE001 — a failed run is logged and retried in five minutes
        db.log_run("failed", 0, f"{type(e).__name__}: {e}")
        print(f"{now:%H:%M} FAILED — {type(e).__name__}: {e}")
        return 1


def fetch(nse, now: datetime, listed: list[str], wanted: list[str]) -> tuple[list[dict], list[str]]:
    """The chains for `wanted` (NSE's spelling) that NSE stamped today, in the session."""
    rows, stale = [], []
    for exp in wanted:
        table = build_chain_table(nse.index_option_chain("NIFTY", exp), exp, listed, now.date())
        stamped = datetime.strptime(table["as_of"], f"{NSE_DATE} %H:%M:%S")
        if stamped.date() != now.date() or not OPEN <= stamped.time() <= CLOSE:
            stale.append(f"{exp} stamped {table['as_of']}")
            continue
        rows += rows_from(table, datetime.strptime(exp, NSE_DATE).date().isoformat())
    return rows, stale


def record_intraday(now: datetime, rows: list[dict], refetch=None, sleep=_time.sleep) -> None:
    """The intraday record, priced only from a chain stamped after the rule's
    bar closed: when NSE is behind, the needed expiries are asked for again
    (and saved like any snapshot) a few times before giving up to the next run."""
    try:
        from briefing.intraday_live import record, state_now
        state = state_now(now)
        written, waiting = record(now, rows, state)
        for _ in range(RETRIES if refetch else 0):
            if not waiting:
                break
            sleep(RETRY_GAP_S)
            again, _stale = refetch([datetime.fromisoformat(e).strftime(NSE_DATE) for e in sorted(waiting)])
            if again:
                db.save(again)
                db.log_run("saved", len(again), "re-asked for a rule's price")
            more, waiting = record(now, again, state)
            written += more
        if written:
            print(f"{now:%H:%M} intraday record: {', '.join(written)}")
        if waiting:
            print(f"{now:%H:%M} intraday record: NSE's chain still behind for {', '.join(sorted(waiting))}")
    except Exception as e:  # noqa: BLE001 — the snapshot is saved either way
        print(f"{now:%H:%M} intraday record FAILED — {type(e).__name__}: {e}")


if __name__ == "__main__":
    # launchd starts this on the minute a bar closes; give the bar a moment to be served.
    wait = SETTLE_S - datetime.now(IST).second
    if 0 < wait <= SETTLE_S:
        _time.sleep(wait)
    sys.exit(main())
