# NIFTY COPILOT — Project Plan

Living document — the *chronological* record of what was decided and when. For how the
system is structured (layers, invariants, the strategy lifecycle, how to extend it), see
**[ARCHITECTURE.md](ARCHITECTURE.md)**.

Current status: **Phases 1-9 done**, plus options integration built out of phase order on request.

**Goal reframed: patterns ranked by option profit (2026-09-18):** the target is not "does a
strategy beat the index" but "which pattern is forming, why, which option it points to, and how
much that option made." Built: per-pattern option research on real NSE premiums (option chosen on
2018–2023, judged on 2024–26), a generic "could form on the next close" engine with trigger levels
and base rates, and plain-language rationale for all 26 patterns. Result: 0 APPROVED, 2 CONDITIONAL.

**Two pattern bugs found and fixed along the way — both inflated earlier results:**
1. *Look-ahead in the candlestick patterns.* The swing-high/low filter used a centered rolling
   window, so Hammer, Shooting Star and both Engulfings saw two bars into the future. Hammer and
   Shooting Star were the only CONDITIONAL strategies; without the leak both are REJECTED
   (Hammer's holdout went from +0.69% to −0.46%).
2. *EMA Pullback/Rejection fired every day of a trend, not on the reclaim.* In pandas 3,
   `bool_series.shift(1).fillna(False)` is object dtype and `~` on it is integer bit-flip
   (`~True == -2`, truthy), so "just reclaimed" meant "is above". Every EMA Pullback number in
   the Phase 6–8 entries below came from that broken rule; the genuine pattern forms ~2×/year.
Both are now locked by generic tests over every pattern (truncation for look-ahead; "transition
patterns never fire two days running").

**All 26 strategies validated; forward log started (2026-09-18):** ran walk-forward validation on
the 22 never-validated strategies. The first pass returned two APPROVED at +0.043% and +0.062% per
trade in the holdout, less than simply being long, because the verdict only asked "positive?".
Tightened (and stated here because the criteria changed after seeing results — in the stricter
direction): a strategy must now beat a direction-matched buy-and-hold baseline, same mechanics and
costs, in both development and holdout. Re-validated all 26: **1 APPROVED, 3 CONDITIONAL, 22
REJECTED.** The one APPROVED (MACD Bullish Crossover) clears its baseline by 0.07%/trade, t ≈ 0.18 —
noise; the recommendation gate still blocks it. Honest read: no daily-bar strategy here has a
demonstrated edge.

Then, with approval, added a significance requirement (holdout edge over baseline must reach
t ≥ 2). Final: **0 APPROVED, 2 CONDITIONAL (thin samples), 24 REJECTED.**

Started the forward log: every day's recommendation is recorded once its bar is final, write-once,
never backfilled, and scored later from the next open. First entry: 2026-09-17, NO_TRADE.

**Zerodha connected; Phase 0 question answered (2026-09-18):** Kite Connect (₹500/month, approved)
is live. Kite's 15-minute NIFTY history starts **2015-01-09** — ~11.7 years, past the original
10-year target (Yahoo's free intraday reaches ~60 days). Daily goes back to 1990 (pre-1996-04-22 is
back-calculated). All of it is now in a local archive (`api/data/nifty_bars.db`: 72,094 15-min bars
over 2,896 days, 8,804 daily bars) so backtests don't need a login. Bars still forming are flagged
`provisional` and never archived; found and fixed a bug in that logic where Diwali Muhurat
bars (which start at 18:15, after the normal close) would have been treated as final the moment they opened.

**Multiple-comparisons counting fixed (2026-09-17):** `total_hypotheses_tested()` was counting
every *logged run* rather than every *distinct* strategy+parameter combination. Because each
dashboard load re-runs several backtests, the count had reached 6,342 when only 86 genuine
hypotheses had ever been tested — inflating the required evidence bar from ~0.49% to 0.725%
expectancy with no new research behind it, and climbing further every time anyone opened the
app. Now counts distinct combinations; `total_runs_logged()` keeps the raw count visible for
transparency. Regression test added.

**Phase 9 done (2026-09-16):** persistent strategy playbook in SQLite (`strategy_status_history`) —
verdicts are a timestamped historical record, not a live recomputation that silently drifts.
26 strategies registered (13 symmetric call/put pairs); 4 validated so far, 0 APPROVED,
2 CONDITIONAL, 2 REJECTED. Of the three best baseline-adjusted candidates run through full
walk-forward validation, two were rejected outright — the multiple-comparisons concern proving
real rather than theoretical.

**Options Trade Helper (2026-09-15):** you asked for daily NIFTY options trading help. Clarified this meant swing-style options ideas (buy a call/put off a directional signal, hold ~1-2 weeks) rather than intraday options day-trading. Built `api/options/advisor.py`: checks whether EMA Pullback (the only strategy with any real edge, still CONDITIONAL) is signaling as of today's close, and if so, translates that into strike guidance (ATM/ITM, not OTM) and expiry guidance (buffer well beyond the hold period) — with the CONDITIONAL status and a list of critical warnings (no live premiums/IV/Greeks, options can lose money even on a correct directional call due to theta decay) always shown alongside. Deliberately does not fetch or invent real option prices — that data isn't in the system, and this project's whole premise is not fabricating numbers that aren't actually computed. Options chain data (strikes, premiums, OI, IV, Greeks) remains a real future data-sourcing decision, same budget considerations as everything else.

**Phase 8 finding (2026-09-15):** ran EMA Pullback through walk-forward folds (5 chronological chunks of the full history) and a development/holdout split (70/30). The holdout split alone looked fine (development +0.74% expectancy, holdout +0.15%, both positive) — but the fold breakdown told a different story: only **2 of 5 folds** had positive expectancy (2011-2015, 2015-2019, and 2022-2026 were all negative; 2007-2011 and 2019-2022 carried the whole result). Combined honest verdict: **CONDITIONAL, not APPROVED.** This is a deliberate design choice — a single train/test split can look clean while masking real inconsistency that only the fold-by-fold view reveals, and the app is built to surface that tension rather than round it up to a confident answer.

**Known methodological limitation, stated rather than hidden:** Phase 7 already looked at the *full* history (holdout window included) when picking EMA Pullback as the best of 4 candidates. Because its parameters are fixed by hand rather than fit to data, there's no optimization step that could leak — so this is a genuine test of the rule's stability over time — but it is not a fully clean test of the *selection* process. A rigorous version would re-run strategy discovery using only the development period and confirm the same strategy gets chosen before ever looking at the holdout. Worth revisiting if this strategy is ever taken further.

**Phase 7 decision (2026-09-15):** revisited the Phase 0 data question as planned. Chose to proceed with the free ~19-year daily dataset rather than pay for Zerodha now — the daily depth already exceeds the original 10-year target, and 15-minute granularity is deferred until it's actually needed (still capped at ~60 days free either way, so paying now wouldn't even answer that question without further work).

**Phase 7 findings (exploratory, not validated — see Phase 8):** ran four independent strategies over the full 2007-2026 daily history with identical costs: EMA Pullback (+0.61% expectancy, PF 1.63, 109 trades), Previous-Day-High Breakout (+0.13% expectancy, PF 1.10, 319 trades — largest sample, weakest edge), Bollinger Band Reversion (~breakeven, PF 1.00, 76 trades), RSI Oversold Reversal (−1.44% expectancy, PF 0.48, 36 trades — loses money, especially in TREND_BEAR). Only EMA Pullback shows a real edge worth pursuing further. Its parameter-robustness sweep (5 EMA spans × 4 holding periods = 20 combinations) came back **positive expectancy in all 20** — a genuinely encouraging sign it's not a fluke tuned to one lucky number, though still not proof: Phase 8's walk-forward test on unseen data is what would actually confirm that. 35 total hypotheses now logged in the audit trail.

**Major finding (2026-09-15): free daily NIFTY data goes back to 2007-09-17 — ~19 years — via Yahoo Finance, confirmed by actually pulling it (`period="max"` returned 4,659 daily bars).** This changes the Phase 0 picture materially: the "10 years realistically isn't free" warning still holds at the *15-minute* timeframe (still ~60 days free via Yahoo), but at the *daily* timeframe we already have almost double the target history, for free, right now. This is enough to meaningfully exercise the whole backtest/walk-forward pipeline before any Zerodha decision — the ₹500/month subscription still matters for real 15-minute intraday history, but is no longer blocking daily-level research.

The dashboard shows real, computed values (price, regime, most indicators) instead of hardcoded numbers — pulled from free Yahoo Finance data through the Phase 4 abstraction, computed by hand-written deterministic formulas (no LLM, no third-party indicator library). The backtest engine (Phase 6) is proven against a real example strategy over the full ~19-year history.

**Important finding from Phase 5 (2026-09-15):** NIFTY 50 is a spot index — it has no real trading volume of its own (only its constituent stocks and derivatives do). Yahoo Finance's free intraday data reports volume as a flat 0 for `^NSEI`, which makes VWAP and relative-volume genuinely *uncomputable* from this source, not just imprecise. Rather than fake these, the API returns them as explicitly unreliable/unavailable with the reason stated, and the dashboard shows that caveat inline. Real volume-based analysis will need NIFTY futures data (Zerodha, paid) — reinforces the Phase 7 timeline, doesn't change it.

**Phase 0 decision (2026-09-14):** You have an active Zerodha account. Chosen path: **free-only for now** — build Phases 1-6 on free/limited data (NSE limits, yfinance, sample data), and revisit the ₹500/month Kite Connect subscription only if/when Phase 7's 10-year research actually needs the extra depth. Nothing paid has been signed up for.

---

## 1. Review of the spec — issues found

**Real risk, not a nitpick: 10-year 15-min data is not free, but it's cheaper than it used to be.**
Zerodha cut Kite Connect API pricing from ₹2000/month to **₹500/month** in 2025, and historical data is now bundled into that single fee (it used to be a separate ₹2000/month add-on). That changes the calculus a lot — the spec's warning that 10 years of data "realistically cannot be done for free" is still true, but the paid fallback is now cheap (~$6/month) rather than expensive, *if* Zerodha's archive actually has the depth you need. See Phase 0 below — that's unverified and is the first thing to test.

**Requires a live Zerodha trading account.** Kite Connect isn't a standalone data subscription — you need an existing (or newly opened) Zerodha demat/trading account to get an API key at all. If you don't have one yet, that's a bigger decision (KYC, account opening) than the ₹500/month itself.

**"Broker-agnostic" and "Zerodha as first data source" are in mild tension.** They're reconcilable (that's what the provider-abstraction layer is for), but it means Phase 4 needs to define the abstract interface *before* writing the Zerodha-specific code, not after — otherwise the Zerodha shape leaks into the rest of the app and "swap providers later" becomes a rewrite.

