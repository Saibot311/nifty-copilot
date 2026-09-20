"""Mechanical enforcement of invariant I2 for the copilot: the LLM may
explain numbers, never produce them.

Every number in an answer must match a number in the data it was given (or
in the user's own question), allowing for display rounding — 23270.6 may
appear as 23,271 or 23,270.60, -1170 as "₹1,170" (sign carried by words
like "lost"). Small counting words ("the last 5 days", "2 patterns") are
allowed up to SMALL_INT. Anything else is unverified, and the answer is
rejected rather than shown.
"""

import json
import re

SMALL_INT = 10

# 23,270.60 / -1.2 / 1,170 / 0.05 / 2026 — a number with optional sign,
# Indian or Western thousands separators, and decimals.
_NUM = re.compile(r"(?<![\w.])[-+−]?\d[\d,]*(?:\.\d+)?")


def _to_float(token: str) -> float | None:
    t = token.replace(",", "").replace("−", "-").replace("+", "")
    try:
        return float(t)
    except ValueError:
        return None


def numbers_in_text(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text):
        v = _to_float(m.group())
        if v is not None:
            out.append(v)
    return out


def numbers_in_data(data) -> set[float]:
    found: set[float] = set()

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            found.add(float(x))
        elif isinstance(x, str):
            found.update(numbers_in_text(x))
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(k)
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(json.loads(json.dumps(data, default=str)))
    return found


def _matches(value: float, source: float) -> bool:
    """value is an acceptable rendering of source: equal up to sign, and to
    whatever precision `value` was written at (0-3 decimals), or source is a
    fraction rendered as a percentage (0.583 -> 58%). Only true fractions
    (|source| <= 1) get the x100 reading — otherwise the "30" in "15:30"
    would vouch for an invented 3,000."""
    candidates = [abs(source)] + ([abs(source) * 100] if abs(source) <= 1 else [])
    for s in candidates:
        for places in (0, 1, 2, 3):
            if round(s, places) == abs(value) and abs(s - abs(value)) <= 0.5 * 10**-places + 1e-9:
                return True
    return False


def unverified_numbers(answer: str, data, question: str = "") -> list[float]:
    allowed = numbers_in_data(data) | set(numbers_in_text(question))
    bad = []
    for v in numbers_in_text(answer):
        if float(v).is_integer() and 0 <= abs(v) <= SMALL_INT:
            continue
        if not any(_matches(v, s) for s in allowed):
            bad.append(v)
    return bad
