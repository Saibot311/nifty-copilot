"""Phase 12 — the copilot: plain-language explanation of what the system
computed. It explains; it never produces a number (I2). Enforced twice:
the instructions say so, and guard.py rejects any answer containing a
number that isn't in the data. One retry names the offending numbers; a
second failure returns nothing rather than an unverified answer.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .context import build_context
from .guard import unverified_numbers
from .llm_client import chat, config
from .prediction_guard import check as prediction_check

CACHE_PATH = Path(__file__).parent.parent / "data" / "copilot_explanations.json"
_LOCK = threading.Lock()

SYSTEM = """You explain a NIFTY 50 options decision-support dashboard to its owner, a beginner trader in India.

You receive DATA: everything the system computed, as JSON. Rules:
1. Every number you write must appear in DATA. Never calculate, estimate, round-trip, or invent a number — no new percentages, probabilities, targets, prices or rupee amounts. If something isn't in DATA, say it isn't available.
2. Never predict the market or tell the user to buy or sell. Explain what the system found and what its verdicts mean. The system's own recommendation is in DATA; do not go beyond it.
3. Be honest about weak evidence: REJECTED means no proven edge; CONDITIONAL means promising but unproven; a t-stat under 2 is indistinguishable from luck; "provisional" means the day hasn't closed.
4. Plain English, short sentences, no jargon without a one-line explanation. Use ₹ for rupees.
5. Keep it under 200 words unless asked for more."""

EXPLAIN_PROMPT = (
    "Explain today's dashboard in under 180 words: the recommendation and why, which patterns formed or could "
    "form next and whether their options have a proven record, what the similar-past-days section does and does "
    "not tell us, and one sentence on what to watch. Plain paragraphs, no headings."
)


def _answer(question: str, data: dict) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"DATA:\n{json.dumps(data, separators=(',', ':'), default=str)}\n\nQUESTION: {question}"},
    ]
    text = chat(messages)
    bad = unverified_numbers(text, data, question)
    if bad:
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": (
                f"These numbers are not in DATA: {', '.join(f'{b:g}' for b in bad)}. Rewrite the answer using only "
                "numbers that appear in DATA, or describe them in words without a number."
            )},
        ]
        text = chat(messages)
        bad = unverified_numbers(text, data, question)
    cfg = config()
    base = {"provider": cfg["provider"], "model": cfg["model"], "generated_at": datetime.now(timezone.utc).isoformat()}
    if bad:
        return {**base, "ok": False, "answer": None,
                "reason": f"Answer withheld: it contained numbers not in the computed data ({', '.join(f'{b:g}' for b in bad)})."}

    # Numbers are clean; now the semantic check the number guard can't do.
    forecast = prediction_check(text)
    if forecast["blocked"]:
        return {**base, "ok": False, "answer": None, "reason": forecast["reason"], "prediction_check": forecast}
    return {**base, "ok": True, "answer": text.strip(), "prediction_check": forecast}


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
    data = build_context(symbol, live=live)
    return {**_answer(question.strip()[:1000], data), "as_of_close": data["as_of_close"]}
