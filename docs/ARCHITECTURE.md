# NIFTY Copilot — Structural Framework

How this system is put together and the rules that keep it honest. `PROJECT_PLAN.md`
is the *chronological* record — what we decided and when. This file is the *structural*
one — where things live, how data flows, and what must stay true as the codebase grows.

Read this before adding anything.

---

## 1. The invariants

Five rules. Everything else is implementation detail; these are the reason the system is
worth trusting at all. A change that breaks one of these is a bug even if every test passes.

| # | Invariant | Where it's enforced |
|---|---|---|
| **I1** | **No look-ahead.** A signal is decided on bar `i`'s close and executed at bar `i+1`'s open. Never same-bar, never a future bar. A bar whose window hasn't closed is `provisional` and is never a signal input or archived. | `backtest/engine.py`, `zerodha_provider.is_provisional`; locked by `tests/test_engine.py`, `tests/test_intraday_bars.py`, and `tests/test_pattern_no_lookahead.py` (every pattern re-run on truncated history must agree) |
| **I2** | **Every number shown is computed by deterministic Python.** No LLM ever produces a statistic. If it isn't computed, the UI says "not available" — it does not guess. | Whole `quant/` + `backtest/` stack; `lib/api.ts` has no mock fallbacks; `copilot/guard.py` withholds any LLM answer containing a number not in the computed data, `copilot/prediction_guard.py` withholds forecasts and trade instructions |
| **I3** | **Costs are always applied.** Gross return is never presented as a result. Index and options have separate, realistic cost models. | `backtest/costs.py`, `backtest/options_engine.py`; locked by `tests/test_costs.py` |
| **I4** | **Nothing is "validated" from a single split, or from drift.** A strategy must survive walk-forward folds *and* an untouched holdout, and in both periods beat simply being in the market in the same direction (same mechanics, same costs), with the holdout edge at t ≥ 2. | `backtest/walkforward.py` (`holdout_verdict`); locked by `tests/test_validation_verdict.py` |
| **I5** | **The bar rises with the number of hypotheses tested.** 26 patterns each get one holdout test, so one clearing t = 2 by luck is likely. A trade needs t above the Bonferroni line for that count (≈2.8–2.9), not just 2. | `stats/multiple_comparisons.py` (`required_t`), `briefing/recommendation.py`; `backtest/hypothesis_log.py` keeps the full audit trail |

**And one product rule:** this is a decision-support tool, not a trading system. There is no
broker execution path, and there never will be. The user makes every decision.

---

## 2. Layers and the dependency rule

```
┌──────────────────────────────────────────────────────────┐
│  web/src          Next.js dashboard — display only       │
│                   Computes nothing except chart geometry │
└───────────────────────────┬──────────────────────────────┘
                            │  HTTP, typed in lib/api.ts
┌───────────────────────────▼──────────────────────────────┐
│  api/main.py      FastAPI — routing, caching, validation │
│                   Thin. No business logic lives here.    │
└───────────────────────────┬──────────────────────────────┘
        ┌───────────────────┼───────────────────┐
┌───────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│ briefing/      │ │ backtest/       │ │ options/        │
│ Turns numbers  │ │ Simulation,     │ │ Live chain      │
│ into a verdict │ │ validation      │ │ analytics       │
└───────┬────────┘ └────────┬────────┘ └────────┬────────┘
        └───────────────────┼───────────────────┘
        ┌───────────────────┼───────────────────┐
┌───────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│ quant/         │ │ stats/          │ │ storage/        │
│ Indicators,    │ │ Multiple-       │ │ SQLite: options │
│ regime         │ │ comparisons     │ │ archive, status │
└───────┬────────┘ └─────────────────┘ └─────────────────┘
        │
┌───────▼──────────────────────────────────────────────────┐
│  market_data/     Provider abstraction — the ONLY place   │
│                   that knows where data comes from        │
└──────────────────────────────────────────────────────────┘
```

**The dependency rule: arrows point down, never up.** `quant/` must never import from
`backtest/`; `market_data/` must never import from anything above it. This is what makes
"swap the data provider" a real capability rather than a rewrite — and it's the single
easiest rule to break accidentally.

---

## 3. The pipeline

