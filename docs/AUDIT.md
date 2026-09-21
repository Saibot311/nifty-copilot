# Deep audit — Phases 0–12

Run 2026-09-21. Every phase checked against the data the system actually runs on, with
independent reference implementations wherever one exists.

```bash
cd api && .venv/bin/python scripts/audit.py              # every phase (~3 min)
cd api && .venv/bin/python scripts/audit.py --phase 5 8  # just these
cd api && .venv/bin/python scripts/audit.py --live       # plus the checks that call paid APIs
./scripts/check_all.sh --deep                            # tests, types, endpoints, then the audit
```

The unit tests in `api/tests/` prove each piece does what its author meant, on inputs the
author chose. The audit asks a different question — *on real data, does each phase do what it
claims?* — because a test suite cannot find the bug its author did not imagine. Three rules
for every check: real data, not fixtures; an independent implementation, not the same code
run twice; and measure the impact, not just the existence.

## Result

| | Before | After |
|---|---|---|
| Audit checks (44) | first run: 23 pass · 13 warn · **7 fail**¹ | **36 pass** · 7 warn · **0 fail** |
| Confirmed bugs | 14 | 0 open |
| Unit tests | 189 | **230** |
| Pattern verdicts | 2 CONDITIONAL · 24 REJECTED | 26 REJECTED |
| Option sessions missing since 2018 | 14 (incl. last Tuesday and Friday) | 1 (missing at NSE itself) |
| Forward-log backups | 0 | 1, verified, rotating nightly |

¹ The first-run count is what each check reported the first time it ran, and it is not a
clean "bugs before" figure in either direction. One first-run FAIL (0.3) was my check being
wrong — it conflated bad ticks with ordinary sampling — and several real bugs first showed as
WARN (8.2, 8.3, 6.4) because the check measured the gap rather than asking which formula the
system used. Five checks were corrected mid-audit once the code was fixed and they were found
to be testing the wrong thing; each correction is described where it matters below. The
number to trust is the 14 confirmed bugs, each reproduced on real data.

The pattern is worth noticing. **Phases 9–12 — the most recent work — were clean on the first
run.** Every bug was in the older foundations: data ingestion, one indicator, and the
statistics that turn a result into a verdict. The core invariant held everywhere it was
tested: no indicator, regime label, strategy or analog uses the future (checked at 25 random
cut points × 9 series, 12 × 26 strategies, and 410 instrumented similarity test points).

## The 14 findings

Ranked by how much they changed what you were shown.

### 1. The verdict ladder rewarded less evidence · `backtest/walkforward.py`
The sample-size check ran *before* the significance test and returned early. A pattern with
fewer than 15 holdout trades skipped the t-test and got CONDITIONAL; the same result on more
trades got REJECTED. **Both CONDITIONAL patterns held that label only through this path** —
Bollinger Band Reversion at t = 0.86, RSI Overbought Reversal at t = 0.50. The existing test
suite contained a test that pinned the bug in place (a thin holdout with *no t at all*,
expected to be CONDITIONAL). Fixed so significance is tested first; CONDITIONAL now means only
"cleared the bar, on too few trades to trust." New test: less evidence can never earn a better
verdict. *No trade suggestion was affected — only APPROVED triggers one.*

### 2. Bollinger bands used the wrong standard deviation · `quant/indicators.py`
`rolling().std()` is pandas' *sample* std. Bollinger's definition, TA-Lib and TradingView use
the population std. Bands were √(20/19) ≈ 2.6% too wide, changing **76 signals** across the
two patterns built on them — which were the two best-ranked patterns in the system.
**Bollinger Upper Rejection's +₹9,266/lot, the best record in the system, falls to +₹794**
with correct bands; its chosen option changed entirely. That headline was mostly an
artefact. The other five indicators (EMA, RSI, ATR, ADX, Stochastic) match independent
implementations of Wilder's and Lane's definitions exactly.

### 3. The evidence bar used the normal distribution · `stats/multiple_comparisons.py`
Right for large samples, wrong for these. At the Bonferroni level for 19 patterns the normal
bar is 2.79; a verdict on 11 holdout trades needs **3.55** under Student's t. Now computed at
each pattern's own degrees of freedom. Student's t is implemented in `stats/student_t.py`
(no scipy) and checked against seven printed table values. The approved "t ≥ 2" rule is kept
as what it always was — the large-sample form of a 2.5% one-sided test — at the right
sample size: 2.23 for 11 trades, 2.01 for 50.

### 4. The t-test treated the baseline as exact · `backtest/pattern_options.py`
The no-signal baseline's mean is itself a sample. A one-sample test drops its uncertainty and
overstates t. Replaced with Welch's two-sample test; checked by hand calculation.

