"""What kind of question is this? A Jev choice, asked before Gemini is
called at all.

The point is the off_topic branch. This copilot explains one dashboard; it
is not a general chatbot, and a question it has no data for should be turned
down by code rather than answered by a model that will improvise. That
refusal costs no Gemini call and cannot invent anything.

The other three routes are recorded but not yet acted on. Sending only the
relevant slice of context is the obvious next step — it shrinks the prompt
and narrows what the guards have to police — but it also narrows what the
answer is allowed to mention, so it needs its own labelled cases first.

Fails open: no key or a service outage routes everything to the model, which
is the behaviour we had before routing existed.
"""

from . import jev

ROUTES = ("today", "pattern_record", "method", "off_topic")

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
                "meaning": "About how the system works or what a term means — the tests, the evidence bar, the vocabulary, the data behind it.",
                "examples": ["what is a holdout?", "why is the bar higher now?", "how do you decide something is rejected?"],
            },
            "off_topic": {
                "meaning": "Nothing this dashboard computed could answer it: other markets or stocks, tax or broker questions, general chat, or a request to do something unrelated.",
                "examples": ["what do you think of Reliance?", "write me a poem", "how do I open a demat account?", "what's the weather"],
            },
        },
    }
}

# A question is only turned away when the classification is clear. Below
# this it goes to the model, where the guards still apply.
OFF_TOPIC_ABOVE = 0.7

DECLINE = (
    "This copilot only explains what this dashboard computed — today's verdict, the patterns and their measured "
    "records, and how those judgments are made. It has no data on anything else, so it won't guess."
)


def route(question: str) -> dict:
    """{route, off_topic, probabilities, checked}. Never raises."""
    try:
        answers = jev.ask({"question": question}, QUESTION)
    except jev.JevUnavailable as e:
        return {"checked": False, "route": None, "off_topic": False, "probabilities": {}, "reason": str(e)}
    a = answers.get("route", {})
    probs = jev.probabilities(a)
    return {
        "checked": True,
        "route": a.get("choice"),
        "off_topic": probs.get("off_topic", 0.0) > OFF_TOPIC_ABOVE,
        "probabilities": {k: round(v, 3) for k, v in probs.items()},
        "confidence": a.get("confidence"),
    }
