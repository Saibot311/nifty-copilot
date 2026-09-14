# NIFTY COPILOT — Project Plan

Living document. Update it as phases complete or decisions change. Current status: **Phases 1-6 done.**

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
| 7 | 10-year research | Uses whatever data source Phase 0 lands on. Start logging every hypothesis tested here. |
| 8 | Walk-forward validation | Train → test → move window. Multiple-comparisons correction applied. |
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
