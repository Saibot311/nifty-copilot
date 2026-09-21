"""One Jev call that reviews a drafted answer from both angles.

The forecast questions and the per-sentence claim questions are independent
judgments over the same state, so they go in a single request: one round
trip, one bill, and both guards see the same evidence. Giving the forecast
questions the computed data as well as the text is what lets "the system
recommends a CALL" be recognised as reporting rather than inferred from tone.

Fails open by design. No key, or a service that does not answer, marks the
answer unchecked rather than withholding it — the number guard in guard.py
is local, deterministic and always runs.
"""

from . import claim_guard, jev, prediction_guard

SKIPPED = {"checked": False, "blocked": False, "scores": {}, "unsupported": [], "problems": []}


def build_state(answer: str, data=None, claims: list[str] | None = None) -> dict:
    state: dict = {"answer": answer}
    if claims:
        state["claims"] = claims
    if data is not None:
        state["data"] = data
    return state


def review_answer(answer: str, data=None, check_claims: bool = True) -> dict:
    """{checked, blocked, scores, unsupported, problems, reason}. Never raises."""
    claims = claim_guard.split_claims(answer) if (check_claims and data is not None) else []
    questions = {**prediction_guard.QUESTIONS, **claim_guard.questions(claims)}
    try:
        answers = jev.ask(build_state(answer, data, claims), questions)
    except jev.JevUnavailable as e:
        return {**SKIPPED, "reason": str(e)}

    scores = prediction_guard.scores(answers)
    hits = prediction_guard.blocking(scores)
    judged = claim_guard.judged(answers, claims)
    unsupported = [c for c in judged if c["against"] > claim_guard.UNSUPPORTED_ABOVE]

    problems = []
    if hits:
        problems.append(
            "This answer " + " and ".join(prediction_guard.LABELS[h] for h in hits)
            + ". Report only what the system computed; never say where the market is going or what to do."
        )
    if unsupported:
        listed = "; ".join(f'"{u["claim"]}"' for u in unsupported)
        problems.append(
            f"These sentences are not supported by DATA: {listed}. Remove them, or replace them with what DATA "
            "actually says."
        )

    return {
        "checked": True,
        "blocked": bool(problems),
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "unsupported": unsupported,
        "claims": judged,
        "problems": problems,
        "claims_checked": len(claims),
        "reason": _reason(hits, unsupported),
    }


def _reason(hits: list[str], unsupported: list[dict]) -> str:
    parts = []
    if hits:
        parts.append("it " + " and ".join(prediction_guard.LABELS[h] for h in hits) + ", which this tool must not do")
    if unsupported:
        n = len(unsupported)
        parts.append(f"{n} sentence{'s' if n > 1 else ''} said something the computed data does not support")
    if not parts:
        return "no forecast, trade instruction or unsupported claim detected"
    return "Answer withheld: " + "; ".join(parts) + "."
