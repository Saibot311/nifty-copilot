"""Records each day's recommendation once its daily bar is final, and
scores past entries against what the index actually did afterwards.

Outcomes follow the backtester's execution rule (I1): decided at the
as_of close, entered at the next session's open, measured to the close h
sessions later. Returns are gross (before costs) — the cost model lives
in the backtester and these are for tracking, not P&L.
"""

from datetime import date, datetime, time

import pandas as pd

from backtest.strategies import load_daily_data
from market_data.kite_session import IST
from storage.forward_log_db import all_recommendations, record_recommendation

HORIZONS = (1, 5, 10)
DIRECTION = {"CONSIDER_CALL": 1, "CONSIDER_PUT": -1}  # the actions build_recommendation emits
MARKET_CLOSE = time(15, 30)


def bar_is_final(as_of: date, now: datetime) -> bool:
    return as_of < now.date() or now.time() >= MARKET_CLOSE


def record_if_final(rec: dict, symbol: str = "^NSEI", now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    as_of = date.fromisoformat(rec["as_of"])
    if not bar_is_final(as_of, now):
        return False
    df, _ = load_daily_data(symbol, 400)
    close = float(df.loc[df.index.date == as_of, "close"].iloc[0])
    return record_recommendation(rec, close)


def score(rows: list[dict], df: pd.DataFrame) -> list[dict]:
    dates = [d.isoformat() for d in df.index.date]
    scored = []
    for row in rows:
        out = {**row, "outcomes": {}}
        if row["as_of"] in dates:
            i = dates.index(row["as_of"])
            if i + 1 < len(df):
                entry = float(df["open"].iloc[i + 1])
                out["entry_date"], out["entry_open"] = dates[i + 1], entry
                sign = DIRECTION.get(row["action"])
                for h in HORIZONS:
                    if i + h < len(df):
                        move = (float(df["close"].iloc[i + h]) / entry - 1) * 100
                        out["outcomes"][f"{h}d"] = {
                            "index_move_pct": round(move, 3),
                            "trade_return_pct": round(sign * move, 3) if sign else None,
                        }
        scored.append(out)
    return scored


def forward_report(symbol: str = "^NSEI") -> dict:
    rows = all_recommendations()
    df, _ = load_daily_data(symbol, 400)
    scored = score(rows, df)

    trades = [r for r in scored if r["action"] in DIRECTION and "10d" in r["outcomes"]]
    rets = [r["outcomes"]["10d"]["trade_return_pct"] for r in trades]
    first = min((r["as_of"] for r in rows), default=None)
    return {
        "entries": scored,
        "summary": {
            "days_logged": len(rows),
            "logging_since": first,
            "by_action": {a: sum(1 for r in rows if r["action"] == a) for a in (*DIRECTION, "NO_TRADE")},
            "completed_trades_10d": len(trades),
            "hit_rate_10d": round(sum(1 for x in rets if x > 0) / len(rets), 3) if rets else None,
            "avg_return_10d_pct": round(sum(rets) / len(rets), 3) if rets else None,
        },
        "note": (
            "Every row was written before its outcome existed and is never edited or backfilled — "
            "this is out-of-sample by construction. Returns are gross, entered at the next open. "
            "Expect weeks of NO_TRADE and a small sample for a long time; that's what honest forward "
            "evidence looks like."
        ),
    }
