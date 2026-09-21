"""Phase 12 — the copilot: plain-language explanation of what the system
computed. It explains; it never produces a number (I2).

Three guards, cheapest first:
  guard.py         local, deterministic — every number must be in DATA
  review.py        one Jev call — no forecast, no trade advice, and every
                   sentence backed by DATA
  router.py        before any of it, on a user question: refuse what this
                   dashboard has no data for, without calling the model

One retry names everything wrong with the draft at once; a second failure
returns nothing rather than an unverified answer. The number check runs
first and short-circuits the Jev call, so a draft that is already going to
be rewritten is not also paid for semantically.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .context import build_context
from .guard import unverified_numbers
from .llm_client import chat, config
from .review import review_answer
from .router import DECLINE, route as route_question

CACHE_PATH = Path(__file__).parent.parent / "data" / "copilot_explanations.json"
_LOCK = threading.Lock()

SYSTEM = """You explain a NIFTY 50 options decision-support dashboard to its owner, a beginner trader in India.

You receive DATA: everything the system computed, as JSON. Rules:
1. Every number you write must appear in DATA. Never calculate, estimate, round-trip, or invent a number — no new percentages, probabilities, targets, prices or rupee amounts. If something isn't in DATA, say it isn't available.
2. Every factual statement you make must be backed by DATA. Do not add market context, history or general trading lore that isn't in DATA, however true it sounds.
3. Never predict the market or tell the user to buy or sell. Explain what the system found and what its verdicts mean. The system's own recommendation is in DATA; do not go beyond it.
4. Be honest about weak evidence: REJECTED means no proven edge; CONDITIONAL means promising but unproven; a t-stat under 2 is indistinguishable from luck; "provisional" means the day hasn't closed.
5. Plain English, short sentences, no jargon without a one-line explanation. Use ₹ for rupees. Plain text only: no markdown, no **bold**, no headings, no bullet characters.
6. Keep it under 200 words unless asked for more."""

EXPLAIN_PROMPT = (
    "Explain today's dashboard in under 180 words: the recommendation and why, which patterns formed or could "
    "form next and whether their options have a proven record, what the similar-past-days section does and does "
    "not tell us, and one sentence on what to watch. Plain paragraphs, no headings."
)


def _problems(text: str, data: dict, question: str) -> tuple[list[str], list[float], dict]:
    """What is wrong with this draft: (instructions to fix, bad numbers, review).

    An invented number is fatal on its own, so the Jev call is skipped when
    one is found — this draft is being rewritten either way.
    """
    bad = unverified_numbers(text, data, question)
    if bad:
        return ([
            f"These numbers are not in DATA: {', '.join(f'{b:g}' for b in bad)}. Rewrite using only numbers that "
            "appear in DATA, or describe them in words without a number."
        ], bad, {"checked": False, "blocked": False, "reason": "not reached — numbers failed first"})
    review = review_answer(text, data)
    return (review["problems"], [], review)


def _answer(question: str, data: dict) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"DATA:\n{json.dumps(data, separators=(',', ':'), default=str)}\n\nQUESTION: {question}"},
    ]
    text = chat(messages)
    problems, bad, review = _problems(text, data, question)
    if problems:
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "Rewrite the whole answer. Fix all of this:\n"
                                        + "\n".join(f"- {p}" for p in problems)},
        ]
        text = chat(messages)
        problems, bad, review = _problems(text, data, question)

    cfg = config()
    base = {"provider": cfg["provider"], "model": cfg["model"],
            "generated_at": datetime.now(timezone.utc).isoformat(), "review": review}
    if bad:
        return {**base, "ok": False, "answer": None,
                "reason": f"Answer withheld: it contained numbers not in the computed data ({', '.join(f'{b:g}' for b in bad)})."}
    if problems:
        return {**base, "ok": False, "answer": None, "reason": review["reason"]}
    return {**base, "ok": True, "answer": text.strip()}


def explain_today(symbol: str = "^NSEI", live: dict | None = None) -> dict:
    """One explanation per trading day, saved — reloading the page costs no
    extra API calls. Live data is left out so the saved answer stays true."""
    data = build_context(symbol)
    key = f"{symbol}:{data['as_of_close']}"
    with _LOCK:
        saved = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
        if key in saved and saved[key].get("ok"):
            return {**saved[key], "cached": True}
    result = {**_answer(EXPLAIN_PROMPT, data), "as_of_close": data["as_of_close"]}
    if result["ok"]:
        with _LOCK:
            saved = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
            saved[key] = result
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(json.dumps(saved, indent=1))
    return {**result, "cached": False}


def ask(question: str, symbol: str = "^NSEI", live: dict | None = None) -> dict:
    question = question.strip()[:1000]
    routed = route_question(question)
    if routed.get("off_topic"):
        # Refused by code, not by the model: nothing was generated, so there
        # is nothing to guard.
        cfg = config()
        return {"provider": cfg["provider"], "model": None, "ok": True, "answer": DECLINE,
                "generated_at": datetime.now(timezone.utc).isoformat(), "route": routed,
                "review": {"checked": False, "blocked": False, "reason": "no model answer to check"}}
    data = build_context(symbol, live=live)
    return {**_answer(question, data), "as_of_close": data["as_of_close"], "route": routed}
