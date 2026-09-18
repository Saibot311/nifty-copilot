"""Plain-language description of every registered pattern: exactly what the
code checks (`forms_when`) and the market logic it's betting on (`why`).

`why` is the hypothesis, not evidence. Whether it held up on NIFTY is
answered by the numbers next to it, never by this text.
"""

PATTERN_INFO: dict[str, dict[str, str]] = {
    "ema_pullback": {
        "forms_when": "In an established uptrend, price closes back above its 20-day EMA after dipping below it.",
        "why": "Buyers in a trend treat the average as value; a quick reclaim says the dip was taken, not a trend change.",
    },
    "ema_rejection_short": {
        "forms_when": "In an established downtrend, price closes back below its 20-day EMA after bouncing above it.",
        "why": "Sellers in a downtrend use rallies to the average to exit or short; failing there confirms supply.",
    },
    "rsi_reversal": {
        "forms_when": "RSI(14) was below 30 yesterday and closes back at or above 30 today.",
        "why": "Selling became extreme and is now easing; forced sellers are done and short-covering can follow.",
    },
    "prev_day_breakout": {
        "forms_when": "Today's close is above yesterday's high.",
        "why": "Clearing the prior day's range shows buyers absorbed all of yesterday's supply — short-term momentum.",
    },
    "bollinger_reversion": {
        "forms_when": "Price closed below the lower Bollinger Band (20, 2σ) yesterday and closes back inside today.",
        "why": "A move two standard deviations out is stretched; returning inside suggests the stretch is snapping back.",
    },
    "supertrend_flip_bull": {
        "forms_when": "Supertrend (10, 3×ATR) flips from down to up.",
        "why": "Price has moved far enough against the old trend, relative to volatility, to call the trend changed.",
    },
    "supertrend_flip_bear": {
        "forms_when": "Supertrend (10, 3×ATR) flips from up to down.",
        "why": "The volatility-scaled trailing stop of the uptrend was broken — the trend is presumed over.",
    },
    "ema_crossover_bull": {
        "forms_when": "The 9-day EMA crosses above the 21-day EMA.",
        "why": "Short-term average price overtaking the medium-term one marks momentum turning up.",
    },
    "ema_crossover_bear": {
        "forms_when": "The 9-day EMA crosses below the 21-day EMA.",
        "why": "Short-term average price falling under the medium-term one marks momentum turning down.",
    },
    "macd_bull_cross": {
        "forms_when": "The MACD line crosses above its signal line.",
        "why": "The gap between fast and slow averages starts widening upward — acceleration turning positive.",
    },
    "macd_bear_cross": {
        "forms_when": "The MACD line crosses below its signal line.",
        "why": "Upward acceleration has rolled over; momentum is turning negative.",
    },
    "rsi_overbought_reversal": {
        "forms_when": "RSI(14) was above 70 yesterday and closes at or below 70 today.",
        "why": "Buying was extreme and is fading; late buyers become sellers when momentum stalls.",
    },
    "bollinger_upper_rejection": {
        "forms_when": "Price closed above the upper Bollinger Band yesterday and closes back inside today.",
        "why": "An overextended move failed to hold its extreme — a mean-reversion bet downward.",
    },
    "stochastic_oversold_reversal": {
        "forms_when": "Stochastic %K was below 20 yesterday and closes at or above 20 today.",
        "why": "Price had closed near the bottom of its recent range and is lifting off it — short-term exhaustion of selling.",
    },
    "stochastic_overbought_reversal": {
        "forms_when": "Stochastic %K was above 80 yesterday and closes at or below 80 today.",
        "why": "Price had closed near the top of its recent range and is slipping off it — short-term buying exhaustion.",
    },
    "prev_day_breakdown": {
        "forms_when": "Today's close is below yesterday's low.",
        "why": "Losing the prior day's range shows sellers overwhelmed yesterday's demand — short-term downside momentum.",
    },
    "year_high_breakout": {
        "forms_when": "Today's close is the highest of the past 252 trading days.",
        "why": "No one who bought in the last year is at a loss, so there's little overhead supply; new highs tend to attract trend followers.",
    },
    "year_low_breakdown": {
        "forms_when": "Today's close is the lowest of the past 252 trading days.",
        "why": "Every buyer of the past year is under water; stop-losses and capitulation can accelerate the fall.",
    },
    "squeeze_breakout_up": {
        "forms_when": "Bollinger bandwidth was in its lowest 20% of the last 60 days, then price closes above the upper band.",
        "why": "Volatility is cyclical: quiet compression tends to resolve in a sharp move, and the first close outside the band picks the direction.",
    },
    "squeeze_breakout_down": {
        "forms_when": "Bollinger bandwidth was in its lowest 20% of the last 60 days, then price closes below the lower band.",
        "why": "The same compression-then-expansion idea, resolving downward.",
    },
    "bullish_engulfing": {
        "forms_when": "A green candle fully engulfs the prior red candle's body, and that prior candle was the lowest low of the last 5 days.",
        "why": "Sellers pushed to a fresh low, then buyers reversed the whole prior session — a one-day shift in control at a low.",
    },
    "bearish_engulfing": {
        "forms_when": "A red candle fully engulfs the prior green candle's body, and that prior candle was the highest high of the last 5 days.",
        "why": "Buyers pushed to a fresh high, then sellers reversed the whole prior session — a one-day shift in control at a high.",
    },
    "hammer_reversal": {
        "forms_when": "A candle with a lower wick at least 2× its body and a small upper wick, at the lowest low of the last 5 days.",
        "why": "Price was driven down intraday and bought back up by the close — rejection of lower prices at a low.",
    },
    "shooting_star": {
        "forms_when": "A candle with an upper wick at least 2× its body and a small lower wick, at the highest high of the last 5 days.",
        "why": "Price was driven up intraday and sold back down by the close — rejection of higher prices at a high.",
    },
    "pcr_capitulation_call": {
        "forms_when": "The nearest-expiry put/call open-interest ratio drops below 0.5 and stays there a second day.",
        "why": "Call open interest dwarfs puts — option writers are positioned heavily for the market not to rise. Contrarian: positioning that one-sided is the fuel for a squeeze upward.",
    },
    "pcr_exhaustion_put": {
        "forms_when": "The nearest-expiry put/call open-interest ratio rises above 1.5 and stays there a second day.",
        "why": "Put open interest dwarfs calls — writers are positioned heavily for the market not to fall. Contrarian: that crowded positioning can unwind downward. Research support for this side is weaker than for the call side.",
    },
}
