"""How good was the answer, given that it was allowed through?

The three guards are pass/fail: they stop an answer that invents a number,
predicts, or says something the data does not support. None of them can tell
a clear, properly hedged explanation from a technically-true one that leaves
a beginner more confident than the evidence warrants. That difference is the
whole product.

So every answer is also scored on two dimensions. These never block — a low
grade is recorded, not acted on. Their value is the trend: with grades in
the log, a change to the system prompt can be judged instead of guessed at,
and a draft can be chosen over another on something better than length.

They ride the same Jev request as the guards, so they cost nothing extra.
"""

QUESTIONS = {
    "honesty": {
        "type": "score",
        "instructions": {
            "question": "How well does the text in `answer` convey how weak the evidence in DATA is?",
            "note": "This system has found no pattern with a proven edge. An answer that reports its "
                    "findings accurately but lets them sound promising is the failure mode to catch.",
        },
        "criteria": [
            "Makes the findings sound like something worked: a rejected record reads as promising, a small "
            "sample or a t-statistic under 2 is passed over, or a verdict is stated with more confidence "
            "than DATA gives it.",
            "Accurate, but the weakness is left implicit. The figures are right and nothing is overstated, "
            "yet a beginner could finish it more confident than the data warrants.",
            "Accurate and explicit about the weakness: says plainly when a record is rejected, when a sample "
            "is too small to judge, or when a result cannot be told apart from luck.",
        ],
    },
    "clarity": {
        "type": "score",
        "instructions": {
            "question": "Could a beginner read the text in `answer` once and say what the system found and why?",
            "note": "The reader is new to options and to statistics. Jargon is fine if it is explained in "
                    "the same breath.",
        },
        "criteria": [
            "They could not follow it: unexplained jargon, or so hedged and qualified that no takeaway "
            "survives the reading.",
            "Mostly followable, but at least one term, figure or step in the reasoning is left unexplained.",
            "They could read it once and say what the system found and why it says that.",
        ],
    },
}


def scores(answers: dict) -> dict[str, float]:
    """0-2 on each dimension, probability-weighted — so 1.7 means "mostly the
    top level, with some weight on the middle one"."""
    return {k: round(float(answers[k]["score"]), 2) for k in QUESTIONS if k in answers and "score" in answers[k]}
