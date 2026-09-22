"""The copilot: plain-language explanation of what the system computed. It
explains; it never produces a number (I2).

Guards, cheapest first:
  router.py   before anything, on a user question: refuse what this
              dashboard has no data for without calling the model, and
              choose which view of the system the answer is built from
  guard.py    local, deterministic — every number must be in DATA
  review.py   one Jev call — no forecast, no trade advice, every sentence
              backed by DATA, and two grades that never block

One retry names everything wrong with the draft at once; a second failure
returns nothing rather than an unverified answer. The number check runs
first and short-circuits the Jev call, so a draft already being rewritten is
not also paid for semantically.

The daily explanation is written twice and the better-graded one kept — it
is read every day and costs one extra call a day. A typed question is
written once.

It is also composed a third time, in Python, by composer.py. That version
is not shown; it is graded by the same judge and logged beside the model's,
so the question "does this still need a language model?" is answered by the
record rather than by opinion. It does become the answer when the provider
is down, which is strictly safer than an error: it cannot invent anything.

Every answer, shown or withheld, goes to storage/copilot_log_db.py. A guard
with no record is a guard nobody can tune.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from storage.copilot_log_db import record as record_answer

from .composer import compose
from .context import build_context
from .guard import unverified_numbers
from .llm_client import LLMError, LLMNotConfigured, chat, config
from .review import review_answer
from .router import DECLINE, route as route_question

CACHE_PATH = Path(__file__).parent.parent / "data" / "copilot_explanations.json"
_LOCK = threading.Lock()

# The one answer read every day, so it is worth a second draft. A typed
# question gets one: the guards already decide whether it is safe, and the
# grades only decide which of two safe answers reads better.
EXPLAIN_DRAFTS = 2

SYSTEM = """You explain a NIFTY 50 options decision-support dashboard to its owner, a beginner trader in India.

