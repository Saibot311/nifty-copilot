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
| **I1** | **No look-ahead.** A signal is decided on bar `i`'s close and executed at bar `i+1`'s open. Never same-bar, never a future bar. A bar whose window hasn't closed is `provisional` and is never a signal input or archived. | `backtest/engine.py`, `zerodha_provider.is_provisional`; locked by `tests/test_engine.py`, `tests/test_intraday_bars.py` |
| **I2** | **Every number shown is computed by deterministic Python.** No LLM ever produces a statistic. If it isn't computed, the UI says "not available" — it does not guess. | Whole `quant/` + `backtest/` stack; `lib/api.ts` has no mock fallbacks by design |
| **I3** | **Costs are always applied.** Gross return is never presented as a result. Index and options have separate, realistic cost models. | `backtest/costs.py`, `backtest/options_engine.py`; locked by `tests/test_costs.py` |
| **I4** | **Nothing is "validated" from a single split.** A strategy must survive walk-forward folds *and* an untouched holdout before it can be called APPROVED. | `backtest/walkforward.py` |
| **I5** | **The bar rises with the number of hypotheses tested.** Testing 26 strategies against one dataset means some will look good by luck; the required edge scales accordingly. | `stats/multiple_comparisons.py` + `backtest/hypothesis_log.py` |

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
                                       Gate: expectancy > scaled bar?
                                                     ▼
                                          CALL / PUT / NO_TRADE
```

Two things to notice, because they're load-bearing:

- **Buy-and-hold is subtracted before ranking.** NIFTY drifts upward structurally, so every
  long strategy looks profitable in raw terms. `research.py` reports `vs_baseline_pct` —
  alpha, not drift. Ranking on raw expectancy is how you fool yourself.
- **The recommendation gate is the last thing, not the first.** A strategy firing today means
  nothing on its own; it has to clear the scaled evidence bar (I5) to surface as actionable.

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
  ⑥ ACTIONABLE    Fires today AND clears the scaled evidence bar (I5).
                  Only now does it reach the user as CALL or PUT.
```

**Current population of the ladder:** 26 registered (13 symmetric call/put pairs) · 4 validated ·
0 APPROVED · 2 CONDITIONAL (EMA Pullback, Shooting Star) · 2 REJECTED.

Zero APPROVED is a working result, not a failure. The three best baseline-adjusted candidates
were run through full validation and two were rejected outright — which is exactly what the
multiple-comparisons concern predicted, and the reason the ladder exists.

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
| `backtest/hypothesis_log.py` | Append-only audit trail | Anything read-modify-write without the lock |
| `stats/multiple_comparisons.py` | Scaled evidence bar | Strategy logic |
| `storage/options_db.py` | Options archive (655 MB, 4.5 M rows) | Strategy verdicts |
| `storage/strategy_status_db.py` | The Playbook — verdict history | Live recomputation |
| `briefing/research_briefing.py` | Rule-based evidence for/against | Verdicts |
| `briefing/recommendation.py` | The gate → CALL/PUT/NO_TRADE | New statistics |
| `web/src/components/ui.tsx` | Shared primitives (Panel, Pill, Stat…) | Feature components |
| `web/src/lib/api.ts` | Typed fetches. **No mock fallbacks (I2).** | Computation |

---

## 6. Data stores

| Store | Contents | Committed? |
|---|---|---|
| `api/data/nifty_options.db` | 4,568,566 option bars · 2,143 trading days · 2018→2026 | No — rebuild via `scripts/backfill_options.py` |
| `api/data/nifty_bars.db` | Kite index bars: 15m 2015-01-09→now (72k), daily 1990→now | No — rebuild/top up via `scripts/backfill_bars.py` |
| `api/data/kite_session.json` | Today's Kite access token (mode 600) | No — recreated by daily login |
| `api/.env` | `KITE_API_KEY`, `KITE_API_SECRET` | **Never** — secrets |
| `api/data/strategy_status.db` | Every validation verdict, timestamped | No — regenerated by validation runs |
| `api/backtest/hypothesis_log.json` | Every backtest run ever executed | No — generated data |

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

**Phases 1–9 complete.** Phase 10+ (live analysis, similarity engine, LLM copilot, journal,
paper observation, deployment) not started.

Gaps, stated rather than hidden:

- **22 of 26 strategies are unvalidated** — sitting at rung ③. Breadth without depth.
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
