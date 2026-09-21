"""Shared client for TypeSafe's Jev (System One) — the copilot's semantic
guard rail.

Jev returns typed judgments (a probability, a chosen label) rather than
prose, which is what makes it usable inside a guard: code reads a number and
decides. It never writes a word the user sees and never produces a figure the
dashboard shows (I2) — it only judges text that Gemini already wrote.

Independent questions over the same state are asked in one request, so a
single call covers every check we run on an answer.

Every call fails open. A guard that is down must not take the copilot down
with it: the answer is marked unchecked and the number guard still applies.
"""

import requests

from market_data.kite_session import _env

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_S = 20


class JevUnavailable(RuntimeError):
    """No key, or the service did not answer. Callers skip, never block."""


def available() -> bool:
    return bool(_env("TYPESAFE_API_KEY"))


def ask(state, questions: dict) -> dict:
    """Returns the `answers` map. Raises JevUnavailable for anything else —
    the error text never carries the key or the response body."""
    key = _env("TYPESAFE_API_KEY")
    if not key:
        raise JevUnavailable("no TYPESAFE_API_KEY — check skipped")
    if not questions:
        return {}
    try:
        resp = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"state": state, "model": MODEL, "questions": questions},
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["answers"]
    except Exception as e:
        raise JevUnavailable(f"check unavailable ({type(e).__name__}) — skipped") from e


def probabilities(answer: dict) -> dict[str, float]:
    """Choice answers carry a distribution; reading the spread rather than
    the winning label is what lets a caller set its own threshold."""
    return {k: float(v) for k, v in (answer.get("probabilities") or {}).items()}
