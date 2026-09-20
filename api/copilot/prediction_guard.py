"""Second guard on copilot answers, using TypeSafe's Jev (System One).

guard.py catches invented *numbers*. It cannot catch "this looks set to
rise" — a forecast with no number in it, which the copilot's rules forbid
just as firmly. That judgment is semantic, so it goes to a model built to
return a typed answer rather than prose: two noul questions (probability
that a statement is true), asked together over the same state.

Reporting the system's own computed verdict is explicitly allowed — the
criteria say so, otherwise every honest explanation of a CONSIDER_CALL
would be flagged.

Optional: with no TYPESAFE_API_KEY the check is skipped and the answer is
marked unchecked rather than blocked; the number guard still applies.
"""

import requests

from market_data.kite_session import _env

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_S = 20

# Low on purpose: letting a forecast through breaks the product's core
# promise, while a wrongly withheld explanation costs one more click.
# Tune against real answers before raising it.
BLOCK_ABOVE = 0.3

QUESTIONS = {
    "predicts_market": {
        "type": "noul",
        "instructions": {
            "question": "In the writer's own voice, the text claims what the market, index or price will do next.",
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
            "question": "The text tells the reader to place, hold or avoid a trade, as the writer's own advice.",
            "note": "Describing the software's recommendation is not the writer advising; a direct instruction to the reader is.",
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
                ],
            },
        },
    },
}


def available() -> bool:
    return bool(_env("TYPESAFE_API_KEY"))


def check(answer: str) -> dict:
    """{checked, blocked, scores, reason}. Never raises: a guard that is
    down must not take the copilot down with it."""
    key = _env("TYPESAFE_API_KEY")
    if not key:
        return {"checked": False, "blocked": False, "scores": {}, "reason": "no TYPESAFE_API_KEY — prediction check skipped"}
    try:
        resp = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"state": answer, "model": MODEL, "questions": QUESTIONS},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        answers = resp.json()["answers"]
        scores = {k: float(answers[k]["noul"]) for k in QUESTIONS if k in answers}
    except Exception as e:
        return {"checked": False, "blocked": False, "scores": {},
                "reason": f"prediction check unavailable ({type(e).__name__}) — skipped"}

    hits = [k for k, v in scores.items() if v > BLOCK_ABOVE]
    label = {"predicts_market": "predicts where the market is going", "advises_trade": "tells you to trade"}
    return {
        "checked": True,
        "blocked": bool(hits),
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "reason": ("Answer withheld: it " + " and ".join(label[h] for h in hits) + ", which this tool must not do."
                   if hits else "no forecast or trade instruction detected"),
    }