**Historical Similarity Engine (Phase 11) is the single biggest scope-creep risk in the whole roadmap.** Nearest-neighbor search over market states sounds simple but the feature engineering (what makes two market states "similar"?) can absorb unlimited time. The spec already flags this — I'm reinforcing it: start with 3-5 features, hard stop, and only revisit if the simple version's output is obviously wrong or unhelpful once you're actually using it.

**Multiple-comparisons control is the right instinct but needs a simple implementation, not a research paper.** A full false-discovery-rate correction (Benjamini-Hochberg etc.) is easy to bolt on later. For Phases 5-8, the practical version is: (a) log every strategy/parameter combination tested in a simple table (strategy name, params, dataset, date tested), (b) never call something "validated" from a single train/test split, (c) require a strategy to work on a held-out period it never touched. That's enough rigor for a personal system; don't build a statistics framework before you have strategies to test.

**Options data (Phase 11+, "add later") is effectively paid-only for history.** Historical options chain data (OI, IV, Greeks) at scale isn't available free anywhere reliable for NSE. Good that the spec already defers this — flagging so it's not a surprise when you get there.

**Free intraday sources are worse than they sound.** yfinance gives only ~10 days of 1-minute data. NSE's own site/API caps intraday requests around 50-90 days and is fragile to scrape. Community GitHub CSV dumps exist but have no verifiable provenance — fine for *learning the pipeline*, risky for a system whose whole premise is "never invent statistics." This is why Phase 0's decision matters.

