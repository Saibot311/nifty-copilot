"""Why did NIFTY move today? A statistical attribution, not a story.

Financial news always has a reason for yesterday's move, supplied after the
fact. This does the measurable part instead. Three global prices are known
before India opens — the S&P 500, the rupee, Brent crude — and a regression
of NIFTY's daily return on them, fitted on the 250 sessions *before* the day
in question, says how much of today's move they account for. What they do
not account for is labelled unexplained: domestic news, flows, positioning,
or nothing at all.

Two alignment rules make this honest:
  * Each global factor is the last session that closed strictly before the
    Indian date. The US closes after India does, so the same-date S&P move
    had not happened yet when NIFTY traded — using it would be look-ahead,
    and would make global cues look far more explanatory than they are.
  * The betas for a day are fitted only on earlier days.

It is attribution by association. "The S&P accounts for +0.2%" means that
is what the fitted relationship implies, not that the S&P caused it.
"""

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from backtest.strategies import load_daily_data
from market_data import YFinanceProvider

FACTORS = {
    "sp500": ("^GSPC", "S&P 500 (previous US session)"),
    "usdinr": ("INR=X", "USD/INR (previous session; up = rupee weaker)"),
    "brent": ("BZ=F", "Brent crude (previous session)"),
}
WINDOW = 250          # one year of sessions to fit the betas on
MIN_WINDOW = 120


def _returns(ticker: str, start: date) -> pd.Series:
    c = YFinanceProvider().get_ohlc(ticker, "1d", start, date.today())
    s = pd.Series({pd.Timestamp(x.timestamp[:10]): x.close for x in c}).sort_index()
    return (s.pct_change() * 100).dropna()


def prior_session(factor: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """For each Indian date, the factor's return on the last session strictly
    before it. Strictly: a same-date US session had not closed yet."""
    f = factor.sort_index()
    idx = f.index.searchsorted(dates, side="left") - 1
    vals = [f.iloc[i] if i >= 0 else np.nan for i in idx]
    return pd.Series(vals, index=dates)


@dataclass
class Frame:
    nifty: pd.DataFrame      # open, close, return_pct, gap_pct, intraday_pct
    factors: pd.DataFrame    # one column per factor, aligned to NIFTY's dates


def load_frame(start: date = date(2015, 1, 1)) -> Frame:
    df, _ = load_daily_data("^NSEI", (date.today() - start).days)
    df.index = pd.DatetimeIndex([pd.Timestamp(i.date()) for i in df.index])
    n = pd.DataFrame(index=df.index)
    n["close"] = df["close"]
    n["return_pct"] = df["close"].pct_change() * 100
    n["gap_pct"] = (df["open"] / df["close"].shift(1) - 1) * 100
    n["intraday_pct"] = (df["close"] / df["open"] - 1) * 100
    f = pd.DataFrame({k: prior_session(_returns(t, start), n.index) for k, (t, _) in FACTORS.items()})
    return Frame(n.dropna(), f.reindex(n.dropna().index))


def _fit(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, float]:
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    resid = y - X1 @ beta
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
    return beta, r2


def attribute(frame: Frame, day: pd.Timestamp | None = None) -> dict:
    """Today's (or `day`'s) return split into the part the global factors
    account for and the part they do not, with betas from earlier days only."""
    data = frame.nifty.join(frame.factors).dropna()
    day = data.index[-1] if day is None else pd.Timestamp(day)
    if day not in data.index:
        return {"available": False, "reason": f"no complete data for {day.date()}"}
    past = data.loc[:day].iloc[:-1].tail(WINDOW)
    if len(past) < MIN_WINDOW:
        return {"available": False, "reason": "not enough history to fit the relationship"}
    cols = list(FACTORS)
    beta, r2 = _fit(past["return_pct"].to_numpy(), past[cols].to_numpy())
    row = data.loc[day]
    contrib = {k: float(beta[i + 1] * row[k]) for i, k in enumerate(cols)}
    explained = sum(contrib.values())
    return {
        "available": True,
        "date": str(day.date()),
        "nifty_return_pct": round(float(row["return_pct"]), 2),
        "gap_pct": round(float(row["gap_pct"]), 2),
        "intraday_pct": round(float(row["intraday_pct"]), 2),
        "factors": {k: {"label": FACTORS[k][1], "move_pct": round(float(row[k]), 2),
                        "beta": round(float(beta[i + 1]), 3), "contribution_pct": round(contrib[k], 2)}
                    for i, k in enumerate(cols)},
        "explained_by_global_pct": round(explained, 2),
        "unexplained_pct": round(float(row["return_pct"]) - explained, 2),
        "fit_r2_past_year": round(r2, 3),
        "fit_window": f"{past.index[0].date()} to {past.index[-1].date()}",
        "note": ("Attribution by association, fitted on the year before this day. Global cues are the last "
                 "sessions that closed before India opened. 'Unexplained' is everything else — domestic news, "
                 "flows, positioning — or noise."),
    }


def explanatory_power_by_year(frame: Frame) -> dict:
    """How much of NIFTY's daily movement global cues have accounted for,
    year by year — fitted within each year, so a description, not a forecast."""
    data = frame.nifty.join(frame.factors).dropna()
    out = {}
    for yr, g in data.groupby(data.index.year):
        if len(g) < 100:
            continue
        beta, r2 = _fit(g["return_pct"].to_numpy(), g[list(FACTORS)].to_numpy())
        out[str(yr)] = {"sessions": len(g), "r2": round(r2, 3),
                        "sp500_beta": round(float(beta[1]), 3)}
    return out
