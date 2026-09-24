"""Which strike the paper book buys with the money it has.

The book used to buy one fixed strike — 2% in the money for the best read,
each pattern's tested option otherwise — and skip the session whenever a lot
of it cost more than the per-trade cap. Asked on 2026-09-24 to judge instead:
of the strikes the research grid already uses, buy the one that has done best
per rupee among those whose whole lot the book can afford, and step down to
the next best when the first choice does not fit.

"Best" is judged on 2018-2023 only — the development period, never the
2024-26 holdout — and it is the *median* trade's return on premium, not the
mean. With no signal, buying options has lost money on average, and the mean
is carried by a few huge winners: 2% OTM calls averaged +18% of premium on
2018-23 while the typical one lost 64%. Ranked by the mean, the book would buy
lottery tickets (HANDOFF: "Ranking options by % return picks ₹20 lottery
tickets"). Ranked by the median, it buys the deepest in-the-money strike the
money allows and steps toward the money only as far as it must.

Nothing here has an edge. This chooses what has cost a buyer least, not what
will make money, and says so on every row it opens.
"""

import json
import statistics
from pathlib import Path

from backtest import pattern_options as po
from backtest.options_engine import select_contract

MENU_PATH = Path(__file__).parent.parent / "data" / "option_menu.json"
MIN_TRADES = 30          # a no-signal menu entry needs at least this many 2018-23 trades
MIN_OPEN_INTEREST = 1000


def _trades(option_type: str, m: float, dte: int, hold: int) -> list:
    """No-signal buys of one strike, every (hold + 1) sessions from 2018."""
    import pandas as pd

    from backtest.strategies import load_daily_data
    df, _ = load_daily_data("^NSEI", 7000)
    td = [str(d.date()) for d in df.index]
    ctx = (df, pd.Series(df["close"].values, index=td), td)
    days = [d for d in td if po.OPTIONS_START <= d < po.SPLIT_DATE]
    return po._run(days[:: hold + 1], ctx, option_type, m, dte, hold)


def baseline_menu(option_type: str, dte: int, hold: int) -> list[dict]:
    """The research grid's strikes, each with how its no-signal buys did on
    2018-23. Trades that finish on or after the split are dropped (the same
    purge as the research), and the result is stored: the development
    period is fixed, so it only ever needs computing once."""
    key = f"{option_type}:{dte}:{hold}"
    try:
        stored = json.loads(MENU_PATH.read_text())
    except Exception:
        stored = {}
    if key in stored:
        return stored[key]
    menu = []
    for m in po.MONEYNESS_PCT:
        rets = [t.net_return_pct for t in _trades(option_type, m, dte, hold) if t.exit_date < po.SPLIT_DATE]
        if len(rets) < MIN_TRADES:
            continue
        menu.append({"moneyness_pct": m, "label": po.moneyness_label(m), "dev_trades": len(rets),
                     "dev_median_pct": round(statistics.median(rets), 1),
                     "dev_mean_pct": round(statistics.mean(rets), 1)})
    stored[key] = menu
    try:
        MENU_PATH.parent.mkdir(parents=True, exist_ok=True)
        MENU_PATH.write_text(json.dumps(stored, indent=1))
    except Exception:
        pass  # a cache that cannot be written is recomputed next time
    return menu


def pattern_menu(research_row: dict) -> list[dict]:
    """A pattern's own 2018-23 results for each strike, at its tested expiry
    and hold — the grid the research chose its option from, development
    period only. Only the strike moves, so a pattern that does not fit the
    budget is still bought on the schedule it was tested on."""
    opt = research_row.get("suggested_option") or {}
    menu = []
    for g in research_row.get("dev_grid") or []:
        if (g["dte"], g["hold"]) != (opt.get("min_days_to_expiry"), opt.get("hold_days")):
            continue
        if (g.get("num_trades") or 0) < po.MIN_DEV_TRADES or g.get("median_return_pct") is None:
            continue
        menu.append({"moneyness_pct": g["m"], "label": po.moneyness_label(g["m"]), "dev_trades": g["num_trades"],
                     "dev_median_pct": g["median_return_pct"], "dev_mean_pct": g.get("avg_return_pct")})
    return menu


def _offset(spot: float, m: float, option_type: str) -> float:
    return spot * m / 100 * (1 if option_type == "CE" else -1)


def choose(conn, menu: list[dict], *, option_type: str, dte: int, entry_date: str, spot: float,
           planned_exit: str | None, lots_for) -> dict:
    """Price every strike on the menu at the entry close, keep those whose
    whole lot fits (`lots_for(premium)` is the book's sizing rule), and take
    the best 2018-23 median; deeper in the money on a tie. Returns the choice
    (or None), every strike it compared, and one plain sentence."""
    compared = []
    for c in menu:
        picked = select_contract(entry_date, spot, option_type, _offset(spot, c["moneyness_pct"], option_type),
                                 dte, planned_exit or entry_date, MIN_OPEN_INTEREST, conn)
        premium = None
        if picked:
            row = conn.execute("SELECT close FROM option_bars WHERE trade_date = ? AND expiry_date = ? "
                               "AND strike = ? AND option_type = ?",
                               (entry_date, picked[1], picked[0], option_type)).fetchone()
            premium = float(row["close"]) if row and row["close"] else None
        lots = lots_for(premium) if premium else 0
        compared.append({**c, "strike": picked[0] if picked else None, "expiry": picked[1] if picked else None,
                         "premium": premium, "lot_rs": round(premium * po.LOT_SIZE) if premium else None,
                         "lots": lots, "fits": lots >= 1})
    fits = [c for c in compared if c["fits"]]
    choice = max(fits, key=lambda c: (c["dev_median_pct"], -c["moneyness_pct"])) if fits else None
    return {"choice": choice, "compared": compared, "summary": _summary(choice, compared, option_type)}


def _summary(choice: dict | None, compared: list[dict], option_type: str) -> str:
    side = "call" if option_type == "CE" else "put"
    priced = [c for c in compared if c["premium"]]
    if choice is None:
        cheapest = min((c["lot_rs"] for c in priced), default=None)
        return (f"no strike's whole lot fits the budget (cheapest {side} lot ₹{cheapest:,})" if cheapest
                else f"no {side} contract priced at the entry close")
    better = [c for c in priced if not c["fits"] and c["dev_median_pct"] > choice["dev_median_pct"]]
    text = (f"{choice['label']} {side} at ₹{choice['premium']:g} (₹{choice['lot_rs']:,} a lot); "
            f"its typical 2018-23 trade returned {choice['dev_median_pct']:+.1f}% of premium")
    if better:
        text += "; " + ", ".join(f"{c['label']} (₹{c['lot_rs']:,} a lot)" for c in better) + " did not fit"
    return text
