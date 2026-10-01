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
| **I1** | **No look-ahead.** A signal is decided on bar `i`'s close and executed at bar `i+1` — the index engine at its open, the option research and the paper book at its *close* (the archive holds one price per contract per day). Never same-bar, never a future bar. A bar whose window hasn't closed is `provisional` and is never a signal input or archived. | `backtest/engine.py`, `zerodha_provider.is_provisional`; locked by `tests/test_engine.py`, `tests/test_intraday_bars.py`, and `tests/test_pattern_no_lookahead.py` (every pattern re-run on truncated history must agree) |
| **I2** | **Every number shown is computed by deterministic Python.** No LLM ever produces a statistic. If it isn't computed, the UI says "not available" — it does not guess. | Whole `quant/` + `backtest/` stack; `lib/api.ts` has no mock fallbacks; `copilot/composer.py` writes the daily explanation in Python, so it cannot invent one at all; `copilot/guard.py` withholds any LLM answer containing a number not in the computed data; `copilot/review.py` withholds forecasts, trade instructions and any sentence the computed data does not support |
| **I3** | **Costs are always applied.** Gross return is never presented as a result. Index and options have separate, realistic cost models; an option trade's buy leg is charged on the premium paid and its sale on the premium received (since 2026-09-24), in rupees on the lots traded: a flat ₹20 an order plus the STT and exchange charges in force on each leg's own date (since 2026-09-27). An index trade pays both legs in rupees on one NIFTY lot, each at its own price and at the STT and exchange charges in force on its own date, with a short's sale at entry (since 2026-09-27). | `backtest/costs.py`, `backtest/options_engine.py`; locked by `tests/test_costs.py`, `tests/test_futures_costs.py` |
| **I4** | **Nothing is "validated" from a single split, or from drift.** A strategy must survive walk-forward folds *and* an untouched holdout, and in both periods beat simply being in the market in the same direction (same mechanics, same costs), with the holdout edge clearing the significance bar (and, to reach the recommendation, the Bonferroni bar of I5). | `backtest/walkforward.py` (`holdout_verdict`); locked by `tests/test_validation_verdict.py` |
| **I5** | **The bar rises with the number of hypotheses tested — and with how few trades a result rests on.** 26 patterns each get one holdout test, so one clearing t = 2 by luck is likely. A trade needs t above the Bonferroni line for that count, computed from Student's t at the pattern's own degrees of freedom (2.79 in the large-sample limit, 3.55 on 11 trades). The t itself is Welch's, because the no-signal baseline is a sample too. | `stats/multiple_comparisons.py` (`required_t`), `stats/student_t.py`, `backtest/walkforward.py` (`significance_bar`, `welch_t_stat`), `backtest/family.py` (the count: every family that has looked at the holdout — 53 on 2026-09-24), `briefing/recommendation.py`; `backtest/hypothesis_log.py` keeps the full audit trail |

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
0 APPROVED · 0 CONDITIONAL · 26 REJECTED (the two earlier CONDITIONALs were a verdict-ladder bug; see AUDIT.md).
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

**Current state:** 0 APPROVED · 0 CONDITIONAL · 26 REJECTED. The closest, Bollinger Band Reversion
(2% ITM call, 10 days), made +₹8,267/lot on 13 holdout trades against −₹5,669 with no signal, but
t = 1.36 against a bar near 3.4 at that sample size. Six structural hypotheses
(`structural_research.py`) were then tested the same way as bought options: also 0 of 6.

---

## 5. Module map

