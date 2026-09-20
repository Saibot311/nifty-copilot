"""Provider-agnostic LLM client — the copilot's equivalent of
MarketDataProvider. Talks to any OpenAI-compatible chat-completions
endpoint, so switching provider is a config change in api/.env:

    LLM_PROVIDER=gemini   # or groq, or custom (then set LLM_BASE_URL)
    LLM_API_KEY=...
    LLM_MODEL=...         # optional; a sensible default per provider

The key is read from api/.env (gitignored) and never logged or returned.
"""

import requests

from market_data.kite_session import _env

PROVIDERS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-3.6-flash"},
    "groq": {"base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-120b"},
}
TIMEOUT_S = 60


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def config() -> dict:
    provider = (_env("LLM_PROVIDER") or "gemini").lower()
    preset = PROVIDERS.get(provider, {})
    return {
        "provider": provider,
        "base_url": (_env("LLM_BASE_URL") or preset.get("base_url") or "").rstrip("/"),
        "model": _env("LLM_MODEL") or preset.get("model"),
        "has_key": bool(_env("LLM_API_KEY")),
    }


# Gemini 3.x and similar are reasoning models: they spend tokens thinking
# before any visible text, and a tight cap returns an empty message with
# finish_reason 'length'. Budget for the thinking, not just the answer.
def chat(messages: list[dict], max_tokens: int = 4000) -> str:
    cfg = config()
    key = _env("LLM_API_KEY")
    if not key or not cfg["base_url"] or not cfg["model"]:
        raise LLMNotConfigured("Set LLM_PROVIDER and LLM_API_KEY in api/.env (see copilot/llm_client.py).")
    try:
        resp = requests.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": cfg["model"], "messages": messages, "max_tokens": max_tokens, "temperature": 0.2},
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise LLMError(f"Could not reach {cfg['provider']}: {type(e).__name__}") from e
    if resp.status_code == 429:
        raise LLMError(f"{cfg['provider']} free-tier rate limit reached — try again in a minute.")
    if resp.status_code >= 400:
        detail = resp.text[:300].replace(key, "***")
        raise LLMError(f"{cfg['provider']} returned HTTP {resp.status_code}: {detail}")
    try:
        choice = resp.json()["choices"][0]
    except (ValueError, KeyError, IndexError) as e:
        raise LLMError(f"Unexpected response shape from {cfg['provider']}") from e
    text = (choice.get("message") or {}).get("content") or ""
    if not text.strip():
        raise LLMError(
            f"{cfg['provider']} returned no text (finish_reason: {choice.get('finish_reason')}). "
            "If it is 'length', the model used the whole budget thinking — raise max_tokens."
        )
    return text