### 5. Development trades were scored on holdout prices · `backtest/pattern_options.py`
Split on *entry* date, so a trade entered in late December 2023 and exited in January 2024 fed
the option *selection* with holdout-period prices. Two such trades (Prev-Day-High Breakout,
52-Week High Breakout). Trades straddling the split are now purged from both sides; one
pattern's chosen option changed as a result.

### 6. The options archive silently stopped updating · `scripts/backfill_options.py`
A missing bhavcopy means *holiday*, *not published yet* or *download failed* — and all three
were recorded as "done, 0 rows" and never retried. **2026-09-15 was fetched at 13:38 IST,
before that day's file existed, and skipped forever; so was 2026-09-18.** The archive was two
sessions stale last week with nothing to say so. Three holdout-period days were never fetched
at all, and weekend sessions (Budget days, Muhurat) were skipped by calendar. Fixed using the
index archive as the authority on which days were sessions; a new `--fill-gaps` mode runs
nightly. **14 of 15 sessions restored (25,652 rows).** 30 March 2021 returns 404 from NSE's own
archive and is retried quietly.

### 7. Trades that could not finish were counted as finished · both engines
A signal a few days before the data ended was closed early and counted as a completed trade. In
the options engine this was latent — the would-be-truncated trades happened to find no exit
row — but it would have fired the first night both archives were current. Incomplete trades
are now dropped.

### 8. Three definitions of a "10-day hold"
The index engine held 11 sessions; the options engine and forward log 10. Now 10 everywhere.
Options still enter at a *close* rather than an open — the archive is end-of-day — which the
research states and the copilot now says.

### 9. Max drawdown was understated · `backtest/metrics.py`
The equity curve started after the first trade, so losses from the starting balance never
counted. Now starts at 1.0.

### 10. Bad ticks in the 15-minute archive · `market_data/bar_archive.py`
Four sessions have bars beyond the day's official range — 2022-03-07's 10:00 bar has open, low
and close at 15,785.4 and a high of 16,174.45, 230 points above anything traded that day. The
source can't be edited; the loaders now clamp to the official range. (Several enormous wicks —
Sept 2018's flash crash, March 2020, election-result day 2024 — are real and untouched.)

### 11. The regime classifier broke its own contract · `quant/regime.py`
Documented to raise on under 50 bars; returned `TREND_BULL` on 30. The EMAs and ADX return
numbers from the second bar, so the `isna()` guard could never fire.

### 12. The irreplaceable file had no backup · `storage/backup.py`
`forward_log.db` cannot be regenerated. Now backed up nightly through SQLite's online backup
API, re-opened and row-counted before it counts, 30 kept. **Set `BACKUP_DIR` in `api/.env` to
iCloud Drive or Dropbox** — backups on the same disk survive a bad write, not a lost disk.

### 13. Arbitrary symbols reached Yahoo · `api/main.py`
Nine endpoints passed any `symbol` string to an external API, failing as 503. Now constrained
to `^NSEI` and refused with 422 before the handler runs.

### 14. Kite's daily bar for 2015-08-10 is wrong
Close 8,607.55; Yahoo and Kite's own last 15-minute bar agree it was ~8,525. Signals use Yahoo,
so none were affected. Recorded, not edited.

## What the audit could not fault

Worth stating, because a clean result is also a finding:

- No secret value appears in any tracked file or anywhere in git history (searched for the
  actual values in `api/.env`, not a pattern).
- All 23 endpoints return JSON a browser can parse — no `NaN` or `Infinity`.
- CORS admits only the local dashboard; malformed requests leak no traceback.
- The dashboard never falls back to invented data; the production build passes.
- Option prices obey put-call parity to a median 0.10% of spot.
- The dashboard's "formed today" is the same event the research measured (120 sessions ×
  24 patterns, window vs full history, zero disagreements).
- Every published trigger level really triggers its pattern.
- The forward log is write-once and every row predates its outcome.
- Every number the copilot is given traces to a computed source; no secret has been written
  into its records.

## Seven warnings that are facts, not bugs

| Check | What it is |
|---|---|
| 0.1 | Gaps in 1990s daily data. Signals start in 2007. |
| 0.2 | 2021-02-24 ran past 15:30 after an NSE outage. Real. |
| 0.3 | Bad ticks exist in the source — clamped on load (4.2 passes). |
| 0.4 | Kite's 2015-08-10 close (finding 14). |
| 0.6 | Thin strikes in 2019 break parity by up to 1.3% on a few days. |
| 0.7 | 30 March 2021 is missing at NSE itself. |
| 8.4 | **10 of 26 patterns are judged on fewer than 15 holdout trades.** The most important line in this report — see below. |

## Recommendations

The audit's clearest lesson: **the binding constraint is sample size, not a shortage of
indicators.** Ten patterns rest on fewer than fifteen trades, and every new indicator is a new
hypothesis that raises the bar for all the others. So the recommendations are ranked by how
much *evidence* they add, not how much *signal*. Items marked **(+H)** add hypotheses and must
be pre-registered before testing.

