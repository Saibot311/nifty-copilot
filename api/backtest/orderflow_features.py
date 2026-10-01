"""Order-flow features from the five-minute option snapshots, one row per
snapshot, for building rules that can only ever be tested forward.

The snapshots (storage/option_snapshots_db.py, from 1 Oct 2026) hold NSE's
option chain every five minutes of the session: bid and ask with their sizes,
open interest, implied volatility, for the two nearest expiries and the
nearest monthly, strikes within 5% of the index. No archive anywhere has this
for earlier dates, so nothing computed here has a past to be backtested on.

A "snapshot" is every row of ONE expiry sharing one `taken_at`: NSE stamps
each expiry's chain separately, a few seconds apart in the same run, so the
expiries are never mixed inside a feature. Features are computed for one
expiry at a time; the forward harness uses the one it trades (the nearest
expiry not expiring that day).

The features, for a snapshot at time t of a session (each is None when the
data it needs is missing — never a guess, never zero):

  expiry, days_to_expiry    the series the features are on, and calendar days
                            to its expiry (0 on its expiry day)
  spot, spot_chg_open_pct   NIFTY in the chain, and its change since the
                            session's first snapshot
  minutes_since_open        since 09:15
  open_at, open_ok          the first snapshot's time; since-open features
                            are None unless it was taken by OPEN_LATEST, so a
                            recorder that started late cannot pass 11:00 off
                            as the open
  atm_strike                the listed strike nearest spot (the lower on a tie)
  call_oi_near, put_oi_near total open interest on strikes within NEAR_PCT of
                            spot at t
  call_oi_chg_open,         the change in that total since the first snapshot,
  put_oi_chg_open           over the same strikes (those near spot at t that
                            the first snapshot also has)
  call_oi_chg_30m,          the same against the latest snapshot stamped at
  put_oi_chg_30m, ref_30m_at  least LOOKBACK_MIN before t, and no more than
                            LOOKBACK_MIN + LOOKBACK_SLACK_MIN before it
  pcr_oi, pcr_oi_chg_open   near put OI / near call OI, and its change since
                            the open over the same strikes
  oi_flow_open              (put OI change - call OI change) since the open,
                            as a share of the near OI both sides had then
  atm_call_imbalance,       (bid_qty - ask_qty) / (bid_qty + ask_qty) at the
  atm_put_imbalance         at-the-money strike: +1 all bids, -1 all offers
  near_call_imbalance,      the same, summing sizes over the BOOK_STRIKES
  near_put_imbalance        strikes either side of it as well (one strike's
                            top of book is a lot or two, and noisy)
  atm_call_iv, atm_put_iv,  NSE's implied volatility (percent) at the ATM
  atm_iv, atm_iv_chg_open   strike, their mean, and its change since the open
                            (each at its own time's ATM strike)
  vol_spread,               call IV - put IV averaged over the three strikes
  vol_spread_chg_open       nearest spot (Cremers & Weinbaum's measure), and
                            its change since the open. NSE computes both IVs
                            against spot, so the level carries the futures
                            basis; the change since the open mostly nets it out
  skew_1pct, skew_2pct,     IV of the put at the strike nearest spot x (1 - x%)
  skew_*_chg_open           minus IV of the call nearest spot x (1 + x%), and
                            its change since the open: positive when downside
                            protection is dearer
  max_call_build_strike,    the call strike whose OI rose most since the open
  max_call_build_oi,        (any saved strike), how much, and its distance
  max_call_build_dist_pts   from spot (strike - spot); None when none rose.
  (the same for puts)
  max_oi_strike,            the strike with the most call + put OI within
  max_oi_dist_pct           NEAR_PCT of spot, and (spot - strike) / spot in %
  atm_call_spread,          ask - bid at the ATM strike in index points, and
  atm_call_spread_pct,      as a % of the mid; None when either side is
  (the same for puts)       missing or the quote is crossed

No look-ahead: `features_at` is given the session's snapshots up to and
including t and nothing after, and `session_features` calls it on each
prefix. A test scrambles every later snapshot and requires every feature at
t to stay the same.
"""

import sqlite3
from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from pathlib import Path

