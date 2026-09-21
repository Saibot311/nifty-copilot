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
once on 2024–26 option data it never saw: **0 approved, 0 conditional, 26 rejected.**
Four apparent edges have now turned out to be bugs — two in earlier phases, and the
two CONDITIONAL verdicts, which the deep audit traced to a verdict ladder that
skipped the significance test for small samples. The forward log is the real test
now, and it needs calendar time.

**Implied volatility is computed from the options archive** (`options/iv.py`) and
tracks India VIX at a correlation of 0.983. It describes every pattern's trades. Its
one pre-registered test as a filter — buy only below the one-year median — was
**not adopted**: the right direction in both periods, but holdout t = 0.43.

**A deep audit of Phases 0–12 was run on 2026-09-21** — read `docs/AUDIT.md`. It
found and fixed 14 bugs, and it ends with a ranked list of what to build next.

## Running it

```bash
./scripts/check_all.sh          # 28 checks, 230 tests — run before and after changes
./scripts/check_all.sh --fast   # skips endpoint checks (no servers needed)
./scripts/check_all.sh --deep   # then the phase-by-phase audit on real data (~3 min)
```

Run `--deep` after any change to data ingestion, indicators, the engines or the
statistics — that is where every bug the audit found was hiding.

The copilot's three Jev-backed guards are judged by a real model, so they have
their own harness — it costs tokens and is not in `check_all.sh`. Re-run it after
changing any question, criterion or threshold:

```bash
cd api && .venv/bin/python scripts/check_guards.py   # forecast | claims | routes | grades
```

Dev servers are started through the harness preview tool, never `npm`/`uvicorn` in a
shell: `nifty-copilot-api` (:8000) and `nifty-copilot-web` (:3000). They stop when the
session idles; just start them again. First page load after a restart takes ~15-60s
because every cache is cold.

**Daily:** a LaunchAgent runs `api/scripts/daily_job.py` at 19:30 on weekdays (forward
log backup, forward log, bar top-ups, option top-ups plus any gap since 2018, option
research). Verified running unattended. Logs:
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
| `api/data/intraday_research.json` | Execution studies on the 15-min archive | `scripts/intraday_research.py` |
| `api/data/iv.db` | Daily 30-day implied volatility from 2018 | `scripts/iv_research.py` (incremental) |
| `api/data/iv_research.json` | IV description of every pattern, VIX check, the pre-registered test | `scripts/iv_research.py` |
| `api/data/copilot_log.db` | Every answer, its grades, and the Gemini-vs-composed comparison | Accrues in use; deletable (holds your questions) |
| **`api/data/forward_log.db`** | **Each day's verdict, written before the outcome** | **Cannot be rebuilt** — backed up nightly to `api/data/backups/` (30 kept). Set `BACKUP_DIR` in `api/.env` to a synced folder so a lost disk doesn't take it too. |

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
- **The opening print is not a price you get.** The index sits ~0.042% below it 15
  minutes later, in all 12 years. Longs entered late are cheaper than the backtest
  assumes, shorts dearer — CE results are mildly conservative, PE ones mildly optimistic.
- **A result that flips sign between dev and holdout is not a result**, however big
  the t is on each side. Entry timing showed t=-4 one way and t=+3.3 the other.
- **Write a sentence you think is clean and the guards will still find things.** Both
  flags on my own "ideal" answer were correct: "nothing here worth acting on" is the
  writer advising, and a sentence about what formed presupposed patterns the data says
  did not form. Real flagged answers make better labelled cases than invented ones —
  `/api/copilot/record` lists them.
- **A cached fallback is a trap.** One transient 503 served the composed explanation,
  which was then cached, so the model would not have been retried until the next day.
  Only cache what was expensive to produce.
- **An answer can be wrong with every number right.** Asked which pattern had the
  best option record, the copilot named one that lost ₹1,170 per lot — the three
  better ones had not formed that day, so they were not in its context at all. Check
  what the context *contains* before blaming the model.
- **When a guard misfires, fix the question, not the threshold.** Two false alarms
  went from 0.32 and 0.31 to 0.15 and 0.07 on one added criterion; moving the
  threshold would have hidden them and blinded the guard elsewhere.
- **`rolling().std()` is the sample standard deviation.** Bollinger's definition is
  the population one (`ddof=0`). The difference moved 76 signals and turned the
  system's best-looking record, +₹9,266/lot, into +₹794.
- **Split development and holdout on exit date, not entry date.** A trade entered in
  December and closed in January is priced with holdout data.
- **A missing file is not a holiday.** The options backfill recorded "no bhavcopy" as
  done, so a day fetched before its file was published was skipped forever — the
  archive went two sessions stale unnoticed. Ask the index archive whether a session
  happened.
- **NSE's "close" is each strike's last trade, not a synchronous price.** On a
  violent day a regression across strikes reads that timing noise as an 88% interest
  rate. Take the forward from the median of the strikes nearest spot, and judge a
  discount factor by the rate it implies.
- **A tripwire computed from the live value trips on nothing.** The pre-registration
  hash has to be a literal, or editing the hypothesis changes both sides of the check.
- **Pre-register before you look.** The IV filter's hypothesis was committed on its own
  (d1aa408) before any IV number existed. Reading the per-pattern table first and then
  choosing a threshold would have been fitting the filter to the answer — and that
  table flips direction from pattern to pattern.
- **Order matters in a verdict ladder.** A sample-size check that returns before the
  significance test hands small samples a better label than large ones.
- **A test can pin a bug in place.** One asserted that a thin holdout with no t-stat
  at all should be CONDITIONAL. Read what a failing test is protecting before
  "fixing" the code to satisfy it.
- **The normal distribution is not Student's t at n = 11.** The Bonferroni bar was
  2.79 where it should have been 3.55.
- Every bug found gets a regression test. That rule is why the suite is worth having.

## Next steps

1. **Phase 13 — trade journal.** Record what the user actually did (take / skip / wait)
   against what the system said. Pairs with the forward log. No API needed.
2. **Let the forward log accrue.** It is the only out-of-sample evidence that can't be
   fooled by better backtesting.
3. **Intraday: mining for edge, if you still want to.** The execution studies are done
   (see below). Anything further — opening-range breakouts, time-of-day effects — is a
   new hypothesis family that raises the Bonferroni bar for the daily patterns, and it
   can only be measured in index points, never in option money. Decide that trade-off
   before starting.
4. **Decide whether the copilot still needs a language model.** `composer.py` writes
   the daily explanation in Python and runs beside Gemini every day, graded by the same
   judge. Watch `grades_by_method` at `/api/copilot/record`: if the composed version
   closes the clarity gap, the model can be dropped from the daily explanation and kept
   only for typed questions. First readings — composed 1.99 honest / 1.38 clear against
   Gemini 1.79 / 1.53.
5. **Feed the guards real cases.** `/api/copilot/record` lists every withheld answer;
   each is a candidate case for `check_guards.py`.
6. **The audit's recommendations** — `docs/AUDIT.md`, ranked. Top three: replicate every
   pattern on BANKNIFTY options (doubles the trades behind each verdict with no new
   hypotheses), run the fast audit nightly with an alert, and store every trade with each
   research run. The binding constraint is sample size, not a shortage of indicators.

## Ground rules that must not slip

Never invent a number; never predict; never advise a trade; costs always applied;
nothing is "validated" from one split; the evidence bar rises with the number of
hypotheses tested. If a change would break one of those, it's a bug even if the tests
pass. Paid services are flagged and approved before use, never signed up for silently.
