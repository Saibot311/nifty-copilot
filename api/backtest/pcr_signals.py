"""Put-Call Ratio as a contrarian sentiment signal, computed from the real
historical open interest in the local NSE options archive — not
approximated, since Phase 7-8's bhavcopy backfill means we actually have
this.

Direction convention, and an honest note on confidence: sources agree
PCR < 0.5 (call-heavy, complacent) marking a bearish capitulation that
gets bought is the least ambiguous reading — that side is implemented
with reasonable confidence. The high-PCR side is implemented as the
mirror (fade an extreme put-heavy reading, expect a move down) because
that is the standard contrarian convention, but explainer sources were
genuinely inconsistent on this side when researched. Treat the PUT side
of this pair as lower-confidence than the CALL side until its own
backtest numbers say otherwise — that asymmetry is a property of the
sources, not something to paper over.
"""

import pandas as pd

from storage import connect

LOW_PCR_THRESHOLD = 0.5   # call-heavy complacency -> contrarian CALL (higher confidence)
HIGH_PCR_THRESHOLD = 1.5  # put-heavy fear -> contrarian PUT (lower confidence, see module docstring)


def daily_pcr_series(symbol: str = "NIFTY") -> pd.Series:
    """One PCR value per trading day: total put OI / total call OI, summed
    across every strike of the NEAREST expiry on file that day (the
    front-month contract is where OI concentrates and is what most PCR
    commentary actually means)."""
    with connect() as conn:
        rows = conn.execute(
            """
            WITH nearest AS (
                SELECT trade_date, MIN(expiry_date) AS expiry_date
                FROM option_bars
                WHERE expiry_date >= trade_date
                GROUP BY trade_date
            )
            SELECT o.trade_date,
                   SUM(CASE WHEN o.option_type = 'PE' THEN o.open_interest ELSE 0 END) AS put_oi,
                   SUM(CASE WHEN o.option_type = 'CE' THEN o.open_interest ELSE 0 END) AS call_oi
            FROM option_bars o
            JOIN nearest n ON o.trade_date = n.trade_date AND o.expiry_date = n.expiry_date
            GROUP BY o.trade_date
            ORDER BY o.trade_date
            """
        ).fetchall()

    if not rows:
        return pd.Series(dtype=float)

    idx = [r["trade_date"] for r in rows]
    pcr = [
        (r["put_oi"] / r["call_oi"]) if r["call_oi"] else None
        for r in rows
    ]
    return pd.Series(pcr, index=idx).dropna()


def align_pcr_to_df(df: pd.DataFrame, pcr: pd.Series) -> pd.Series:
    """Aligns the options-archive PCR series (indexed by date string) onto
    the daily price df's index. Days the archive hasn't been backfilled to
    yet come back NaN, which the signal functions treat as 'no reading',
    not zero."""
    trading_days = [str(d.date()) for d in df.index]
    return pd.Series(pcr.reindex(trading_days).values, index=df.index)


def pcr_capitulation_call_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    pcr = align_pcr_to_df(df, daily_pcr_series())
    was_below = (pcr.shift(1) < LOW_PCR_THRESHOLD).fillna(False)
    still_below = (pcr < LOW_PCR_THRESHOLD).fillna(False)
    just_entered = was_below & ~(pcr.shift(2) < LOW_PCR_THRESHOLD).fillna(False)
    return (just_entered & still_below).fillna(False)


def pcr_exhaustion_put_signals(df: pd.DataFrame, regime_series: pd.Series) -> pd.Series:
    pcr = align_pcr_to_df(df, daily_pcr_series())
    was_above = (pcr.shift(1) > HIGH_PCR_THRESHOLD).fillna(False)
    still_above = (pcr > HIGH_PCR_THRESHOLD).fillna(False)
    just_entered = was_above & ~(pcr.shift(2) > HIGH_PCR_THRESHOLD).fillna(False)
    return (just_entered & still_above).fillna(False)


PCR_STRATEGY_REGISTRY = {
    "pcr_capitulation_call": {
        "fn": pcr_capitulation_call_signals, "params": {},
        "direction": "long", "option_type": "CE",
        "label": "PCR Capitulation (<0.5, contrarian call)",
    },
    "pcr_exhaustion_put": {
        "fn": pcr_exhaustion_put_signals, "params": {},
        "direction": "short", "option_type": "PE",
        "label": "PCR Exhaustion (>1.5, contrarian put)",
    },
}