| Path | Responsibility | Don't put here |
|---|---|---|
| `market_data/base.py` | `MarketDataProvider` protocol | Anything provider-specific |
| `market_data/{csv,yfinance,zerodha}_provider.py` | One provider each | Indicator math |
| `market_data/nse_bhavcopy.py` | Official NSE F&O archive download/parse | Analysis |
| `market_data/kite_quotes.py` | Live index and option-contract prices from a Kite session; instrument list cached daily, quotes cached a second | Polling faster than the rate limit, or marking a position off a stale quote |
| `market_data/live_quote.py` | Live index quote + market status (15s cache) | Historical fetching |
| `storage/login_log_db.py` · `scripts/kite_login.py` | The daily Zerodha session: prompt in the morning, record which days had one | A stored password or TOTP seed — a test refuses it |
| `market_data/kite_session.py` | Kite login, daily token (dies ~6 AM IST), secret from `api/.env` | Data fetching |
| `market_data/bar_archive.py` | Local index-bar archive + `ArchiveProvider` (no login needed) | Provisional bars — never stored |
| `quant/indicators.py` | Pure functions: series in, series out | State, I/O, signals |
| `quant/regime.py` | Regime classification | Trade decisions |
| `quant/pipeline.py` | Assembles the analysis payload; `daily_frame` (the indicator grid's and the 1D chart's completed sessions) reads Kite's daily bars first — NSE's closes, none missing or late — and Yahoo topped up from NSE's report only when the Kite login has lapsed (`attrs["source"]` says which); VIX falls back NSE → Kite → Yahoo; no VWAP (an index has no volume on either feed) | New math |
| `backtest/engine.py` | The simulator. **I1 lives here.** | Strategy-specific logic |
| `backtest/costs.py` · `options_engine.py` | Cost models (index / options) | Signals |
| `backtest/strategies*.py` · `pcr_signals.py` | Signal functions + registry | Execution logic |
| `backtest/research.py` | Rank all strategies vs. baseline | Validation verdicts |
| `backtest/walkforward.py` | Folds, holdout, final verdict | Live recommendations |
| `backtest/hypothesis_log.py` | Append-only audit trail (JSON Lines, OS file lock) | Rewriting the file — only ever append |
| `stats/bootstrap.py` | 95% percentile intervals for a mean and for an edge over baseline, fixed seed | Changing the seed to move an interval |
| `stats/multiple_comparisons.py` | Scaled evidence bar, at each result's degrees of freedom | Strategy logic |
| `stats/student_t.py` | Student's t CDF and inverse, no scipy; checked against printed tables | Approximations — it is exact to table precision |
| `backtest/pattern_info.py` | What each pattern checks and the idea behind it | Evidence — the numbers are elsewhere |
| `backtest/pattern_options.py` | Pattern → option choice on dev data → profit on holdout | Picking the option on holdout data |
| `backtest/pattern_proximity.py` | Formed today / could form next close, trigger levels (bisected to ~1 pt), base rate | Forecasts — it's a base rate |
| `copilot/llm_client.py` | Provider-agnostic LLM client (any OpenAI-compatible API; Gemini/Groq presets) | Business logic |
| `copilot/guard.py` | I2 for the LLM: rejects any answer with a number not in the data | Leniency — it's the safety net |
| `backtest/intraday.py` | Execution studies on the 15-min archive: is the open obtainable, does entry time matter | Reading it as a pattern engine — it tests assumptions, not edge |
| `copilot/jev.py` | Shared TypeSafe Jev client; every call fails open | Letting a guard outage take the copilot down |
| `copilot/prediction_guard.py` | The two forecast/advice questions and their threshold | Raising `BLOCK_ABOVE` to fix a wording problem — fix the criteria instead |
| `copilot/claim_guard.py` | One choice question per sentence: does the data support it? | Judging a whole block as one claim — a false sentence averages out |
| `copilot/review.py` | Both guards in one Jev call over shared state | Splitting them into two calls; they judge the same evidence |
| `copilot/composer.py` | The daily explanation written in Python — no model, so I2 holds by construction | Letting it decide anything; it only says what the context contains |
| `copilot/context.py` | The digest the copilot may talk about, in three route-scoped views | Adding a view that drops a fact its questions need |
| `copilot/grading.py` | Two 0-2 scores on every answer: honesty about weak evidence, and clarity | Letting a grade block an answer — only the guards block |
| `storage/copilot_log_db.py` | Every answer and what the guards made of it | Treating it as evidence; it holds the user's own questions and may be deleted |
| `copilot/router.py` | Classifies a question before the model is called: refuses off-topic ones in code, picks the context scope | Narrowing the context on an unsure classification — it falls back to everything |
| `copilot/context.py` · `assistant.py` | Compact digest of computed results → explain/ask | Computing anything new |
| `backtest/similarity.py` | Phase 11: 5-feature nearest-neighbour analogs + walk-forward test | More features without evidence they help |
| `backtest/live_patterns.py` | Phase 10: today's candle from 15-min closes → which patterns would form now | Anything final before 15:30 |
| `storage/options_db.py` | Options archives — NIFTY (4.6 M rows) and, via `db_path_for()`, BANKNIFTY, MIDCPNIFTY, SENSEX in their own files | Strategy verdicts |
| `storage/strategy_status_db.py` | The Playbook — verdict history | Live recomputation |
| `briefing/research_briefing.py` | Rule-based evidence for/against | Verdicts |
| `briefing/recommendation.py` | The gate → CALL/PUT/NO_TRADE | New statistics |
| `briefing/pipeline_candidates.py` | The strategy pipeline's two daily straddles listed beside the patterns in the Today call when their condition holds on the last close (the next session is a scheduled RBI decision, Budget or election result — RBI's published 2026-27 dates added — or 30-day IV is below the last 21 sessions' realised), with their verdict and why they do not qualify | Making a straddle the call: the forward log records a call, a put or no trade |
| `briefing/forward_log.py` | Record each final-bar verdict; score it from the next open | Backfilling — ever |
| `storage/forward_log_db.py` | Write-once-per-date recommendation log | Outcomes (computed on read) |
| `storage/backup.py` | Verified, rotating backups of the forward log (SQLite online backup API) | A plain file copy — it can be torn mid-write |
| `options/iv.py` | Black-76 implied vol; forward and discount read off put-call parity, no assumed rates | A regression slope believed without checking the rate it implies |
| `backtest/iv_research.py` | Daily 30-day IV, its VIX check, IV description of every pattern, the one pre-registered filter test | Editing `PREREGISTERED` — a new hypothesis is a new test (a hash test guards it) |
| `backtest/structural_research.py` | Six pre-registered structural hypotheses for an option buyer (volatility pricing, positioning, calendar, gaps), one fixed setup each; `holdout_tests_judged()` — the count the evidence bar corrects for | Editing `PREREGISTERED`, or choosing a setup from a grid |
| `backtest/replication.py` | Pre-registered replication of judged patterns and three structural tests on BANKNIFTY, SENSEX, Midcap Select; one observation per entry date | Re-choosing a setup per index — that is a new test |
| `backtest/course_strategies.py` | Five intraday strategies from the user's course PDFs (TMS Pro, Triple Sync, Gap Fill, Impulsive Momentum, Trap adapted to NIFTY) on the Kite 15- and 5-minute archive, with every gap in the notes closed by one registered reading (hash 42e24490f0b52c4d, logged 2026-09-27 before any run). Judged on a modelled bought option — Black-Scholes on the real intraday path, the previous session's IV, the real expiry calendar, per-leg costs — against the same option bought at the same times with no signal; `scripts/course_strategies.py` | Editing `PREREGISTERED`; reading a result as a real option fill (the options archive is end-of-day) |
| `backtest/instrument_study.py` | The strategy pipeline's Phase 1: which option a buyer should hold. No signal, every session 2019-02-14 to 2023 (development only), nearest vs monthly expiry, 1% OTM / ATM / 1% ITM, held 1, 3 and 5 sessions, calls and puts weighted equally; measured as the cost of one point of NIFTY exposure a session (net rupees per unit ÷ delta ÷ sessions). Also run without the assumed slippage, because that assumption decides the answer; `scripts/instrument_study.py` | Choosing on 2024-26, or by percent of premium (it favours in-the-money contracts for the wrong reason) |
| `backtest/spread_model.py` | Phase 1's missing input: the real half-spread, (ask − bid) / 2, in index points and % of mid, from `option_snapshots.db`, for each (expiry, moneyness) Phase 1 compares, the contract chosen as `pick()` does (nearest expiry after the day; the monthly at least 14 days out, counted only where the recording shows its month complete; the strike nearest the 1% target with a two-sided quote). Median over 14:30-15:30 snapshots (the close Phase 1 trades at), all-day beside it. `SpreadCostModel` charges that half-spread in points each side in place of the 1.5%-of-premium slippage; `scripts/instrument_study.py --measured-spreads` re-runs the grid with it and adds `with_measured_spreads` to `instrument_study.json`, spot from NSE's local closes, no network | Reading it as settled: 2026 spreads on 2019-23 prices, on as many sessions as the snapshots hold; editing any other key of the result |
| `backtest/breakout_research.py` | The afternoon-breakout idea the Trap's 2024-26 result suggested (continuation, and the Trap reversed), pre-registered (bbe333f83a7202a8) and judged on 2015-17 — never used by any study — with 2018-26 reported as the discovery period it is; India VIX as the volatility in every period, last-Thursday monthly expiries for 2015-17; `scripts/breakout_research.py`. `/api/course_research` serves both studies to the Research tab | Judging it on 2018-26, where it was found |
| `market_data/nse_indices.py` · `storage/nse_index_db.py` | NSE's daily all-index report: Midcap Select levels, and the close Yahoo sometimes lacks | Replacing Yahoo's history — it only tops up later sessions |
| `backtest/nifty_pipeline.py` | The strategy pipeline's Phase 2: five pre-registered hypotheses (hash in the file, literal tripwire in its test) — event and cheap-volatility straddles on real NSE closes, and the noise band, last-half-hour momentum and the 5-minute opening range on the course study's modelled option — judged once on 2024-26 against the same option with no signal; `scripts/nifty_pipeline.py` writes `data/nifty_pipeline.json` and counts in `backtest/family.py` | Editing the registration; re-running a changed rule under the same name |
| `scripts/snapshot_options.py` · `storage/option_snapshots_db.py` | The strategy pipeline's Phase 4: NSE's option chain every five minutes of the session (LaunchAgent `com.niftycopilot.snapshots`, on each bar's close plus 20 seconds), near the money, for the two nearest expiries and the nearest monthly — the intraday option prices no archive serves, for testing intraday rules on real prices and measuring real spreads. Each saved run then hands its chain to the intraday record | Saving a chain NSE stamped outside today's session (it restamps the close); updating or deleting a row |
| `options/move_table.py` | `/api/options/moves`: for 8 strikes either side of the money, each contract's own implied volatility solved from its price now (Black-76, so the model reproduces the price), its delta, and its price change for a ±25/50/100/200-point index move instantly and by each coming session's close (NSE's holiday list decides the sessions; time on a market clock where a session is one unit and a closed gap its measured share, 0.47 overnight to about 1 for a weekend), valued against the put-call-parity forward; beside it the premium points per index point measured across the session's option snapshots | NSE's IV column for the model (it does not reproduce a call and a put at one strike); a move with a day's decay passed off as instant |
| `briefing/weekday_profile.py` | The Today tab's weekday card (`/api/weekday_profile`, 60 s cache; 2018-26 history cached for 6 h): every session of this weekday since January 2015 (the 5-minute archive), each in % of its own open and shown as points at today's level — range, first swing (ends on a fixed 0.25% reversal) and swing back, hour-by-hour medians and quartiles — today's path against them, the five past same-weekday sessions closest to today so far and what each did after, and measured why lines (overnight vs intraday drift, first-swing timing, expiry days) | A forecast or a "Consider": it describes; the rules that tried to predict these moves are judged elsewhere |
| `briefing/intraday_live.py` · `storage/intraday_forward_db.py` | The strategy pipeline's Phase 3 on the Today tab: the three intraday rules followed on completed 5-minute bars (the archive's, then Kite's for days after it, Yahoo's when the login has lapsed), each with its levels, trigger, contract (the nearest expiry not expiring that day, at the money), study verdict and one sentence written in Python — "Consider" only for an APPROVED rule. `/api/intraday` (30 s cache); the tick prices any contract a rule bought. The snapshot run records each entry and exit once, at the chain's bid and ask, in an append-only record the database refuses to update or delete | Using a bar still forming; a follower that disagrees with the study's trades (a test replays history through both) |
| `backtest/orderflow_registry.py` · `scripts/orderflow_forward.py` | The four order-flow rules registered 2026-10-01 for a forward test (57c29550776a8810): run nightly on the snapshots from 2 Oct, each judged once at its registered minimum sample at the bar for 69, logged then; `data/orderflow_forward.json`, shown on the Research card | Editing a rule or a minimum; judging before the minimum; counting 1 Oct |
| `backtest/orderflow_features.py` | Order-flow features from the option snapshots, one row per snapshot of one expiry: near-money call and put OI and their change since the open and over 30 minutes, the put-call OI ratio, ATM and near-money book-size imbalance, ATM IV and its change, the call-put vol spread, the 1% and 2% skew, the largest OI build-up and largest-OI strike with their distance from spot, the ATM spread; read with `mode=ro`. Each feature at t is computed from the snapshots up to t only (a test scrambles every later one) | Mixing expiries in one feature; a since-open figure when the first snapshot came after 09:30 |
| `backtest/orderflow_forward.py` | The forward harness for rules on those features (the snapshots have no history, so a rule can only be judged on sessions after its registration): the Phase 1 contract, bought at the ask at least 60 s after the snapshot the rule read and sold at the bid, the rate card with no assumed slippage; the same option at the same clock times on every session as the baseline; refuses to judge before the registered minimums, then closes the sample so it cannot be re-judged at a lucky moment; `trades_needed` for sizing. Nothing in it is registered | Registering a rule without the owner's approval; judging sessions from before the registration |
| `market_data/gift_nifty.py` · `storage/gift_nifty_db.py` | GIFT Nifty live quote from NSE IX, nightly snapshots | Treating it as a signal — an option bought at the close can't act on the evening |
| `market_data/news.py` · `storage/news_db.py` | Market news from five dated, trusted feeds plus NSE filings; an append-only archive stamped with when *this system* first saw each headline | Trusting the publisher's `published_at` for research — feeds restamp and backdate |
| `news/classify.py` · `news/feed.py` | Jev judges each headline: is this the kind of event that moves an index, which way, what topic. Split into pre-open / live / post-close | Reading the tone tally as a signal, or re-judging a headline after the market has moved |
| `market_data/gdelt.py` · `storage/news_tone_db.py` | GDELT's free daily news-tone series back to 2018 — the only reason a news edge can be backtested rather than merely started | Editing the frozen query after seeing a result; a reworded query is a new key |
| `backtest/news_research.py` | Five pre-registered tone hypotheses for an option buyer, one fixed setup each | Using a day's own coverage to trade that day — much of it is *about* that day's move |
| `backtest/family.py` | How many hypotheses have had their look at the holdout, family by family — the count the recommendation's bar is corrected for | A hard-coded count, or a new family left out of it |
| `storage/paper_db.py` · `briefing/paper.py` | Phase 14: hypothetical positions at real premiums, opened forward only, with a weekly no-signal control | Opening one for a past signal date — that is a backtest |
| `storage/journal_db.py` · `briefing/journal.py` | Phase 13: the user's decisions next to the system's verdict; P&L computed, never typed. Each open trade priced now (`positions`: Kite on the tick's one call, else its last archived close with the index at that same close, or put-call parity when that close is missing), with Black-76 time decay, the result at expiry if the index holds, and the breakeven; the user's own stop and target (columns added in place, rows untouched); settlement at expiry from the index close, charged exercise STT, not a sale; a sale dated after expiry refused | Letting the user type the system's verdict, or a settlement value; any wording stronger than "consider", or one not tied to the user's own plan |
| `market_engine/drivers.py` | "Why it moved": NIFTY's return against global cues that closed before India opened, betas from earlier days only | A same-date US session — look-ahead |
| `market_engine/who_wins.py` | The variance risk premium; the cost of buying options without a signal; SEBI's published figures | Showing the forward-looking study as a current signal |
| `market_engine/positioning.py` | NSE participant-wise open interest, zero-sum checked | Reading overnight OI as intraday retail behaviour |
| `market_engine/expiry.py` | Expiry-day footprint studies; unusual strike activity against the same point in past expiries | Calling a statistic evidence against a participant |
| `briefing/today_chart.py` | The Today chart's data, three timeframes with their own EMAs and each candle's change: 15-minute bars (last 10 sessions), 4-hour candles folded from the archived 15-minute bars (Kite's for days after the archive and the session in progress; Yahoo's only when the Kite login has lapsed, asked for a day past today because its end date is exclusive), their EMA20/50, the block still forming (provisional, carried to Kite's bar still open — the price now, not the last closed 15-minute bar), the previous session's high/low, the band each pattern's next close would have to land in (with its distance from the price now) — only for patterns whose option verdict is APPROVED, since 2026-09-30 — the days each of those formed, and the live candle in a session | Anything the browser would have to compute; a band presented as a reason to trade |
| `briefing/live_indicators.py` | The indicator grid under Today's call (`/api/indicators`): price vs EMA20/50, RSI, ADX, ATR, the session range against ATR, the opening gap, India VIX and ATM IV against 20-day realised. In a session, NSE's open/high/low/last become a provisional candle that every reading includes | Relative volume or VWAP (the index has no traded volume on the free feed); a reading worded as what to do |
| `market_data/indices_board.py` | The Market tab's indices board (`/api/indices`, and on the live tick): NIFTY and Bank Nifty from the one NSE all-indices response, Sensex from Kite's quote (Yahoo's 1-minute bars if the Kite login has lapsed; BSE refuses outside requests; Kite's quote calls are spaced a second apart in `kite_quotes._quote_slot`), GIFT Nifty from NSE IX; a commentary written from those numbers: direction, leading or lagging NIFTY, place in the day's range, GIFT while India is shut, feeds behind or missing | Words that suggest a trade or forecast the open; making the tick wait on Yahoo or NSE IX (it reads `cache.cached_background`) |
| `market_engine/strategy_fit.py` | Which strategies today's market suits: whether each is forming (Python, real prices) beside Jev's yes/no on whether today is the kind of market its premise was written for; one request per reading, at most every 15 min and only when the picture changed; stored in `data/strategy_fit.db` | Showing Jev a strategy's record, verdict or trigger; letting a fit reach the recommendation or the paper book (a test reads their source) |
| `market_engine/knowledge.py` | The research as sourced principles, for the dashboard and the copilot | Any unsourced claim, or advice |
| `audit/` | Phase-by-phase deep audit on real data, with independent reference implementations; `scripts/audit.py`, `check_all.sh --deep` | Mocks and fixtures — that is what `tests/` is for |
| `web/src/components/ui.tsx` | Shared primitives (Panel, Pill, Stat…) | Feature components |
| `web/src/lib/api.ts` | Typed fetches. **No mock fallbacks (I2).** | Computation |
| `web/server.mjs` · `web/gate.mjs` | The production server and the page's lock: this Mac by socket address, every other device by the pairing token (HttpOnly cookie; the pairing link redirects the token out of the URL), Host must name this Mac; `node --test gate.test.mjs` | Deciding "this Mac" from a header |

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
| `api/backtest/hypothesis_log.jsonl` | Every backtest run ever executed — the audit trail behind the hypothesis counts | No — and not regenerable either: backed up nightly (gzipped) with the other irreplaceable files |

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

Python syntax · the whole pytest suite · ruff (if installed) · `tsc --noEmit` · ESLint · every read-only endpoint.
Exits non-zero on failure, so it drops straight into a pre-commit hook or CI.

The test suite exists because two real bugs were found by hand in one session. Every bug
found from here gets a regression test — that's the rule that keeps the suite meaningful
rather than decorative.

---

## 9. Status and known gaps

**Phases 1–12 complete** (Phase 12 awaiting an API key). Phase 10 is live trigger tracking: during the session, today's candle
is built from completed 15-minute bars (Kite) and every pattern is run on it — "would form if
today closed now", provisional until 15:30. Phases 13-15 (journal, paper observation, deployment as LaunchAgents) are done. Phase 11, historical similarity: 20 past days nearest
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
