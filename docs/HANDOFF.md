# Handoff — read this first

Written 2026-09-21. Start here, then `ARCHITECTURE.md` (how it's built, the five
invariants) and `PROJECT_PLAN.md` (what was decided and when, newest first).

## What this is

NIFTY 50 options **decision support** for one beginner trader. It never trades: no
broker execution path, and the user makes every decision. Its value is refusing to
manufacture a signal — most days it says NO TRADE, and that is the product working.

## Where it stands

**Phases 1–12 done.** Phase 13 (trade journal) is next; 14–15 (paper observation,
deployment) after.

**The honest result so far: nothing has a proven edge.** 26 patterns, each judged
once on 2024–26 option data it never saw: **0 approved, 2 conditional, 24 rejected.**
Two apparent edges turned out to be bugs (see Traps). The forward log is the real
test now, and it needs calendar time.

## Running it

```bash
./scripts/check_all.sh          # 24 checks, 145 tests — run before and after changes
./scripts/check_all.sh --fast   # skips endpoint checks (no servers needed)
```

The copilot's three Jev-backed guards are judged by a real model, so they have
their own harness — it costs tokens and is not in `check_all.sh`. Re-run it after
changing any question, criterion or threshold:

```bash
cd api && .venv/bin/python scripts/check_guards.py   # or: ... forecast | claims | routes
```

Dev servers are started through the harness preview tool, never `npm`/`uvicorn` in a
shell: `nifty-copilot-api` (:8000) and `nifty-copilot-web` (:3000). They stop when the
session idles; just start them again. First page load after a restart takes ~15-60s
because every cache is cold.

**Daily:** a LaunchAgent runs `api/scripts/daily_job.py` at 19:30 on weekdays (forward
log, archive top-ups, option research). Verified running unattended. Logs:
`api/data/daily_job.log`. Remove with `./scripts/install_daily_job.sh --remove`.

**Zerodha login expires every day at ~6 AM IST.** Without it, 15-minute bars and live
tracking fall back or skip; everything else still works.
Re-login: <http://127.0.0.1:8000/api/zerodha/login>

## Secrets

All in `api/.env` (gitignored, never in chat or commits): `KITE_API_KEY`,
`KITE_API_SECRET`, `LLM_API_KEY` (Gemini free tier), `LLM_PROVIDER`, `TYPESAFE_API_KEY` (Jev).
To add one, prompt for it — never put a key in the command text:

```bash
read -s "k?Paste key: " && echo "NAME=$k" >> ~/Documents/NIFTY-Trading-App/api/.env && unset k && echo " saved"
```

## Data on disk (all gitignored, all regenerable except one)

| File | What | Rebuild |
|---|---|---|
| `api/data/nifty_options.db` | 4.57M option bars, 2018→now (655 MB) | `scripts/backfill_options.py` |
| `api/data/nifty_bars.db` | 15-min bars from 2015-01-09; daily from 1990 | `scripts/backfill_bars.py` |
| `api/data/pattern_options.json` | Pattern → option research output | `scripts/pattern_options.py` |
| `api/data/strategy_status.db` | Validation verdict history | `scripts/validate_all.py --all` |
| **`api/data/forward_log.db`** | **Each day's verdict, written before the outcome** | **Cannot be rebuilt — back it up** |

## Traps that already cost real time

- **pandas 3:** `bool_series.shift(1).fillna(False)` is object dtype, and `~` on it is
  integer bit-flip (`~True == -2`, truthy). Use `shift(1, fill_value=False)`. This made
  EMA Pullback fire every day of a trend for six phases.
- **Centered rolling windows look into the future.** A `rolling(5, center=True)` swing
  filter leaked two bars and made two patterns look profitable.
- **Any cached value that calls another cached value** needs per-key locks — a single
  global lock deadlocked the recommendation.
- **Gemini 3.x think before writing.** Too small a `max_tokens` returns empty content
  with `finish_reason: "length"` and HTTP 200.
- **Ranking options by % return** picks ₹20 lottery tickets. Rank by ₹ per lot.
- **A guard that judges a whole block as one claim averages a lie away.** Split on
  lines as well as sentences, or a false line hides between two true ones.
- **When a guard misfires, fix the question, not the threshold.** Two false alarms
  went from 0.32 and 0.31 to 0.15 and 0.07 on one added criterion; moving the
  threshold would have hidden them and blinded the guard elsewhere.
- Every bug found gets a regression test. That rule is why the suite is worth having.

## Next steps

1. **Phase 13 — trade journal.** Record what the user actually did (take / skip / wait)
   against what the system said. Pairs with the forward log. No API needed.
2. **Let the forward log accrue.** It is the only out-of-sample evidence that can't be
   fooled by better backtesting.
3. **Intraday research.** 11.7 years of 15-minute bars are archived and unused. Option
   P&L can't be backtested intraday (the archive is end-of-day), so index-level only.
4. **Copilot: slice context per route.** `router.py` already classifies every
   question and records the route; acting on it (sending only the relevant part of
   the digest) needs its own labelled cases, because a narrower context also
   narrows what the answer is allowed to mention.

## Ground rules that must not slip

Never invent a number; never predict; never advise a trade; costs always applied;
nothing is "validated" from one split; the evidence bar rises with the number of
hypotheses tested. If a change would break one of those, it's a bug even if the tests
pass. Paid services are flagged and approved before use, never signed up for silently.