```
NSE / Yahoo ──▶ market_data/ ──▶ DataFrame (OHLCV)
                                      │
                                      ├──▶ quant/indicators.py ──▶ EMA, RSI, ADX, ATR…
                                      │         │
                                      │         └──▶ quant/regime.py ──▶ TREND_BULL / BEAR / RANGE
                                      │
                                      └──▶ backtest/strategies.py ──▶ boolean signal series
                                                     │
                                                     ▼
                                          backtest/engine.py  (I1 + I3)
                                                     │
                                                     ▼
                                          backtest/metrics.py ──▶ expectancy, PF, drawdown
                                                     │
                            ┌────────────────────────┼────────────────────────┐
                            ▼                        ▼                        ▼
                  research.py                walkforward.py          hypothesis_log.py
                  (rank vs. buy-and-hold)    (folds + holdout, I4)   (count distinct, I5)
                            │                        │                        │
                            │                        ▼                        │
                            │             storage/strategy_status_db.py       │
                            │             (the Playbook — permanent record)   │
                            │                        │                        │
                            └────────────────────────┴────────────────────────┘
                                                     ▼
                                       briefing/recommendation.py
                                       Gate: option APPROVED and t > Bonferroni?
                                                     ▼
                                          CALL / PUT / NO_TRADE
```

Two things to notice, because they're load-bearing:

- **Buy-and-hold is subtracted before ranking.** NIFTY drifts upward structurally, so every
  long strategy looks profitable in raw terms. `research.py` reports `vs_baseline_pct` —
  alpha, not drift. Ranking on raw expectancy is how you fool yourself.
- **The recommendation gate is the last thing, not the first.** A strategy firing today means
  nothing on its own; its option must be APPROVED with t above the Bonferroni bar (I5) to surface.

---

## 4. The strategy lifecycle

This is the core framework. A strategy climbs a ladder; **it can never skip a rung.**

```
  ① IDEA          Research grounding — why should this edge exist?
       │
       ▼
  ② REGISTERED    One entry in STRATEGY_REGISTRY + a signal function.
       │          Now backtestable. Status: untested.
       ▼
  ③ MEASURED      Full-history backtest, costs applied, logged as a hypothesis.
       │          Ranked by alpha vs. buy-and-hold — not raw return.
       ▼
  ④ VALIDATED     Walk-forward folds + untouched holdout (I4).
       │          → APPROVED / CONDITIONAL / REJECTED
       ▼
  ⑤ RECORDED      Written to strategy_status_history. Permanent, timestamped,
       │          never overwritten — so drift is visible as history.
       ▼
  ⑥ ACTIONABLE    Forms today AND its option clears the Bonferroni bar (I5).
                  Only now does it reach the user as CALL or PUT.
```

**Current population of the ladder:** 26 registered (13 symmetric call/put pairs) · 26 validated ·
0 APPROVED · 2 CONDITIONAL (Hammer, Shooting Star — both on <15 holdout trades) · 24 REJECTED.
APPROVED now also requires the holdout edge over baseline to be statistically distinguishable
from luck (t ≥ 2).

Zero APPROVED is a working result, not a failure. The three best baseline-adjusted candidates
were run through full validation and two were rejected outright — which is exactly what the
multiple-comparisons concern predicted, and the reason the ladder exists.

---

## 4b. What the system ranks by

The goal is option profit, not index return. For each pattern the question is: when it forms,
which option does it point to, and what did that option actually make? `pattern_options.py`
tests 45 option choices per pattern (moneyness × min expiry × hold) on real NSE premiums,
**chooses on 2018–2023 only**, and reports profit from 2024 onward, which the choice never saw.
Same verdict rule as I4, with "buying this option with no signal" as the baseline.
`pattern_proximity.py` answers "what could form next" by simulating 225 candidate next-day
candles against every pattern.

