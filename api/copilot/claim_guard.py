"""Third guard on copilot answers: is each sentence actually supported by
the data the system computed?

guard.py checks *numbers*. prediction_guard.py checks for forecasts and
trade advice. Neither catches a sentence like "this pattern has worked well
recently" — no invented figure, no prediction, and still not true. That is
the gap this closes.

The judgment is semantic, so it goes to Jev as one choice question per
sentence: does DATA support this, contradict it, say nothing about it, or is
it not a factual claim at all? The last option matters — an explanation is
mostly framing and caveats, and treating those as unsupported claims would
withhold every honest answer.

Threshold is deliberately looser than the forecast guard's. Letting a
forecast through breaks the product's promise; being twitchy here just makes
the copilot useless. The number guard already covers the dangerous case.
"""

import re

MAX_CLAIMS = 12

# Split on sentence end followed by the start of a new one. A decimal point
# is followed by a digit, not a space, so 23,270.60 stays in one piece.
# Lines are split first: a list item or heading ends without punctuation, and
# a whole block judged as one claim would let a bad sentence hide among good
# ones — the averaging is exactly what the guard must not do.
_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z₹"\'(])')
_BULLET = re.compile(r'^\s*(?:[-*•]|\d+[.)])\s+')

# Flag when contradicted + not-in-data together carry more probability than
# this. Tune on scripts/check_guards.py, not by taste.
UNSUPPORTED_ABOVE = 0.6

_NOTE = (
    "DATA is everything the system computed; `answer` is the full text the statement came from, for context only. "
    "The writer's job is to explain DATA to a beginner, so restating a DATA value in plain words, naming a verdict "
    "DATA gives, or explaining what a term in DATA means all count as supported. Judge only the one statement."
)


def split_claims(text: str) -> list[str]:
    parts = []
    for line in text.strip().splitlines():
        line = _BULLET.sub("", line).strip()
        parts += [s.strip() for s in _SPLIT.split(line) if s.strip()]
    return parts[:MAX_CLAIMS]


def questions(claims: list[str]) -> dict:
    return {
        f"claim_{i}": {
            "type": "choice",
            "instructions": {
                "question": f"How does DATA relate to the statement in `claims[{i}]`?",
                "note": _NOTE,
            },
            "criteria": {
                "supported": {
                    "meaning": "DATA contains this, or the statement is a plain-language restatement of something in DATA.",
                    "examples": [
                        "the system's verdict today is NO_TRADE",
                        "that option lost money per lot over the test period",
                        "REJECTED means the pattern showed no proven edge",
                    ],
                },
                "contradicted": {
                    "meaning": "DATA says something different — a different verdict, direction, or figure.",
                    "examples": [
                        "the system recommends a CALL (when DATA's action is NO_TRADE)",
                        "this pattern has an approved record (when DATA says rejected)",
                    ],
                },
                "not_in_data": {
                    "meaning": "A factual claim about the market, a pattern, or a record that DATA does not contain at all.",
                    "examples": [
                        "this pattern has worked well recently",
                        "volatility has been rising all month",
                        "most traders lose money on weekly options",
                    ],
                },
                "not_a_claim": {
                    "meaning": "No factual assertion to check: framing, a caveat, a general definition, or a note on how to read the dashboard.",
                    "examples": [
                        "Here is what the dashboard shows today.",
                        "None of this is a reason to trade.",
                        "A t-statistic under 2 is indistinguishable from luck.",
                    ],
                },
            },
        }
        for i, claim in enumerate(claims)
    }


def judged(answers: dict, claims: list[str]) -> list[dict]:
    """Every checked sentence with how much probability sits against it.

    Kept separate from the threshold so scripts/check_guards.py can sweep
    UNSUPPORTED_ABOVE over labelled cases instead of it being a guess.
    """
    out = []
    for i, claim in enumerate(claims):
        a = answers.get(f"claim_{i}")
        if not a:
            continue
        p = {k: float(v) for k, v in (a.get("probabilities") or {}).items()}
        against = p.get("contradicted", 0.0) + p.get("not_in_data", 0.0)
        out.append({
            "claim": claim,
            # The model's own pick, not a tie-break over two of the four —
            # reporting "contradicted" at probability 0.0 reads as a finding.
            "verdict": a.get("choice") or max(p, key=p.get, default="unknown"),
            "against": round(against, 3),
            "probabilities": {k: round(v, 3) for k, v in p.items()},
        })
    return out


def unsupported(answers: dict, claims: list[str]) -> list[dict]:
    """The sentences DATA does not back, with why and how strongly."""
    return [c for c in judged(answers, claims) if c["against"] > UNSUPPORTED_ABOVE]
