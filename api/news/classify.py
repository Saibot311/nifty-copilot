"""What is this headline about, and would it move the Indian index?

A judgment like that is semantic, so it goes to Jev: it returns a typed
answer and a calibrated probability rather than prose, which is what lets
code read a number and decide. A text model asked the same thing would write
a paragraph that sounds like a forecast, and a paragraph that sounds like a
forecast is the one thing this dashboard must never produce.

What Jev is allowed to do here:
  * say whether a headline is the kind of event that moves an index;
  * say which way it would push, if either;
  * put it in a topic.

What it is not allowed to do, and cannot: produce a number the dashboard
shows as a measurement (I2), or turn any of this into a recommendation. Its
output is a *description of the news*, and whether that description predicts
returns is a separate pre-registered study that has not reported yet.

The three questions are independent over the same headline, so they go in
one request. Judgments are stored once and never recomputed: re-judging the
same headline later, after the market has moved, would quietly turn hindsight
into a signal. A changed question is a new QUESTION_SET, not an edit.
"""

from copilot import jev

# Bump this — never edit a question in place — if any wording below changes.
# The archive keys judgments by it, so an old judgment stays attached to the
# question that actually produced it.
QUESTION_SET = "news_v1"

DIRECTIONS = ("higher", "lower", "unclear")
TOPICS = ("policy", "earnings", "global", "flows", "commodity_currency", "corporate", "noise")

QUESTIONS = {
    "market_moving": {
        "type": "noul",
        "instructions": {
            "question": "The event described in `headline` is the kind that moves the NIFTY 50, India's large-cap equity index.",
            "note": "Judge the event, not the wording. A dramatic headline about one small company does not move the index; "
                    "a flat headline about the policy rate does. Market commentary that only describes what the index has "
                    "already done today is reporting, not a market-moving event.",
        },
        "criteria": {
            "true": {
                "meaning": "Monetary policy, inflation or growth data, a large-cap earnings surprise, foreign flows, a global "
                           "shock, oil or rupee moves, tax or regulatory change affecting equities broadly.",
                "examples": ["RBI holds repo rate, shifts stance to neutral", "US Fed signals faster cuts; Asian markets rally",
                             "Reliance Q2 profit beats estimates by 18%", "FIIs sell Rs 12,000 crore in five sessions"],
            },
            "false": {
                "meaning": "One small or mid-cap company's routine news, an IPO listing pop, a personal-finance or lifestyle "
                           "piece, a recap of the session's own move, or a sports, politics or entertainment story.",
                "examples": ["Sensex falls 840 points at noon", "IPO GMPs: three small issues to watch",
                             "The Ruby Mills Limited — Trading Window", "Best credit cards for festive season"],
            },
        },
    },
    "direction": {
        "type": "choice",
        "instructions": {
            "question": "If the event in `headline` moved the NIFTY 50, which way would it push it?",
            "note": "Answer for the event's own implication, not for what the index happens to have done. "
                    "Choose unclear whenever the sign is genuinely ambiguous or the headline is not a market event — "
                    "unclear is the honest answer and is expected often.",
        },
        "criteria": {
            "higher": {
                "meaning": "The event is good for Indian large-cap equities.",
                "examples": ["RBI cuts repo rate by 25 bps", "Inflation falls below forecast", "FIIs turn net buyers"],
            },
            "lower": {
                "meaning": "The event is bad for Indian large-cap equities.",
                "examples": ["Crude jumps 6% on supply disruption", "US yields hit multi-year highs",
                             "GST rates raised on consumer goods"],
            },
            "unclear": {
                "meaning": "Not a market event, both-sided, or the sign cannot be read from the headline.",
                "examples": ["Sensex falls 840 points at noon", "Company X announces board meeting",
                             "Markets on edge ahead of Fed decision"],
            },
        },
    },
    "topic": {
        "type": "choice",
        "instructions": {"question": "What is `headline` mainly about?"},
        "criteria": {
            "policy": {"meaning": "Central bank, government, tax or regulatory action, and macro data releases.",
                       "examples": ["RBI keeps rates on hold", "CPI inflation eases to 4.1%"]},
            "earnings": {"meaning": "Company results, guidance or profit warnings.",
                         "examples": ["Infosys raises FY guidance", "HDFC Bank Q2 due Oct 17"]},
            "global": {"meaning": "Overseas markets, the Fed, geopolitics, global risk sentiment.",
                       "examples": ["US, Japanese yields hit multi-year highs", "Asian shares slip on Fed caution"]},
            "flows": {"meaning": "Foreign or domestic institutional buying and selling, IPO and fund flows.",
                      "examples": ["FIIs sell Rs 12,000 crore", "SIP inflows hit record"]},
            "commodity_currency": {"meaning": "Oil, gold, metals, and the rupee.",
                                   "examples": ["Brent crosses $90", "Rupee hits record low against dollar"]},
            "corporate": {"meaning": "A specific company's non-earnings news: deals, filings, management, listings.",
                          "examples": ["NSE shares rise 5% after listing", "Company X — Trading Window"]},
            "noise": {"meaning": "Session recaps, personal finance, lifestyle, or anything not about markets.",
                      "examples": ["Sensex falls 840 points at noon", "Best festive credit cards"]},
        },
    },
}


def available() -> bool:
    return jev.available()


def judge_one(headline: str, summary: str | None = None) -> dict:
    """Three typed judgments for one headline, in one request.

    Raises jev.JevUnavailable. Callers store nothing on failure: an
    unjudged headline is shown as unjudged, never as neutral.
    """
    state = {"headline": headline}
    if summary:
        state["summary"] = summary[:400]
    answers = jev.ask(state, QUESTIONS)

    moving = answers.get("market_moving") or {}
    direction = answers.get("direction") or {}
    topic = answers.get("topic") or {}
    dir_probs = jev.probabilities(direction)
    chosen_dir = direction.get("choice") or (max(dir_probs, key=dir_probs.get) if dir_probs else None)

    return {
        "market_moving": round(float(moving["noul"]), 3) if moving.get("noul") is not None else None,
        "direction": chosen_dir if chosen_dir in DIRECTIONS else "unclear",
        "dir_conf": round(float(dir_probs.get(chosen_dir, 0.0)), 3) if chosen_dir else None,
        "topic": topic.get("choice") if topic.get("choice") in TOPICS else None,
    }