**Yardstick: ₹ profit per lot** (today's lot size, 65). Average % return was tried first and
steered almost every pattern to the cheapest far-OTM weekly option — big percentages, little money.

**Current state:** 0 APPROVED · 2 CONDITIONAL (Bollinger Band Reversion → 2% ITM call, 10 days,
+₹3,667/lot vs −₹6,160 with no signal; RSI Overbought Reversal → 2% OTM put, one big winner in 11) ·
24 REJECTED. Both CONDITIONAL on ~11 holdout trades, t < 1.

---

## 5. Module map

| Path | Responsibility | Don't put here |
|---|---|---|
| `market_data/base.py` | `MarketDataProvider` protocol | Anything provider-specific |
| `market_data/{csv,yfinance,zerodha}_provider.py` | One provider each | Indicator math |
| `market_data/nse_bhavcopy.py` | Official NSE F&O archive download/parse | Analysis |
| `market_data/live_quote.py` | Live index quote + market status (15s cache) | Historical fetching |
| `market_data/kite_session.py` | Kite login, daily token (dies ~6 AM IST), secret from `api/.env` | Data fetching |
| `market_data/bar_archive.py` | Local index-bar archive + `ArchiveProvider` (no login needed) | Provisional bars — never stored |
| `quant/indicators.py` | Pure functions: series in, series out | State, I/O, signals |
| `quant/regime.py` | Regime classification | Trade decisions |
| `quant/pipeline.py` | Assembles the analysis payload | New math |
| `backtest/engine.py` | The simulator. **I1 lives here.** | Strategy-specific logic |
| `backtest/costs.py` · `options_engine.py` | Cost models (index / options) | Signals |
| `backtest/strategies*.py` · `pcr_signals.py` | Signal functions + registry | Execution logic |
| `backtest/research.py` | Rank all strategies vs. baseline | Validation verdicts |
| `backtest/walkforward.py` | Folds, holdout, final verdict | Live recommendations |
| `backtest/hypothesis_log.py` | Append-only audit trail (JSON Lines, OS file lock) | Rewriting the file — only ever append |
| `stats/multiple_comparisons.py` | Scaled evidence bar | Strategy logic |
| `backtest/pattern_info.py` | What each pattern checks and the idea behind it | Evidence — the numbers are elsewhere |
| `backtest/pattern_options.py` | Pattern → option choice on dev data → profit on holdout | Picking the option on holdout data |
| `backtest/pattern_proximity.py` | Formed today / could form next close, trigger levels (bisected to ~1 pt), base rate | Forecasts — it's a base rate |
| `copilot/llm_client.py` | Provider-agnostic LLM client (any OpenAI-compatible API; Gemini/Groq presets) | Business logic |
| `copilot/guard.py` | I2 for the LLM: rejects any answer with a number not in the data | Leniency — it's the safety net |
| `copilot/prediction_guard.py` | Second check via TypeSafe Jev: blocks forecasts and trade instructions (no numbers needed) | Blocking when the service is down — it fails open, marked unchecked |
| `copilot/context.py` · `assistant.py` | Compact digest of computed results → explain/ask | Computing anything new |
| `backtest/similarity.py` | Phase 11: 5-feature nearest-neighbour analogs + walk-forward test | More features without evidence they help |
| `backtest/live_patterns.py` | Phase 10: today's candle from 15-min closes → which patterns would form now | Anything final before 15:30 |
| `storage/options_db.py` | Options archive (655 MB, 4.5 M rows) | Strategy verdicts |
| `storage/strategy_status_db.py` | The Playbook — verdict history | Live recomputation |
| `briefing/research_briefing.py` | Rule-based evidence for/against | Verdicts |
| `briefing/recommendation.py` | The gate → CALL/PUT/NO_TRADE | New statistics |
| `briefing/forward_log.py` | Record each final-bar verdict; score it from the next open | Backfilling — ever |
| `storage/forward_log_db.py` | Write-once-per-date recommendation log | Outcomes (computed on read) |
| `web/src/components/ui.tsx` | Shared primitives (Panel, Pill, Stat…) | Feature components |
| `web/src/lib/api.ts` | Typed fetches. **No mock fallbacks (I2).** | Computation |

---

## 6. Data stores

| Store | Contents | Committed? |
|---|---|---|
| `api/data/nifty_options.db` | 4,568,566 option bars · 2,143 trading days · 2018→2026 | No — rebuild via `scripts/backfill_options.py` |
| `api/data/nifty_bars.db` | Kite index bars: 15m 2015-01-09→now (72k), daily 1990→now | No — rebuild/top up via `scripts/backfill_bars.py` |
| `api/data/kite_session.json` | Today's Kite access token (mode 600) | No — recreated by daily login |
| `api/.env` | `KITE_API_KEY`, `KITE_API_SECRET`, `LLM_PROVIDER`, `LLM_API_KEY`, `TYPESAFE_API_KEY` | **Never** — secrets |
| `api/data/copilot_explanations.json` | One saved explanation per trading day | No — regenerated |
| `api/data/forward_log.db` | Each day's verdict, written before its outcome existed | No — and irreplaceable: back it up, it can't be regenerated |
| `api/data/pattern_options.json` | Pattern → option research output | No — `scripts/pattern_options.py` |
| `api/data/strategy_status.db` | Every validation verdict, timestamped | No — regenerated by validation runs |
| `api/backtest/hypothesis_log.jsonl` | Every backtest run ever executed | No — generated data |

All gitignored: they are *generated*, not source. Anything derivable from code and public
data should be reproducible, not committed.

---

## 7. How to extend

**Add a strategy** → write the signal function (DataFrame in, boolean Series out, no
look-ahead), add one `STRATEGY_REGISTRY` entry with `fn`/`params`/`direction`/`option_type`/`label`,
add its PUT mirror if it has one. It now flows through research automatically. Then walk it
up the ladder — registering is rung ②, not rung ⑥.

**Add an indicator** → pure function in `quant/indicators.py`, series in / series out. No I/O,
no state. Add a test if the math has an edge case (warm-up period, division by zero).

**Add a data provider** → implement `MarketDataProvider` in `market_data/`. If you find
yourself importing it directly anywhere outside that package, the abstraction has leaked.

**Add an endpoint** → thin handler in `main.py` that calls into a module. Wrap expensive
work in `cached()`. Add the path to `ENDPOINTS` in `scripts/check_all.sh`, and the typed
fetch to `lib/api.ts`. Handlers that *write* (e.g. `/api/validation/{name}`) stay out of the
smoke test — health checks must never mutate the record.

**Add a check** → a new `section` block in `scripts/check_all.sh` calling `ok`/`bad`.

**Add a daily task** → a step in `api/scripts/daily_job.py`. Each step is independent and must be
safe to re-run. The LaunchAgent (`scripts/install_daily_job.sh`, weekdays 19:30) picks it up;
`--remove` uninstalls it. Log: `api/data/daily_job.log`.

---

## 8. Quality gates

```bash
./scripts/check_all.sh          # everything
./scripts/check_all.sh --fast   # skip endpoint smoke test
```

Python syntax · pytest (39) · ruff (if installed) · `tsc --noEmit` · ESLint · every read-only endpoint.
Exits non-zero on failure, so it drops straight into a pre-commit hook or CI.

The test suite exists because two real bugs were found by hand in one session. Every bug
found from here gets a regression test — that's the rule that keeps the suite meaningful
rather than decorative.

---

## 9. Status and known gaps

**Phases 1–12 complete** (Phase 12 awaiting an API key). Phase 10 is live trigger tracking: during the session, today's candle
is built from completed 15-minute bars (Kite) and every pattern is run on it — "would form if
today closed now", provisional until 15:30. Phase 13+ (journal,
paper observation, deployment) not started. Phase 11, historical similarity: 20 past days nearest
to today on 5 features, shown against the base rate, with a walk-forward test of whether analogs
predict anything (currently: no — t 0.03 over 410 tests; shown as context, not a forecast).

