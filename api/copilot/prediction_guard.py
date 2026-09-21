"""Forecast guard: does the answer predict the market, or tell the reader
to trade? Both are forbidden, and neither leaves a number behind for
guard.py to catch — "this looks set to rise" breaks the rule with no figures
in it at all.

The judgment is semantic, so it goes to Jev as two noul questions (the
probability that a statement is true) asked over the same state as the claim
guard, in one request.

Reporting the system's own computed verdict is explicitly allowed — the
criteria say so and give examples, otherwise every honest explanation of a
CONSIDER_CALL would be flagged. Tuning that distinction moved a real false
positive from 0.64 to 0.05, which is why the examples are worth their space.

The state also carries what the system actually computed, so "the system
recommends a CALL" can be recognised as reporting rather than guessed at
from tone alone.
"""

# Low on purpose: letting a forecast through breaks the product's core
# promise, while a wrongly withheld explanation costs one more click.
# Tune against scripts/check_guards.py before raising it.
BLOCK_ABOVE = 0.3

LABELS = {
    "predicts_market": "predicts where the market is going",
    "advises_trade": "tells you to trade",
}

QUESTIONS = {
    "predicts_market": {
        "type": "noul",
        "instructions": {
            "question": "In the writer's own voice, the text in `answer` claims what the market, index or price will do next.",
            "note": "Relaying a verdict that software computed is reporting, not predicting. What matters is who is making the claim, not whether a direction is mentioned.",
        },
        "criteria": {
            "true": {
                "meaning": "The writer asserts or hints at future direction as their own view.",
                "examples": ["momentum looks set to carry it higher", "expect a bounce from here", "this should hold 23,000"],
            },
            "false": {
                "meaning": "Reports computed results, history, or what a pattern would need in order to form — including relaying the system's recommendation and its stated reasons.",
                "examples": [
                    "the system recommends a CALL because the pattern that formed has an approved option record",
                    "the system says NO_TRADE: nothing formed on the last close",
                    "this pattern forms if NIFTY closes at 23,322 or higher",
                    "on 2024-26 data that option averaged a loss per lot",
                ],
            },
        },
    },
    "advises_trade": {
        "type": "noul",
        "instructions": {
            "question": "The text in `answer` tells the reader to place, hold or avoid a trade, as the writer's own advice.",
            "note": "Describing the software's recommendation is not the writer advising; a direct instruction to the reader is. "
                    "Naming the option the system computed — its moneyness, strike or holding period — is part of reporting that "
                    "verdict, not an instruction. A verdict such as REJECTED or NO_TRADE is a finding about past data, not a "
                    "warning to stay out.",
        },
        "criteria": {
            "true": {
                "meaning": "Directs the reader to act.",
                "examples": ["buy the 23,300 call", "book profits today", "stay out of the market"],
            },
            "false": {
                "meaning": "Explains the system's computed recommendation, its evidence, or what an option returned historically, without instructing the reader.",
                "examples": [
                    "the system recommends a CALL today; its option record is approved",
                    "the system's verdict is NO_TRADE",
                    "the system's verdict is CONSIDER_CALL: buy a 2% ITM call, hold 10 days, per its computed record",
                    "on 2024-26 data that option lost money per lot, so the system rejects it",
                ],
            },
        },
    },
}


def scores(answers: dict) -> dict[str, float]:
    return {k: float(answers[k]["noul"]) for k in QUESTIONS if k in answers}


def blocking(scores: dict[str, float]) -> list[str]:
    return [k for k, v in scores.items() if v > BLOCK_ABOVE]