SESSION_OPEN = time(9, 15)
OPEN_LATEST = time(9, 30)          # a first snapshot later than this is not "the open"
NEAR_PCT = 2.0                     # strikes within this % of spot are near the money
LOOKBACK_MIN, LOOKBACK_SLACK_MIN = 30, 10
BOOK_STRIKES = 2                   # ATM and this many strikes either side
SPREAD_STRIKES = 3                 # strikes averaged in the vol spread
SKEW_PCTS = (1.0, 2.0)


# --- reading -------------------------------------------------------------------------

def read_rows(db_path: Path | None = None, start: date | None = None, end: date | None = None) -> list[dict]:
    """Snapshot rows between two session dates (inclusive), read-only: the
    file is opened with mode=ro, so nothing here can add, change or delete a
    row in a database that cannot be rebuilt."""
    from storage.option_snapshots_db import DB_PATH
    path = Path(db_path or DB_PATH)
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        q, args = "SELECT * FROM snapshots WHERE 1=1", []
        if start:
            q, args = q + " AND taken_at >= ?", args + [start.isoformat()]
        if end:
            q, args = q + " AND taken_at < ?", args + [(end + timedelta(days=1)).isoformat()]
        return [dict(r) for r in conn.execute(q + " ORDER BY taken_at, expiry, strike, option_type", args)]
    finally:
        conn.close()


def by_session(rows: list[dict]) -> dict[date, list[dict]]:
    out: dict[date, list[dict]] = {}
    for r in rows:
        out.setdefault(date.fromisoformat(r["taken_at"][:10]), []).append(r)
    return out


def expiries_listed(rows: list[dict]) -> list[date]:
    return sorted({date.fromisoformat(r["expiry"]) for r in rows})


def traded_expiry(day: date, expiries: list[date]) -> date | None:
    """The pipeline's Phase 1 rule: the nearest expiry that does not expire that day."""
    later = [e for e in expiries if e > day]
    return min(later) if later else None


def snapshots(rows: list[dict], expiry: date | str) -> list[dict]:
    """One expiry's rows grouped into snapshots, oldest first:
    {"taken_at": datetime, "expiry": str, "spot": float, "quotes": {(strike, "CE"|"PE"): row}}."""
    exp = expiry.isoformat() if isinstance(expiry, date) else expiry
    grouped: dict[str, dict] = {}
    for r in rows:
        if r["expiry"] != exp:
            continue
        g = grouped.setdefault(r["taken_at"], {"taken_at": datetime.fromisoformat(r["taken_at"][:19]),
                                               "expiry": exp, "spot": None, "quotes": {}})
        if g["spot"] is None and r.get("spot"):
            g["spot"] = float(r["spot"])
        g["quotes"][(float(r["strike"]), r["option_type"])] = r
    return [grouped[k] for k in sorted(grouped) if grouped[k]["spot"]]


# --- small helpers -------------------------------------------------------------------

def _pos(x) -> float | None:
    """A price, size or IV NSE reported, or None: NSE writes 0 where there is none."""
    return float(x) if x is not None and x > 0 else None


def _strikes(snap: dict) -> list[float]:
    return sorted({k[0] for k in snap["quotes"]})


def _nearest(strikes: list[float], target: float) -> float | None:
    return min(strikes, key=lambda k: (abs(k - target), k)) if strikes else None


def _near(snap: dict) -> list[float]:
    lo, hi = snap["spot"] * (1 - NEAR_PCT / 100), snap["spot"] * (1 + NEAR_PCT / 100)
    return [k for k in _strikes(snap) if lo <= k <= hi]


def _oi(snap: dict, strike: float, kind: str) -> float | None:
    q = snap["quotes"].get((strike, kind))
    return None if q is None or q.get("oi") is None else float(q["oi"])


def _oi_sum(snap: dict, strikes: list[float], kind: str) -> float | None:
    vals = [_oi(snap, k, kind) for k in strikes]
    return None if not vals or any(v is None for v in vals) else sum(vals)


def _iv(snap: dict, strike: float, kind: str) -> float | None:
    q = snap["quotes"].get((strike, kind))
    return _pos(q.get("iv")) if q else None


