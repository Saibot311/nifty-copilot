"""Translates an index-level directional signal into options trade
guidance — strike/expiry heuristics, not a live options price feed.

Deliberately limited to EMA Pullback: it's the only strategy that showed
any real edge in Phase 7-8 research (still CONDITIONAL, not APPROVED —
the other three are exploratory dead ends). Deliberately does NOT quote
strikes, premiums, IV, or Greeks: none of that data is in this system yet,
and inventing plausible-looking numbers for it would be exactly the kind
of fabricated statistic this project exists to avoid.
"""

from backtest.strategies import STRATEGY_REGISTRY, load_daily_data
from backtest.walkforward import evaluate_strategy


def get_signal_status(strategy_name: str = "ema_pullback", symbol: str = "^NSEI", days: int = 500) -> dict:
    if strategy_name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy '{strategy_name}'")
    spec = STRATEGY_REGISTRY[strategy_name]
    df, regime_series = load_daily_data(symbol, days)
    entries = spec["fn"](df, regime_series, **spec["params"])

    fired_today = bool(entries.iloc[-1])
    recent_fire_dates = [str(df.index[i].date()) for i in range(len(df)) if bool(entries.iloc[i])][-5:]

    return {
        "strategy": strategy_name,
        "symbol": symbol,
        "as_of": str(df.index[-1].date()),
        "signal_active_today": fired_today,
        "recent_signal_dates": recent_fire_dates,
    }


def translate_to_options(strategy_name: str = "ema_pullback", symbol: str = "^NSEI", hold_days: int = 10) -> dict:
    signal = get_signal_status(strategy_name, symbol)
    validation = evaluate_strategy(symbol=symbol, hold_days=hold_days)
    validation_status = validation["final_status"]

    if not signal["signal_active_today"]:
        return {
            "as_of": signal["as_of"],
            "actionable_today": False,
            "message": (
                f"No active {strategy_name} signal as of the latest daily close ({signal['as_of']}). "
                "No options trade to consider today from this strategy."
            ),
            "recent_signal_dates": signal["recent_signal_dates"],
            "validation_status": validation_status,
        }

    # Buffer math: hold_days is in TRADING days (~1.45 calendar days per
    # trading day including weekends), plus an explicit safety margin so
    # the option doesn't expire right as the thesis is supposed to play
    # out rather than well after.
    calendar_days_for_hold = round(hold_days * 1.45)
    safety_buffer_days = 10
    min_expiry_calendar_days = calendar_days_for_hold + safety_buffer_days

    return {
        "as_of": signal["as_of"],
        "actionable_today": True,
        "direction": "CALL (bullish)",
        "rationale": (
            "EMA Pullback is long-only and only fires in a TREND_BULL regime, so an active "
            "signal always implies a bullish view — never a put from this strategy."
        ),
        "strike_guidance": (
            "Consider an at-the-money (ATM) or slightly in-the-money (ITM) strike rather than "
            "far out-of-the-money. ATM/ITM options lose a smaller fraction of their value to time "
            "decay relative to their premium, which matters more over a multi-day hold than for a "
            "same-day trade."
        ),
        "expiry_guidance": (
            f"Look for an expiry at least ~{min_expiry_calendar_days} calendar days out from "
            f"{signal['as_of']} — enough buffer beyond the strategy's {hold_days}-trading-day hold "
            "that the option isn't expiring right as (or before) the thesis is supposed to play out. "
            "Check your broker's platform for the exact available NIFTY expiry dates rather than "
            "assuming a specific weekday — NSE has changed weekly-expiry conventions before."
        ),
        "validation_status": validation_status,
        "critical_warnings": [
            f"This strategy's status is {validation_status}, not APPROVED (see Phase 8) — only 2 of 5 "
            "historical periods showed a real edge. Treat this as a documented idea to evaluate "
            "yourself, not a recommendation to act on.",
            "This translates an INDEX-level signal into an options idea. It does not account for "
            "implied volatility, theta decay speed, bid-ask spread, or actual option premiums — none "
            "of that data is in this system yet.",
            "An option can lose value even if NIFTY moves in the predicted direction, if it moves too "
            "slowly or IV drops. The backtest measures the INDEX's return, not what an actual option "
            "position would have returned.",
            "Not a live options price feed. No real strikes, premiums, or Greeks are fetched here.",
        ],
        "recent_signal_dates": signal["recent_signal_dates"],
    }