### Do next

1. **Replicate every pattern on BANKNIFTY options.** The strongest test of whether a pattern is
   real is whether it works on data it was never designed on. The bhavcopy backfill already
   takes a `--symbol`, the options engine needs no changes, and it roughly doubles the trades
   behind every verdict. A pattern that holds on both indices is worth far more than one that
   clears a higher bar on one. (BANKNIFTY weeklies ended in Nov 2024; monthlies continue.)
2. **Run the fast audit nightly and alert on FAIL.** The options archive was stale for days
   and nothing noticed. Checks 0.5, 0.7, 1.3, 4.2 and 10.3 take seconds.
3. **Store every trade with every research run.** The audit had to re-run configurations to
   inspect individual trades. Storing them makes every verdict auditable after the fact and
   makes item 5 possible.

### Accuracy of the evidence

4. **Combinatorial purged cross-validation** instead of one 2024 split. Many train/test paths
   instead of one, with the purging already built here — more holdout trades per verdict
   without new data.
5. **Bootstrap confidence intervals on ₹/lot.** "Between −₹4,000 and +₹12,000 per lot" tells a
   beginner more than "t = 1.31".
6. **Probability of Backtest Overfitting** for the 45-configuration option choice. The holdout
   protects the verdict, but not the *choice*, which is picked from 45 on the same data.
7. **Measure real fills going forward.** Slippage is a flat 1.5% of premium per side. Record
   live bid/ask at a fixed time each day from Kite; after a few months, replace the guess.
   Option *opens* have to be collected the same way — Kite's historical API only covers
   listed instruments, so expired contracts cannot be backfilled.

### Trade recognition

8. **✅ Done 2026-09-21 — see PROJECT_PLAN.md. The pre-registered filter test was NOT ADOPTED.**
   **Implied volatility from data already on disk.** For a buyer of options, the entry IV
   matters as much as direction — buying calls into high IV loses to the IV collapse even when
   the index moves the right way. The archive holds price, strike, expiry and spot for every
   contract since 2018, so IV and IV rank can be computed (Black-Scholes inversion) with no new
   data. First use: as a *description* of each pattern's trades, costing no hypotheses. Only
   then as a filter **(+H)**.
9. **Option-chain signals instead of transplanted index patterns (+H).** Every pattern here is
   an index pattern with an option bolted on. The archive has open interest and its daily
   change per strike — OI build-up and unwinding, put-call OI by strike, skew. These describe
   what option traders are doing, which index candles cannot.
10. **An event calendar.** RBI policy, Budget, election results, expiry days. Tag every signal
    that falls on one; report those trades separately before deciding anything **(+H)**.
11. **Meta-labeling, later.** Keep each pattern as the trigger; train a second model to decide
    take-or-skip from IV, regime and OI. It improves precision without inventing new signals —
    but needs hundreds of trades, so only after item 1.

### System hygiene

12. **Validate on ingest, not only in the audit.** Reject impossible bars and check put-call
    parity as data arrives, so a bad row never reaches a signal.
13. **A staleness banner** on the dashboard when either archive is more than one session behind.
14. **A live bad-tick filter.** Today's 15-minute bars can't be clamped to a daily range that
    doesn't exist yet; a median-absolute-deviation filter on wicks would catch spikes.
15. **Install `ruff`.** The lint section of `check_all.sh` has been skipping itself.
16. **Phase 13 — the trade journal** — is still the next planned phase. Like the forward log,
    it cannot be backfilled honestly, so every week without it is a week lost.

## How the pipeline is organised

| Module | Phases | Checks |
|---|---|---|
| `audit/checks_data.py` | 0 | bar integrity, daily vs intraday, two-source agreement, option integrity, put-call parity, coverage |
| `audit/checks_platform.py` | 1–4 | secrets in history, ignores, backup, strict JSON, error leaks, CORS, mock data, production build, provider contract, served bad ticks |
| `audit/checks_quant.py` | 5 | indicators vs independent implementations, Bollinger impact, no look-ahead, regime contract and distribution |
| `audit/checks_backtest.py` | 6–8 | engine timing, truncation, costs, hold definition, metrics, strategy look-ahead, signal sanity, purge, Welch, small-sample bar, sample sizes |
| `audit/checks_live.py` | 9–12 | playbook vs research, recommendation gate, window vs full history, trigger levels, forward log, analog outcomes, copilot numbers, context provenance, secrets in records, labelled guard cases |

Each check registers itself with `@check(phase, id, title)` and returns PASS, WARN, FAIL or SKIP
with its evidence. A check that raises is recorded as a FAIL, never skipped. Add checks as new
phases are built.