def _imbalance(snap: dict, strikes: list[float], kind: str) -> float | None:
    bid = ask = 0.0
    for k in strikes:
        q = snap["quotes"].get((k, kind))
        if q:
            bid += float(q.get("bid_qty") or 0)
            ask += float(q.get("ask_qty") or 0)
    return round((bid - ask) / (bid + ask), 4) if bid + ask > 0 else None


def _spread(snap: dict, strike: float, kind: str) -> tuple[float | None, float | None]:
    q = snap["quotes"].get((strike, kind))
    bid, ask = (_pos(q.get("bid")), _pos(q.get("ask"))) if q else (None, None)
    if bid is None or ask is None or ask < bid:
        return None, None
    return round(ask - bid, 2), round((ask - bid) / ((ask + bid) / 2) * 100, 3)


def _diff(a, b, nd: int = 4):
    return None if a is None or b is None else round(a - b, nd)


def _atm(snap: dict) -> float | None:
    return _nearest(_strikes(snap), snap["spot"])


def _atm_iv(snap: dict) -> float | None:
    k = _atm(snap)
    vals = [v for v in (_iv(snap, k, "CE"), _iv(snap, k, "PE")) if v is not None] if k is not None else []
    return round(sum(vals) / len(vals), 4) if vals else None


def _vol_spread(snap: dict) -> float | None:
    near = sorted(_strikes(snap), key=lambda k: (abs(k - snap["spot"]), k))[:SPREAD_STRIKES]
    diffs = [c - p for c, p in ((_iv(snap, k, "CE"), _iv(snap, k, "PE")) for k in near)
             if c is not None and p is not None]
    return round(sum(diffs) / len(diffs), 4) if diffs else None


def _skew(snap: dict, pct: float) -> float | None:
    strikes = _strikes(snap)
    put_k = _nearest(strikes, snap["spot"] * (1 - pct / 100))
    call_k = _nearest(strikes, snap["spot"] * (1 + pct / 100))
    if put_k is None or call_k is None:
        return None
    return _diff(_iv(snap, put_k, "PE"), _iv(snap, call_k, "CE"))


def _max_build(first: dict, now: dict, kind: str) -> tuple[float | None, float | None]:
    best = None
    for k in _strikes(now):
        a, b = _oi(first, k, kind), _oi(now, k, kind)
        if a is None or b is None or b - a <= 0:
            continue
        if best is None or b - a > best[1] or (b - a == best[1] and k < best[0]):
            best = (k, b - a)
    return best if best else (None, None)


def _reference(snaps: list[dict], t: datetime) -> dict | None:
    """The latest snapshot at least LOOKBACK_MIN before t, if it is not too old."""
    stamps = [s["taken_at"] for s in snaps]
    i = bisect_right(stamps, t - timedelta(minutes=LOOKBACK_MIN)) - 1
    if i < 0 or snaps[i]["taken_at"] < t - timedelta(minutes=LOOKBACK_MIN + LOOKBACK_SLACK_MIN):
        return None
    return snaps[i]


# --- the features --------------------------------------------------------------------