---

## 2. Architecture (introduced in stages, per the spec's own philosophy)

```
Stage 1 (Phase 2):  Next.js + TypeScript + React + Tailwind, mock JSON data, no backend
Stage 2 (Phase 3):  + Python + FastAPI backend, SQLite
Stage 3 (Phase 5+): + pandas / numpy / scipy / scikit-learn / ta (indicator library)
Later, only if needed: PostgreSQL, Docker
```

**Market-data abstraction (Phase 4).** A single Python interface, e.g.:

```python
class MarketDataProvider(Protocol):
    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> DataFrame: ...
```

`ZerodhaProvider`, `CSVProvider`, and later others all implement this. Every other part of the app (quant engine, backtester, live assistant) talks to the interface, never to a provider directly. This is what makes "if Zerodha disappears tomorrow, the core app still works" actually true rather than aspirational.

**LLM vs. deterministic code — confirmed split (no changes):**
- Deterministic Python only, always: indicators, backtest metrics, regime classification, similarity search + its stats, every number shown in the UI.
- LLM only: explaining numbers the code already computed, teaching concepts, reviewing code/architecture, UI/UX judgment calls.
- The LLM never estimates a statistic. If a number isn't computed, the answer is "not available," not a guess.

---

## 3. Phased plan (as specified, with the adjustments above folded in)

