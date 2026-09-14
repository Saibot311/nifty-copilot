# NIFTY COPILOT — Project Plan

Living document. Update it as phases complete or decisions change. Current status: **Phase 0 decided — starting Phase 1.**

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
| 4 | Market data abstraction | Define the interface *first*, then implement `ZerodhaProvider`. |
| 5 | Quant engine | Indicators, price action, VWAP, regime detection — empirically tested, not assumed. |
| 6 | Backtest engine | Costs, slippage, full metric set. Reviewed specifically for look-ahead bias. |
| 7 | 10-year research | Uses whatever data source Phase 0 lands on. Start logging every hypothesis tested here. |
| 8 | Walk-forward validation | Train → test → move window. Multiple-comparisons correction applied. |
| 9 | Strategy playbook | Only real, computed numbers. APPROVED / CONDITIONAL / REJECTED. |
| 10 | Live analysis | Decision point = 15-min candle close. Unfinished candles marked provisional. |
| 11 | Historical similarity | **Start with 3-5 features + nearest-neighbor. Expand only if needed.** |
| 12 | LLM copilot | Explains results only; never generates numbers. |
| 13 | Journal | TAKE/SKIP/WAIT tracking, mistake analysis. |
| 14 | Paper observation | Live markets, zero execution. |
| 15 | Deployment | Only once stable. |

---

## 4. Beginner checklist

**Phase 1 — Foundation.** Status as of the environment check on 2026-09-14:

| Item | Status |
|---|---|
| Node.js | ✅ Already installed (v18.20.4 — fine for Next.js) |
| Git / local repo | ✅ Already set up at `NIFTY-Trading-App` |
| GitHub account + remote repo | ⬜ Not yet done — **this is the current step** |
| VS Code | Optional/skippable — you're already working with me in the Claude Code app, which covers editing/running code. Only install VS Code separately if you specifically want a second editor open. |
| Python | Not needed yet — arrives in Phase 3 |

---

## 5. Cost summary (flag anything paid before it's used — per your Budget Rule)

| Item | Cost | Free alternative | What you lose with the free version |
|---|---|---|---|
| Zerodha Kite Connect API | ₹500/month (~$6), requires a Zerodha trading account | NSE site scraping, yfinance, community CSVs | Depth (yfinance: ~10 days intraday), reliability (scraping breaks, rate-limited), and data provenance you can trust for real statistics |
| TrueData / Global Datafeeds (GFDL) | Not publicly listed — quote-based, likely a real commitment | — | Only worth contacting if Zerodha's actual historical depth (see below) turns out insufficient |
| Everything else in Stages 1-3 (Next.js, FastAPI, pandas, SQLite, GitHub, VS Code) | Free | — | — |

---

## 6. Open decision — Phase 0 (this needs your answer before Phase 1 starts)

**What's still unverified:** blog posts and forum threads say Zerodha's historical API can return NIFTY daily data back to ~2015, but minute-level granularity is capped at 60 days *per request* — which usually just means you loop over date ranges, not that the data doesn't exist further back. Nobody's confirmed in writing how far back *15-minute* NIFTY index data actually goes through the paid API. That's a 10-minute test, not a research project, but it does mean signing up for the ₹500/month plan before we know for sure it'll deliver 10 years.

I've asked you directly (see question) how you'd like to sequence this.