def features_at(snaps: list[dict]) -> dict:
    """Every feature at the LAST snapshot in `snaps`, which must be one
    session's snapshots of one expiry, oldest first, up to and including t.
    Nothing else is read, so nothing later can leak in."""
    now, first = snaps[-1], snaps[0]
    t, spot = now["taken_at"], now["spot"]
    open_ok = first["taken_at"].time() <= OPEN_LATEST
    out: dict = {"taken_at": t.isoformat(), "expiry": now["expiry"],
                 "days_to_expiry": (date.fromisoformat(now["expiry"]) - t.date()).days, "spot": spot,
                 "minutes_since_open": round((t - datetime.combine(t.date(), SESSION_OPEN)).total_seconds() / 60, 2),
                 "open_at": first["taken_at"].isoformat(), "open_ok": open_ok,
                 "spot_chg_open_pct": round((spot / first["spot"] - 1) * 100, 4) if open_ok else None}
    atm = _atm(now)
    out["atm_strike"] = atm
    near = _near(now)
    out["call_oi_near"], out["put_oi_near"] = _oi_sum(now, near, "CE"), _oi_sum(now, near, "PE")
    out["pcr_oi"] = (round(out["put_oi_near"] / out["call_oi_near"], 4)
                     if out["put_oi_near"] is not None and out["call_oi_near"] else None)

    # since the open, over the strikes near spot now that the first snapshot also has
    both = [k for k in near if _oi(first, k, "CE") is not None and _oi(first, k, "PE") is not None
            and _oi(now, k, "CE") is not None and _oi(now, k, "PE") is not None]
    c0, p0 = _oi_sum(first, both, "CE"), _oi_sum(first, both, "PE")
    c1, p1 = _oi_sum(now, both, "CE"), _oi_sum(now, both, "PE")
    ok = open_ok and None not in (c0, p0, c1, p1)
    out["call_oi_chg_open"] = c1 - c0 if ok else None
    out["put_oi_chg_open"] = p1 - p0 if ok else None
    out["pcr_oi_chg_open"] = round(p1 / c1 - p0 / c0, 4) if ok and c0 and c1 else None
    out["oi_flow_open"] = round(((p1 - p0) - (c1 - c0)) / (c0 + p0), 6) if ok and c0 + p0 > 0 else None

    ref = _reference(snaps, t)
    out["ref_30m_at"] = ref["taken_at"].isoformat() if ref else None
    if ref is not None:
        both30 = [k for k in near if all(_oi(s, k, kind) is not None for s in (ref, now) for kind in ("CE", "PE"))]
        out["call_oi_chg_30m"] = _diff(_oi_sum(now, both30, "CE"), _oi_sum(ref, both30, "CE"))
        out["put_oi_chg_30m"] = _diff(_oi_sum(now, both30, "PE"), _oi_sum(ref, both30, "PE"))
    else:
        out["call_oi_chg_30m"] = out["put_oi_chg_30m"] = None

    strikes = _strikes(now)
    if atm is not None:
        i = strikes.index(atm)
        book = strikes[max(0, i - BOOK_STRIKES):i + BOOK_STRIKES + 1]
    else:
        book = []
    for kind, name in (("CE", "call"), ("PE", "put")):
        out[f"atm_{name}_imbalance"] = _imbalance(now, [atm], kind) if atm is not None else None
        out[f"near_{name}_imbalance"] = _imbalance(now, book, kind) if book else None
        out[f"atm_{name}_iv"] = _iv(now, atm, kind) if atm is not None else None
        sp = _spread(now, atm, kind) if atm is not None else (None, None)
        out[f"atm_{name}_spread"], out[f"atm_{name}_spread_pct"] = sp

    out["atm_iv"] = _atm_iv(now)
    out["atm_iv_chg_open"] = _diff(out["atm_iv"], _atm_iv(first)) if open_ok else None
    out["vol_spread"] = _vol_spread(now)
    out["vol_spread_chg_open"] = _diff(out["vol_spread"], _vol_spread(first)) if open_ok else None
    for pct in SKEW_PCTS:
        key = f"skew_{pct:g}pct"
        out[key] = _skew(now, pct)
        out[f"{key}_chg_open"] = _diff(out[key], _skew(first, pct)) if open_ok else None

    for kind, name in (("CE", "call"), ("PE", "put")):
        k, build = _max_build(first, now, kind) if open_ok else (None, None)
        out[f"max_{name}_build_strike"], out[f"max_{name}_build_oi"] = k, build
        out[f"max_{name}_build_dist_pts"] = round(k - spot, 2) if k is not None else None

    totals = {k: _oi(now, k, "CE") + _oi(now, k, "PE") for k in near
              if _oi(now, k, "CE") is not None and _oi(now, k, "PE") is not None}
    k_max = max(sorted(totals), key=lambda k: totals[k]) if totals else None
    out["max_oi_strike"] = k_max
    out["max_oi_dist_pct"] = round((spot - k_max) / spot * 100, 4) if k_max is not None else None
    return out


def session_features(snaps: list[dict]) -> list[dict]:
    """Features at every snapshot of one session and expiry, each from the
    snapshots up to it."""
    return [features_at(snaps[:k + 1]) for k in range(len(snaps))]