Gaps, stated rather than hidden:

- **The daily job needs the Mac on (or waking) that evening,** and Kite bars only top up on days
  you logged in — the options archive and forward log don't need a login.
- **No revalidation cadence.** A verdict from last month is still shown as current; the schema
  records history but nothing re-checks on a schedule.
- **Phase 7 selection saw the full history.** Validation tests each *rule's* stability, not the
  *selection process*. A clean version re-runs discovery on development data only.
- **`strategy_status_db` has no `max_drawdown_pct` or `regime` column** — both are buried in
  the `full_result_json` blob, so neither is queryable.
- **15-minute data is archived but not yet used.** Every strategy still runs on daily bars;
  no intraday backtest exists yet.
- **Irregular sessions are in the 15m archive** — Diwali Muhurat (~1h, evenings), Saturday special
  sessions, the 2021-02-24 outage day. Real data, but an intraday backtest must exclude or treat
  them separately; they'll distort any time-of-day logic.
- **Daily bars before 1996-04-22 are back-calculated** (1,239 bars — NIFTY didn't trade before
  launch). Fine for context, not for backtests.
- **Kite login is manual, daily.** Nothing refreshes the token automatically, by design — Zerodha
  requires a human login with 2FA.

---

## 10. What this system will not do

No auto-trading. No broker execution API. No LLM-generated statistics. No number on screen
without deterministic code behind it. No "validated" claim from a single backtest. No paid
service signed up for without explicit approval first.

These aren't cautious defaults to be relaxed later — they're the definition of the product.
