"""What kind of question is this? A Jev choice, asked before Gemini is
called at all.

The point is the off_topic branch. This copilot explains one dashboard; it
is not a general chatbot, and a question it has no data for should be turned
down by code rather than answered by a model that will improvise. That
refusal costs no Gemini call and cannot invent anything.

The other three routes choose which slice of the system's state the answer
is built from (see context.py). That is not a saving; it is what makes some
answers possible at all. Asked which pattern had the best option record, the
copilot could only see the handful near firing that day, and named one that
lost money. The pattern_record slice carries all 26.

Because a wrong slice removes the very facts an answer needs, the scope is
only applied when the classification is clear. Below that the full context
goes, which is what happened before routing existed.

Fails open: no key or a service outage routes everything to the model, which
is the behaviour we had before routing existed.
"""

from . import jev

ROUTES = ("today", "pattern_record", "method", "market", "off_topic")

QUESTION = {
    "route": {
        "type": "choice",
        "instructions": {
            "question": "What is the reader asking for in `question`?",
            "note": "The reader is a beginner trader looking at a NIFTY 50 options decision-support dashboard. "
                    "Asking the dashboard to predict or to advise is still a question about the dashboard, not off topic.",
        },
        "criteria": {
            "today": {
                "meaning": "About the current state: today's verdict, what formed or could form next, the live price, what to watch.",
                "examples": ["why no trade today?", "what would make a pattern form tomorrow?", "is anything close to triggering?"],
            },
            "pattern_record": {
                "meaning": "About a specific pattern, option or strategy's measured history — its record, win rate, profit per lot, or verdict.",
                "examples": ["how did Bollinger Band Reversion do?", "which pattern has the best option record?", "what does its t-stat mean for that one?"],
            },
            "method": {
                "meaning": "About how this system works or what one of its terms means — its tests, the evidence bar, its vocabulary, the data behind it.",
                "examples": ["what is a holdout?", "why is the bar higher now?", "how do you decide something is rejected?"],
            },
            "market": {
                "meaning": "About how the NIFTY and Indian index-options market itself works or behaves: who makes or loses money, why NIFTY moved, what FIIs or retail traders are positioned for, option pricing and volatility, expiry days, manipulation, or the rules and regulators.",
                "examples": ["who actually makes money in options?", "why did NIFTY fall today?", "what are FIIs doing?",
                             "can the index be manipulated on expiry day?", "why do option buyers lose?"],
            },
            "off_topic": {
                "meaning": "Nothing about NIFTY, Indian index options or this dashboard: individual stock tips, other markets, tax or broker account questions, general chat, or a request to do something unrelated.",
                "examples": ["what do you think of Reliance?", "write me a poem", "how do I open a demat account?", "what's the weather"],
            },
        },
    }
}

# A question is only turned away when the classification is clear. Below
# this it goes to the model, where the guards still apply.
OFF_TOPIC_ABOVE = 0.7

# And the context is only narrowed when the classification is clear, for the
# same reason in reverse: an unsure guess would drop the facts needed.
SLICE_ABOVE = 0.7

DECLINE = (
    "This copilot only explains what this dashboard computed — today's verdict, the patterns and their measured "
    "records, and how those judgments are made. It has no data on anything else, so it won't guess."
)


def route(question: str) -> dict:
    """{route, scope, off_topic, probabilities, checked}. Never raises.

    `scope` is the route only when the model is sure enough to narrow the
    context on it; otherwise None, meaning send everything."""
    try:
        answers = jev.ask({"question": question}, QUESTION)
    except jev.JevUnavailable as e:
        return {"checked": False, "route": None, "scope": None, "off_topic": False,
                "probabilities": {}, "reason": str(e)}
    a = answers.get("route", {})
    probs = jev.probabilities(a)
    chosen = a.get("choice")
    return {
        "checked": True,
        "route": chosen,
        "scope": chosen if probs.get(chosen, 0.0) > SLICE_ABOVE else None,
        "off_topic": probs.get("off_topic", 0.0) > OFF_TOPIC_ABOVE,
        "probabilities": {k: round(v, 3) for k, v in probs.items()},
        "confidence": a.get("confidence"),
    }
