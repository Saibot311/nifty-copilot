"""Assembles everything the system knows into one structured briefing:
market state, indicator readings, and live option-chain measurements.

Every figure here is computed by Python elsewhere in the project and
passed through unchanged. The evidence lists are built by explicit rules
over those figures, not by a language model's impression of them — an LLM
layer reading this briefing would be explaining these numbers, never
producing them. That boundary is the whole point.

Sections degrade independently: if the live option chain is unreachable,
that section reports itself unavailable rather than being silently
dropped or filled with plausible-looking values.
"""

from quant.pipeline import build_analysis


def _evidence(analysis: dict) -> dict:
    ind = analysis["indicators"]
    pa = analysis["price_action"]
    regime = analysis["regime"]

    bullish, bearish, neutral = [], [], []

    if ind["ema_20"] > ind["ema_50"]:
        bullish.append(f"EMA20 ({ind['ema_20']}) is above EMA50 ({ind['ema_50']}) — uptrend structure.")
    else:
        bearish.append(f"EMA20 ({ind['ema_20']}) is below EMA50 ({ind['ema_50']}) — downtrend structure.")

    rsi = ind.get("rsi_14")
    if rsi is not None:
        if rsi > 55:
            bullish.append(f"RSI is {rsi} — momentum leaning up.")
        elif rsi < 45:
            bearish.append(f"RSI is {rsi} — momentum leaning down.")
        else:
            neutral.append(f"RSI is {rsi} — no momentum edge either way.")

    adx = ind.get("adx_14")
    if adx is not None:
        if adx >= 25:
            neutral.append(f"ADX is {adx} — a real trend is in force, which strengthens whichever direction price is already going.")
        else:
            neutral.append(f"ADX is {adx} — below 25, so trend-following setups are on weaker footing.")

    if regime == "TREND_BULL":
        bullish.append("Regime classifier reads TREND_BULL.")
    elif regime == "TREND_BEAR":
        bearish.append("Regime classifier reads TREND_BEAR.")
    else:
        neutral.append(f"Regime classifier reads {regime} — no clean directional regime.")

    if pa["structure"] == "higher_high_higher_low":
        bullish.append("Price action shows higher highs and higher lows.")
    elif pa["structure"] == "lower_high_lower_low":
        bearish.append("Price action shows lower highs and lower lows.")
    else:
        neutral.append("Price structure is mixed — no clean sequence of higher or lower swings.")

    if pa["broke_prev_day_high"]:
        bullish.append(f"Broke above the previous day's high ({pa['prev_day_high']}).")
    if pa["broke_prev_day_low"]:
        bearish.append(f"Broke below the previous day's low ({pa['prev_day_low']}).")

    if len(bullish) > len(bearish) + 1:
        net = "Evidence leans bullish."
    elif len(bearish) > len(bullish) + 1:
        net = "Evidence leans bearish."
    else:
        net = "Evidence is mixed — no clear directional edge from the indicators alone."

    return {
        "bullish": bullish,
        "bearish": bearish,
        "neutral_or_context": neutral,
        "net_read": net,
        "counts": {"bullish": len(bullish), "bearish": len(bearish)},
    }


def _levels(analysis: dict) -> dict:
    ind = analysis["indicators"]
    pa = analysis["price_action"]
    return {
        "confirmation_would_be": [
            f"A close back above EMA20 ({ind['ema_20']}) while the regime holds — that is exactly what the EMA Pullback rule waits for.",
            f"A break and hold above the previous day's high ({pa['prev_day_high']}).",
        ],
        "invalidation_would_be": [
            f"A close below the previous day's low ({pa['prev_day_low']}).",
            f"ADX falling below 20 (currently {ind['adx_14']}) — trend strength draining away.",
        ],
    }


def build_briefing(symbol: str = "^NSEI", include_live_chain: bool = True) -> dict:
    analysis = build_analysis(symbol)

    briefing: dict = {
        "as_of": analysis["as_of"],
        "symbol": analysis["symbol"],
        "market_state": {
            "price": analysis["price"],
            "change": analysis["change"],
            "change_pct": analysis["change_pct"],
            "regime": analysis["regime"],
        },
        "indicators": analysis["indicators"],
        "price_action": analysis["price_action"],
        "evidence": _evidence(analysis),
        "levels": _levels(analysis),
    }

    if include_live_chain:
        try:
            from options.chain_analytics import live_chain_analytics

            briefing["live_option_chain"] = live_chain_analytics("NIFTY")
        except Exception as e:
            briefing["live_option_chain"] = {
                "unavailable": f"Live chain could not be fetched ({type(e).__name__}). "
                "Reported as unavailable rather than substituted with stale or estimated values."
            }

    briefing["how_to_read_this"] = (
        "Every number above is computed from real market data — none is estimated. The evidence "
        "lists are rule-based reads of those numbers, not opinions. This is decision support: it "
        "shows what is measurable and what the historical record says, then leaves the trade "
        "decision to you."
    )
    return briefing