| Phase | What | Notes |
|---|---|---|
| 0 | Data & budget reality check | **We are here.** See open decision below. |
| 1 | Foundation | GitHub, VS Code, Node.js. No Python yet. |
| 2 | UI with mock data | Next.js only. Price, chart, regime, indicators, scenarios, WHY panel — all fake data. |
| 3 | Backend | Python, FastAPI, SQLite. |
| 4 | Market data abstraction | ✅ Done. `MarketDataProvider` Protocol in `api/market_data/base.py`; `CSVProvider` (synthetic sample data) and `YFinanceProvider` (real, free, daily NIFTY data via Yahoo Finance — no signup) both implement it and are swappable via one query param on `/api/candles`. `ZerodhaProvider` is a stub that raises a clear error until you approve the ₹500/month Kite Connect subscription — proves the abstraction without pretending Zerodha is wired up. |
| 5 | Quant engine | ✅ Done (first cut). `api/quant/`: hand-written EMA/SMA/RSI/MACD/ATR/Bollinger/ADX/OBV/historical-volatility/session-VWAP formulas, a threshold-based regime classifier (ADX + EMA structure), and a couple of fully-implemented price-action checks (prev-day high/low break, HH-HL structure). Wired into `/api/snapshot` and `/api/indicators` — no more hardcoded placeholders for those two. Not yet done: the fuller price-action pattern list, and *empirically testing* whether any of this predicts anything — that's Phase 6-8's job, not this one. |
| 6 | Backtest engine | ✅ Done (first cut). `api/backtest/`: non-overlapping-position trade simulator that strictly executes decisions one bar after they're observed (signal from bar i's close → entry at bar i+1's open — the concrete no-lookahead rule), a configurable NSE cost model (brokerage/STT/exchange/GST/stamp duty/slippage), and the full metric set (win rate, expectancy, profit factor, max drawdown, Sharpe/Sortino approx, by-year, by-regime, long/short breakdown). Proven against a real example strategy ("EMA Pullback", named in this spec's own strategy-database example) over real NIFTY data: **24 trades / 5.5yr → −0.20% expectancy; 109 trades / 19yr → +0.61% expectancy, profit factor 1.63** — a genuine, useful illustration of why small samples mislead, not a claim that this strategy works. An append-only hypothesis log (`api/backtest/hypothesis_log.json`, gitignored — it's generated data, not source) already records every run, per the multiple-comparisons discipline in the spec. Not yet done: walk-forward validation and FDR correction across many strategies — that's Phase 8, once there's more than one strategy to compare. |
| 7 | 10-year research | ✅ Done (first cut). Four strategies tested over the full free ~19-year daily history (exceeds the original 10-year target), plus a 20-combination parameter-robustness sweep for the one that showed promise (EMA Pullback). Every run logged. Only EMA Pullback looks worth carrying forward to Phase 8 — the other three are exploratory dead ends, which is a legitimate, useful outcome, not a failure. |
| 8 | Walk-forward validation | ✅ Done (first cut). EMA Pullback tested via 5-fold walk-forward + a 70/30 development/holdout split, combined into one honest verdict. Result: **CONDITIONAL** — holdout split looked fine alone, but only 2/5 chronological folds were positive, so the combined logic correctly refused to call it APPROVED. Documented limitation: Phase 7's strategy *selection* already saw the full history, so this validates the rule's stability, not the selection process itself. |
| 9 | Strategy playbook | Only real, computed numbers. APPROVED / CONDITIONAL / REJECTED. |
| 10 | Live analysis | Decision point = 15-min candle close. Unfinished candles marked provisional. |
| 11 | Historical similarity | **Start with 3-5 features + nearest-neighbor. Expand only if needed.** |
| 12 | LLM copilot | Explains results only; never generates numbers. |
| 13 | Journal | TAKE/SKIP/WAIT tracking, mistake analysis. |
| 14 | Paper observation | Live markets, zero execution. |
| 15 | Deployment | Only once stable. |
| 16 (candidate, not yet approved) | News context layer | User idea (2026-09-14): explain how the market is reacting to financial news. Scope: a **qualitative context add-on to the WHY panel** — LLM summarizes recent relevant headlines (free RSS: Economic Times, Moneycontrol, NSE/BSE corporate announcements) alongside the already-computed scenario. Explicitly NOT a backtested numeric input to the regime/setup engine unless/until historical news-sentiment data is sourced and validated separately (reliable historical sentiment datasets are paid — e.g. RavenPack — and out of scope for now). Natural home: after Phase 10 (needs live data) / alongside Phase 12 (LLM copilot). |

---

## 4. Beginner checklist

**Phase 1 — Foundation.** Status as of the environment check on 2026-09-14:

| Item | Status |
|---|---|
| Node.js | ✅ Upgraded to v26.8.2 via Homebrew (the original v18.20.4 was too old for Tailwind v4 / ESLint 9, which need Node 20+) |
| Git / local repo | ✅ Set up at `NIFTY-Trading-App` |
| GitHub account + remote repo | ✅ Connected — https://github.com/Saibot311/nifty-copilot (auth via `gh auth login`, since GitHub retired password-based git pushes in 2021) |
| VS Code | Skipped — working directly in the Claude Code app |
| Python | ✅ Already installed (v3.13.3) — no install needed |

**Phase 3 status:** FastAPI backend scaffolded in `api/` with its own virtual environment (`api/.venv`, gitignored). Three endpoints so far — `/health`, `/api/snapshot`, `/api/indicators` — returning the same placeholder shape as `web/src/lib/mock-data.ts`, verified via curl and the auto-generated `/docs` page. CORS is open to `http://localhost:3000` only. No database yet — SQLite gets added once there's something real to persist (journal entries or cached market data), not before. The frontend now calls this API for the price snapshot and indicators (scenarios still come from the local mock file — no point faking a backend "computation" for them until the quant engine in Phase 5 actually calculates something). Verified both directions: with the API running, the dashboard shows live-fetched data with no banner; with it stopped, an amber "Backend API not reachable" banner appears and the page falls back to local mock data instead of crashing.

**Phase 2 status:** Mock dashboard built and verified running in-browser — price header, regime badge, indicator grid, three scenario cards (bullish/bearish/no-trade) each with entry/target/stop/reward:risk, confirmation/invalidation conditions, placeholder historical-evidence stats, and a working "Why?" toggle. All data in `web/src/lib/mock-data.ts` is explicitly fake — no real data yet. Chart is a placeholder box (real charting library arrives once there's real data to plot). Not yet built: trading journal UI, historical-similarity view (those are Phases 13 and 11 respectively — later).

---

## 5. Cost summary (flag anything paid before it's used — per your Budget Rule)

| Item | Cost | Free alternative | What you lose with the free version |
|---|---|---|---|
| Zerodha Kite Connect API | ₹500/month (~$6), requires a Zerodha trading account | NSE site scraping, yfinance, community CSVs | Depth (yfinance: ~10 days intraday), reliability (scraping breaks, rate-limited), and data provenance you can trust for real statistics |
| TrueData / Global Datafeeds (GFDL) | Not publicly listed — quote-based, likely a real commitment | — | Only worth contacting if Zerodha's actual historical depth (see below) turns out insufficient |
| Everything else in Stages 1-3 (Next.js, FastAPI, pandas, SQLite, GitHub, VS Code) | Free | — | — |

---

## 6. Phase 0 decision — resolved, revisit at Phase 7

Original open question was whether Zerodha's paid historical API actually delivers 10 years of 15-minute NIFTY data — still genuinely unverified (nobody's confirmed it in writing; it's a 10-minute test once you're actually paying for Kite Connect). That question no longer blocks anything: since free Yahoo Finance data covers ~19 years at the *daily* timeframe, Phases 1-6 have real data to work with regardless. The Zerodha question becomes relevant again specifically at Phase 7, and specifically for *15-minute* granularity — worth testing empirically before committing to the ₹500/month subscription, exactly as originally planned.

I've asked you directly (see question) how you'd like to sequence this.