You receive DATA: everything the system computed, as JSON. Rules:
1. Every number you write must appear in DATA. Never calculate, estimate, round-trip, or invent a number — no new percentages, probabilities, targets, prices or rupee amounts. If something isn't in DATA, say it isn't available. A fraction in DATA may be written as a percentage — 0.71 as 71% — which is the one conversion allowed.
2. Every factual statement you make must be backed by DATA. Do not add market context, history or general trading lore that isn't in DATA, however true it sounds.
3. Never predict the market or tell the user to buy or sell. Explain what the system found and what its verdicts mean. The system's own recommendation is in DATA; do not go beyond it.
4. Be honest about weak evidence: REJECTED means no proven edge; CONDITIONAL means it cleared the significance bar but on too few trades to trust; a t-stat below its bar (about 2, higher for small samples) is indistinguishable from luck; "provisional" means the day hasn't closed.
5. Never describe a way of making money without the risk that comes with it. If others profit by selling options, say they are paid for crash risk and when that risk hit (the data has it); if institutions profit through algorithms, say that edge comes from speed and scale individuals do not have. Nothing should read as a strategy to imitate.
6. Plain English, short sentences, no jargon without a one-line explanation. Use ₹ for rupees. Plain text only: no markdown, no **bold**, no headings, no bullet characters.
7. Keep it under 200 words unless asked for more."""

EXPLAIN_PROMPT = (
    "Explain today's dashboard in under 180 words: the recommendation and why, which patterns formed or could "
    "form next and whether their options have a proven record, what the similar-past-days section does and does "
    "not tell us, and one sentence on what to watch. Plain paragraphs, no headings."
)


def _evaluate(text: str, data: dict, question: str) -> dict:
    """A draft and everything known about it.

    An invented number is fatal on its own, so the Jev call is skipped when
    one is found — this draft is being rewritten either way.
    """
    bad = unverified_numbers(text, data, question)
    if bad:
        return {"text": text, "bad_numbers": bad, "review": {
            "checked": False, "blocked": False, "grades": {},
            "reason": "not reached — numbers failed first"}, "problems": [
            f"These numbers are not in DATA: {', '.join(f'{b:g}' for b in bad)}. Rewrite using only numbers that "
            "appear in DATA, or describe them in words without a number."]}
    review = review_answer(text, data)
    return {"text": text, "bad_numbers": [], "review": review, "problems": review["problems"]}


def _rank(attempt: dict) -> tuple:
    """Clean first, then better graded. A withheld answer is worse than any
    shown one however well it reads."""
    grades = attempt["review"].get("grades") or {}
    return (not attempt["problems"], grades.get("honesty", 0) + grades.get("clarity", 0))


def _answer(question: str, data: dict, drafts: int = 1, kind: str = "ask", route: str | None = None) -> dict:
    base = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"DATA:\n{json.dumps(data, separators=(',', ':'), default=str)}\n\nQUESTION: {question}"},
    ]
    attempts = [_evaluate(chat(base), data, question) for _ in range(max(1, drafts))]
    best = max(attempts, key=_rank)
    written = len(attempts)

    if best["problems"]:
        messages = base + [
            {"role": "assistant", "content": best["text"]},
            {"role": "user", "content": "Rewrite the whole answer. Fix all of this:\n"
                                        + "\n".join(f"- {p}" for p in best["problems"])},
        ]
        # The rewrite is listed first so that it wins a tie: it is the one
        # that saw the feedback, and reporting the draft that preceded it
        # would hide what the model was actually told.
        best = max([_evaluate(chat(messages), data, question), best], key=_rank)
        written += 1

    cfg = config()
    review = best["review"]
    result = {
        "provider": cfg["provider"], "model": cfg["model"], "drafts": written,
        "generated_at": datetime.now(timezone.utc).isoformat(), "review": review,
        "grades": review.get("grades") or {},
    }
    if best["bad_numbers"]:
        result |= {"ok": False, "answer": None, "reason": (
            "Answer withheld: it contained numbers not in the computed data "
            f"({', '.join(f'{b:g}' for b in best['bad_numbers'])}).")}
    elif best["problems"]:
        result |= {"ok": False, "answer": None, "reason": review["reason"]}
    else:
        result |= {"ok": True, "answer": best["text"].strip()}

    _log(result, kind=kind, question=question, route=route, as_of=data.get("as_of_close"),
         bad_numbers=best["bad_numbers"], review=review)
    return result


def _log(result: dict, *, kind: str, question: str, route: str | None, as_of: str | None,
         bad_numbers: list, review: dict, outcome: str | None = None, method: str = "gemini") -> None:
    """Never lets a logging problem cost the user their answer."""
    try:
        record_answer({
            "kind": kind, "question": question, "route": route, "as_of_close": as_of, "method": method,
            "drafts": result["drafts"], "outcome": outcome or ("shown" if result["ok"] else "withheld"),
            "reason": None if result["ok"] else result["reason"],
            "bad_numbers": bad_numbers, "unsupported": review.get("unsupported") or [],
            "scores": review.get("scores") or {}, "grades": review.get("grades") or {},
            "answer": result.get("answer"),
        })
    except Exception:
        pass


def composed_explanation(data: dict) -> dict:
    """The Python-written explanation, graded like any other answer.

    It goes through the same guards deliberately. It should never be
    blocked — every number in it came from `data` — so if it ever is, either
    a template says something the data does not support or a guard is wrong.
    Both are worth knowing, which is why it is checked rather than trusted.
    """
    text = compose(data)
    review = review_answer(text, data)
    return {
        "provider": "python", "model": None, "drafts": 0, "method": "composed",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review": review, "grades": review.get("grades") or {},
        "ok": not review["blocked"],
        "answer": None if review["blocked"] else text,
        "reason": review["reason"] if review["blocked"] else None,
    }


def explain_today(symbol: str = "^NSEI", live: dict | None = None) -> dict:
    """One explanation per trading day, saved — reloading the page costs no
    extra API calls. Live data is left out so the saved answer stays true."""
    data = build_context(symbol, scope="today")
    key = f"{symbol}:{data['as_of_close']}"
    with _LOCK:
        saved = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
        if key in saved and saved[key].get("ok"):
            return {**saved[key], "cached": True}

    shadow = composed_explanation(data)
    try:
        result = {**_answer(EXPLAIN_PROMPT, data, drafts=EXPLAIN_DRAFTS, kind="explain"),
                  "as_of_close": data["as_of_close"], "method": "gemini"}
        _log(shadow, kind="explain", question=EXPLAIN_PROMPT, route=None,
             as_of=data["as_of_close"], bad_numbers=[], review=shadow["review"],
             outcome="shadow", method="composed")
    except (LLMError, LLMNotConfigured) as e:
        if not shadow["ok"]:
            raise
        # Serving the composed explanation beats serving an error: it was
        # assembled from the same computed data and cannot invent anything.
        result = {**shadow, "as_of_close": data["as_of_close"],
                  "fallback_from": f"{config()['provider']} unavailable ({type(e).__name__})"}
        _log(result, kind="explain", question=EXPLAIN_PROMPT, route=None,
             as_of=data["as_of_close"], bad_numbers=[], review=shadow["review"], method="composed")
    # Only a model answer is worth saving. The composed fallback costs
    # nothing to rebuild, and caching it would make one transient 503 the
    # explanation for the rest of the day.
    if result["ok"] and result.get("method") != "composed":
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
        result = {"provider": cfg["provider"], "model": None, "ok": True, "answer": DECLINE, "drafts": 0,
                  "generated_at": datetime.now(timezone.utc).isoformat(), "route": routed, "grades": {},
                  "review": {"checked": False, "blocked": False, "reason": "no model answer to check"}}
        # "declined", not "shown": no model wrote it, so it is not evidence
        # about the guards or the prose.
        _log(result, kind="ask", question=question, route="off_topic", as_of=None,
             bad_numbers=[], review={}, outcome="declined")
        return result
    # The route decides which view of the system the answer is built from;
    # an unsure classification means scope is None and everything is sent.
    data = build_context(symbol, live=live, scope=routed.get("scope"))
    return {**_answer(question, data, kind="ask", route=routed.get("route")),
            "as_of_close": data["as_of_close"], "route": routed}
