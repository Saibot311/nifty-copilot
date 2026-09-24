# Handoff — read this first

Written 2026-09-21, updated 2026-09-24 (after the deep audit — `AUDIT_REPORT.md`). Start here, then `ARCHITECTURE.md` (how it's built, the five
invariants) and `PROJECT_PLAN.md` (what was decided and when, newest first).

## What this is

NIFTY 50 options **decision support** for one beginner trader. It never trades: no
broker execution path, and the user makes every decision. Its value is refusing to
manufacture a signal — most days it says NO TRADE, and that is the product working.

## Where it stands

**Phases 1–15 done.** Phase 13, the trade journal, and Phase 14, paper observation, are both in the
dashboard's **Journal** tab — log every session's decision there, including "stayed out". Phase 15,
deployment, runs the app on this Mac as two LaunchAgents (see Running it). The phases are finished;
what the system needs now is calendar time, not more code.

**The dashboard is live while the market is open** — the header and the paper book poll
`/api/live/tick` every 2s (Kite when logged in, NSE's feed otherwise). Everything else on the page is
still end-of-day by design: option premiums come from NSE's nightly file.

**Costs, since 2026-09-24:** each leg of an option trade is charged on its own premium — the buy on
what was paid, the sale (STT, slippage, fees) on what it sold for; 3.29% on a trade that sells at what it
paid, more on a winner, only the buy leg on a worthless expiry. Before, the whole round trip was charged
on the entry premium, which flattered winners. Every study was re-scored; paper rows opened before the
change keep the convention they were opened under (`paper_trades.cost_model` is NULL for them).

**Every verdict label faces the family bar**, not just the recommendation: pattern verdicts, the
index-level validation and the similar-days card use Bonferroni over all hypotheses judged (53 →
t ≥ 3.11 and more on few trades). Registered studies keep the bar frozen in their registration.

**The lot size is 65** — checked against NSE's own F&O file for 24 Sep 2026 (`NewBrdLotQty`, every NIFTY
option and future).

**The paper book has allocated funds and a daily policy.** Set the amount on the Journal tab; positions
size in whole lots against the book's current value, at most 40% each. Three policies are measured apart: patterns that
formed; `best_read` when nothing formed — one option, one direction, at the strike the money allows
(`briefing/option_choice.py`: the best *typical* 2018-23 trade among strikes whose whole lot fits —
never the mean, which would buy far out-of-the-money lottery tickets; in practice the deepest in the
money that fits), from the
best-evidenced signal firing that day (all of them rejected; a negative t is never followed), falling
back to the 20-session trend; and a weekly no-signal control, one lot each way, as the yardstick.
**The book takes one position a session, in one direction** — and never bets against itself: while a
call is held, a put is skipped (and the reason recorded), and the reverse. When several patterns form, the one with
the strongest holdout t takes the slot and the rest are reported as passed over. The control sits
*outside* the book: it spends none of the allocated money, moves none of the equity, and cannot take
the session's slot — it is a measurement, and without it a result has nothing to be compared against.
An in-the-money lot runs ~₹28,000, so the per-trade cap is 40% of the book — at 20% nothing could
open. A skipped position reports why — in the nightly log and on the Journal tab ("Last evening"),
from a record kept in `paper.db` (`paper_sessions`); until the audit the reasons were computed and
thrown away. **The book compounds:** wins and losses change its value and
positions are sized off that value, and the Journal tab shows the curve and the stated goal. That
scoreboard reaches nothing else — a test asserts the recommendation gate cannot see it.
`best_read` has no proven edge and says so on the row.

**Paper observation runs itself** (`briefing/paper.py`, nightly): each pattern that forms opens a
hypothetical position at the real closing premium, marked and closed on its tested schedule, against a
weekly no-signal control. Zero execution. It may never open a position for a session before
`FIRST_SIGNAL_DATE` — a paper trade on a past signal is a backtest in disguise.

**There is a news section on the Market tab.** Five dated feeds (RBI's own wire, ET Markets, Business
Standard, Mint, BusinessLine) plus NSE corporate filings, split by when a headline arrived relative to
the session a buyer can act in: pre-open, during, after the close. Jev reads each one and says whether
it is the kind of event that moves an index, which way it would push, and what it is about — a
description of the news, never a forecast. A judgment is stored once and never recomputed, because
re-judging after the market has moved turns hindsight into a signal, and an unjudged headline shows as
unjudged rather than as neutral. `api/data/news.db` is forward-only and **cannot be regenerated**: no
free source publishes dated Indian market headlines going back, so every row exists only because the
system was running that day. It is in the nightly backup set.

**The indicator grid under the Today chart (`/api/indicators`, `briefing/live_indicators.py`).** Eight
readings: price vs EMA20/50, RSI(14), ADX(14), ATR(14), the session range against ATR, the opening gap,
India VIX with its change on the day, and ATM implied volatility against 20-day realised. Relative volume
and VWAP were removed: NIFTY has no traded volume on the free feed, so they read "0.0x" and "Unavailable"
every day. In a session, NSE's open/high/low/last become a provisional candle that every reading
includes, and the page refreshes the grid every minute; after the close, a session the daily file does
not have yet is still counted from NSE's feed. Pre-open zeros are never a candle.

**"Which strategies fit today" (Market tab, `/api/strategy_fit`).** Python shortlists what is actually
forming — formed on the last close, would form if the index closed now (live 15-minute data), or within
1% of its trigger — and Jev reads, per strategy, whether today's trend, momentum and volatility are the
kind its premise was written for. Jev never sees a strategy's record, verdict or trigger, is never asked
about returns or direction, and its reading reaches neither the recommendation nor the paper book. Paid:
one request per reading, stored, and asked again only when the market picture changes and 15 minutes
have passed (question set `fit_v1` — bump it, never edit the wording). First reading, 25 Sep 01:34:
Prev-Day-Low Breakdown 0.91, Stochastic Oversold Reversal 0.86, Prev-Day-High Breakout 0.06 — all
three rejected on 2024-26, which the card shows beside them.

**Whether news pays is being tested, not assumed.** GDELT gives away a daily news-tone series back to
2018, which is why this could be backtested on the same 2018–23 / 2024–26 split as everything else.
Five hypotheses were registered before any was computed (hash `30439303ef31c290`), raising the family
count to 31 — so they face a higher bar than the 26 registered before them. The alignment rule matters
more here than anywhere: much of a day's market coverage is *about* that day's move, so a signal is
read off a completed UTC day and entered at the next Indian session's close. **Verdict: 0 of 5** — every
one rejected on 2024-26 (3,160 days of tone, 2018-01-01 to 2026-09-24). GDELT throttles by the size of
the request: fetch in 3-month windows (`backfill_news_tone.py` now defaults to it). The study's own bar
used 31 hypotheses — it left out the 22 replications that had already run; that is frozen in its
registration and changes nothing (its best t is 0.60 against bars above 3).

**The honest result so far: nothing has a proven edge.** 26 patterns, each judged
once on 2024–26 option data it never saw: **0 approved, 0 conditional, 26 rejected.**
Four apparent edges have now turned out to be bugs — two in earlier phases, and the
two CONDITIONAL verdicts, which the deep audit traced to a verdict ladder that
skipped the significance test for small samples. The forward log is the real test
now, and it needs calendar time.

**The user only BUYS options (calls or puts).** Frame every idea that way. Six structural
hypotheses beyond chart patterns — volatility pricing, FII and retail positioning, turn of month,
pre-holiday, opening gaps — were pre-registered and tested as bought options
(`backtest/structural_research.py`, Market tab, `/api/structural`): **0 of 6 approved.** The evidence
bar is now corrected for all 26 holdout tests, not just the 19 patterns.

**Replicated on BANKNIFTY, SENSEX and Midcap Select** (`backtest/replication.py`, Research tab,
`/api/replication`): the same rules and option setups on four indices, a date counted once. **0 of 22
pass**; NIFTY's best pattern failed on Midcap and SENSEX. SENSEX options only exist from Jan 2024 in
BSE's public archive, Midcap from Jan 2022. **GIFT Nifty** is live on the Market tab and snapshotted
nightly (no free history exists).

**Every holdout result carries a 95% bootstrap interval** (`stats/bootstrap.py`) and every holdout
trade is stored with its research run. Each pattern's edge over no-signal includes zero — the
intervals are the most honest thing on the dashboard.

**A market context engine answers "who makes money, and why did it move"**
(`api/market_engine/`, the dashboard's **Market** tab, `docs/MARKET_RESEARCH.md`). It
measures the variance risk premium (options priced above what followed on 71% of days
since 2018), attributes each day's move to global cues fitted only on earlier days,
reads NSE's participant-wise positioning (1,913 sessions), and tests NIFTY's expiry days
for manipulation footprints (none clear). The copilot answers market questions from it.

**Implied volatility is computed from the options archive** (`options/iv.py`) and
tracks India VIX at a correlation of 0.983. It describes every pattern's trades. Its
one pre-registered test as a filter — buy only below the one-year median — was
**not adopted**: the right direction in both periods, but holdout t = 0.43.

**A deep audit of Phases 0–12 was run on 2026-09-21** — read `docs/AUDIT.md`. It
found and fixed 14 bugs, and it ends with a ranked list of what to build next.

## Running it

```bash
./scripts/check_all.sh          # the checks and the whole test suite — run before and after changes
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

**The app is deployed on this Mac** (Phase 15): two LaunchAgents run the built dashboard and the API,
start at login and restart on crash — bound to `127.0.0.1`, or to every interface with `--lan` (always
pass `--lan` if the phone is used; without it the phone cannot connect).

```bash
./scripts/install_app_services.sh            # build + install, this Mac only
./scripts/install_app_services.sh --lan      # also reachable from your phone (token required)
./scripts/install_app_services.sh --status   # services, endpoints, network, stale build
./scripts/install_app_services.sh --remove   # frees :3000 and :8000 for dev servers
```

**Phone access** (`--lan`): both services bind every interface, and both demand the token from
anything that is not this Mac — the API in `api/access.py`, the page itself in `web/gate.mjs`, run by
`web/server.mjs` (a thin custom server, because only the socket knows who is asking; until 2026-09-24
the page was served to any device on the Wi-Fi). A phone carries the token as a cookie, set the first
time it opens the pairing link; phones paired before then send their stored token once, automatically.
Both also refuse a Host header that does not name this Mac (DNS rebinding) and writes from another
site's page. Pair from the dashboard *on the Mac* — "Use this on my
phone" shows a QR code; the token is written to `api/.env` and shown nowhere else, not in a log and
not to a remote caller even with a valid token. "Forget paired devices" rotates it. Only do this on a
network you trust — there is no TLS, so treat it as a lock on a door, not a security system. For
outside the house, put both devices on a private network (Tailscale or similar) rather than opening a
port.

**A watchdog** (`com.niftycopilot.watchdog`, every 10 minutes) restarts a service that has stopped
answering. launchd's KeepAlive covers a process that dies; this covers one that is alive and wedged —
verified by SIGSTOPping the API and watching it come back. One miss is treated as a cold start; two
in a row is a restart plus a notification. Log: `api/data/health_watch.log`.

The services serve a *build*, so edited code is not live until the installer runs again — `--status`
says when the build is stale. They also hold the ports: **run `--remove` before starting dev servers**
through the harness preview tool (`nifty-copilot-api`, `nifty-copilot-web`), and reinstall afterwards.
First page load after a restart takes ~15-60s because every cache is cold.

**Daily:** a LaunchAgent runs `api/scripts/daily_job.py` at 19:30 on weekdays (forward
log backup, forward log, bar top-ups, option top-ups plus any gap since 2018, option
research, IV, positioning, the structural tests, market studies). Verified running unattended. Logs:
`api/data/daily_job.log`. Remove with `./scripts/install_daily_job.sh --remove`.

**Zerodha login expires every day at ~6 AM IST.** Without it, 15-minute bars and live
tracking fall back or skip; everything else still works.
Re-login: <http://127.0.0.1:8000/api/zerodha/login>

A second LaunchAgent (`./scripts/install_login_check.sh`, weekdays 08:45 and 12:30) checks whether
today has a session and, if not, opens that page and raises a notification — then records the
outcome. **It is not an auto-login and must never become one:** that would mean keeping a broker
password and a 2FA seed on this disk, and Zerodha requires a person. `tests/test_login_log.py` fails
if `pyotp`, `selenium` or a password/TOTP name ever appears in that code path. The record of which
days had a session is in `login_log.db`, summarised at `/api/zerodha/status` and in the header pill;
the days without one are the days 15-minute bars are missing.

## Secrets

All in `api/.env` (gitignored, never in chat or commits): `KITE_API_KEY`,
`KITE_API_SECRET`, `LLM_API_KEY` (Gemini free tier), `LLM_PROVIDER`, `TYPESAFE_API_KEY` (Jev).
To add one, prompt for it — never put a key in the command text:

```bash
read -s "k?Paste key: " && echo "NAME=$k" >> ~/Documents/NIFTY-Trading-App/api/.env && unset k && echo " saved"
```

## Data on disk (all gitignored; the bold ones cannot be regenerated)

| File | What | Rebuild |
|---|---|---|
| `api/data/nifty_options.db` | 4.57M option bars, 2018→now (655 MB) | `scripts/backfill_options.py` |
| `api/data/nifty_bars.db` | 15-min bars from 2015-01-09; daily from 1990 | `scripts/backfill_bars.py` |
| `api/data/pattern_options.json` | Pattern → option research output | `scripts/pattern_options.py` |
| `api/data/strategy_status.db` | Validation verdict history | `scripts/validate_all.py --all` |
| `api/data/intraday_research.json` | Execution studies on the 15-min archive | `scripts/intraday_research.py` |
| `api/data/iv.db` | Daily 30-day implied volatility from 2018 | `scripts/iv_research.py` (incremental) |
| `api/data/iv_research.json` | IV description of every pattern, VIX check, the pre-registered test | `scripts/iv_research.py` |
| `api/data/structural_research.json` | The six pre-registered structural tests | `scripts/structural_research.py` |
| `api/data/options_banknifty.db` · `options_midcpnifty.db` · `options_sensex.db` | Other indices' option archives (NSE 2018→ / Jan 2022→; BSE Jan 2024→) | `scripts/backfill_other_indices.py` (resumable; `--recent` nightly) |
| `api/data/nse_indices.db` | NSE's own daily all-index report, 2017→ — Midcap Select levels, and the close Yahoo sometimes lacks | `scripts/backfill_nse_indices.py` |
| `api/data/replication.json` | The pooled multi-index replication | `scripts/replication.py` |
| **`api/data/journal.db`** | **Your trade journal** | **Cannot be rebuilt** — backed up nightly with the forward log |
| **`api/data/paper.db`** | **Paper positions, opened forward** | **Cannot be rebuilt** — backed up nightly |
| `api/data/login_log.db` | Which days had a Zerodha session, and when it started | Accrues daily; deletable |
| **`api/data/gift_nifty.db`** | **Nightly GIFT Nifty snapshots, from 2026-09-22** | **Cannot be rebuilt** (no free history exists) — backed up nightly since the audit |
| **`api/data/news.db`** | **Every headline, stamped when this system first saw it, and Jev's one judgment of it** | **Cannot be rebuilt** — backed up nightly |
| `api/data/news_tone.db` | GDELT daily tone, 2018→ | `scripts/backfill_news_tone.py` (3-month windows) |
| **`api/backtest/hypothesis_log.jsonl`** | **Every strategy and parameter set ever run** | **Cannot be rebuilt** — backed up nightly (gzipped) since the audit |
| `api/data/participant_oi.db` | NSE participant-wise open interest (Client/DII/FII/Pro), 2019→ | `scripts/backfill_participant_oi.py` |
| `api/data/market_research.json` | The market engine's studies | `scripts/market_research.py` |
| `api/data/copilot_log.db` | Every answer, its grades, and the Gemini-vs-composed comparison | Accrues in use; deletable (holds your questions) |
| **`api/data/forward_log.db`** | **Each day's verdict, written before the outcome** | **Cannot be rebuilt** — backed up nightly (30 kept) to `BACKUP_DIR` in `api/.env` — set 2026-09-22 to iCloud Drive `NIFTY-Copilot-Backups/`, so a lost disk doesn't take it too. Falls back to `api/data/backups/` if unset. |

## The dashboard

Four tabs. **Today** answers one question — what is the call, and what would change it: the verdict
and the chart side by side, the copilot, the patterns in play, then the forward record, implied
volatility, the briefing and analogs in a two-column grid. **Research** is every pattern as one dense
table with a 95% range bar per row on a shared scale (seeing every range touch ₹0 is the point), then
the multi-index replication. **Market** is the context engine. **Journal** is yours to fill in daily.

Rules that keep it readable: one card per idea, not one card per number; a caveat is stated once, not
on every row; detail hides behind a row you click; two columns above 1100px. It was a 4,300px column
of identical cards before 2026-09-23 — don't let it drift back.

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
- **A detector must be judged by how often it fires on ordinary days.** The first
  unusual-activity monitor compared strikes with their own earlier days and flagged
  everything the day before expiry; the second, at z ≥ 3, still fired on 40% of sessions,
  because volume shares have fat tails. z ≥ 5 fires on 8%, measured.
- **The same-date US session had not happened when India traded.** Global cues must be
  the last session that closed *before* India opened, or they look far more explanatory
  than they are.
- **Open interest is what is held at the close.** Most retail option buying is intraday,
  so participant OI cannot show retail losing — only SEBI's P&L studies can.
- **Order matters in a verdict ladder.** A sample-size check that returns before the
  significance test hands small samples a better label than large ones.
- **A test can pin a bug in place.** One asserted that a thin holdout with no t-stat
  at all should be CONDITIONAL. Read what a failing test is protecting before
  "fixing" the code to satisfy it.
- **The normal distribution is not Student's t at n = 11.** The Bonferroni bar was
  2.79 where it should have been 3.55.
- **Yahoo is missing real sessions.** 12 since 2018 — 1 January sessions, Budget-day and Muhurat
  specials, two ordinary days. Ask the Zerodha archive whether a session happened (holidays, calendar
  effects); Yahoo stays the trading calendar only so results match the pattern research.
- **An unsure router must get everything.** "No scope" silently meant the "today" slice, so an
  ambiguous question lost the pattern records and market studies. A test asserted exactly that.
- **Audit 8.2 fails when a new session lands before the nightly research re-runs** — it recomputes
  the baseline on today's data and compares with last night's stored t. Re-run
  `scripts/pattern_options.py` before believing it.
- **A server stuck in reload is not a code bug.** A hung request can hold uvicorn's reload at
  "Waiting for background tasks"; every endpoint then times out. Restart the preview server.
- **Five parallel downloaders got ~46 days refused** (a solid July–August 2025 run). Missing days are
  never marked done, so one slow rerun (`--delay 1.0`) filled them. Keep backfills to 2–3 streams.
- **The PCR pattern read NIFTY's option chain whatever index it ran on.** Anything replicated must be
  checked for hard-wired NIFTY inputs (`pcr_db=` now selects the archive).
- **Yahoo does not carry NIFTY Midcap Select** — NSE's `ind_close_all_DDMMYYYY.csv` does, from Jan 2022.
- **A row written after its entry session opened is not forward evidence.** Two were (17 and 21 Sep),
  one of them while testing the Yahoo fix. `record_if_final` now refuses; late rows are marked and
  excluded, never deleted. Beware of any code path that records while you are testing.
- **launchd's PATH has no node**, so the nightly audit's build check failed on nothing. The agent now
  carries a PATH, and the check SKIPs when npx is missing.
- **Rounding a number for the copilot breaks the number guard.** Audit 12.2 caught a rounded interval
  that no computed source contained. Hand the model full precision.
- **A fix written into one loader is not a fix.** The Yahoo top-up lived in `backtest/strategies.py`,
  so the snapshot and briefing showed an older session than the rest of the page for a day. It is in
  `market_data.nse_indices.top_up` now, and a test asserts every loader shares it.
- **A server-rendered page is frozen at page-load time.** `AutoRefresh` re-fetches it; `LiveTicker`
  keeps the header ticking. Without those, "live" means "live when you opened the tab".
- **A production origin is not the dev origin.** Opening the deployed dashboard at `127.0.0.1:3000`
  sent that origin, the API's CORS list had only `localhost:3000`, and every client-side fetch failed
  while the server-rendered page looked perfect. Both spellings are allowed now; audit 15.1 guards the
  list against a wildcard.
- **Two processes write these SQLite files** — the API service and the 19:30 job. Every store opens
  through `storage/sqlite_open.py` (WAL + a 30s busy timeout); the defaults gave "database is locked".
- **KeepAlive does not catch a wedged process**, only a dead one. That is what the watchdog is for.
- **An exception raised inside a middleware never reaches FastAPI's handler** — it becomes an opaque
  500. The token gate returns its refusal instead, so a phone is told what to do.
- **A library can hold a request open forever.** NSE's client sends every request — its cookie
  handshake included — with no timeout; one silent socket froze the price, the market status and the
  option chain behind a stale-while-revalidate cache that no longer refreshed. The shared session now
  carries an 8s default (`live_quote._timeout_session_class`).
- **`yf.download` leaks a connection per call.** 40 fetches left 40 sockets open, which garbage
  collection never freed, against launchd's 256-file limit. `Ticker.history` on one shared session holds
  the count flat; the services now also run with 4,096.
- **`/health` proves nothing about files.** It answered while every endpoint that opens a database would
  have failed. The watchdog asks `/health/deep`.
- **A file a script made from a shell is not one launchd may open.** The watchdog's stdout pointed at
  the log its own script created; launchd refused it (exit 78) on every run, so the watchdog never ran.
  Give a LaunchAgent a log file of its own.
- **Yahoo drops sessions in the middle of the series, and the series then changes under you.** 22 Sep
  2026 was there that evening (topped up from NSE) and gone the next day. Recent gaps are filled from
  NSE's own report (`nse_indices.GAP_FILL_FROM`); older ones are left as the research measured them.
- **A check dated to the wrong session can never be true.** The paper book kept a pattern only if the
  scan's date equalled the signal date; at 19:30 the scan is dated to the entry session, so no pattern
  position ever opened. Read the rule off history truncated at the signal close.
- **The evidence bar counts every family that looked at the holdout** — patterns, IV, structural,
  replication and news (`backtest/family.py`, 53 on 2026-09-24). A family added later has to be added
  there, or the bar quietly stays low.
- **Tomorrow is not in the data while it trades.** "No later session" is not "not started": the forward
  log now falls back to the calendar before accepting a row.
- **Taking money out of the paper book is not a loss.** Its high-water mark once showed −₹50,000 after
  two withdrawals. Drawdown is measured on what trades made.
- Every bug found gets a regression test. That rule is why the suite is worth having.

## Next steps

1. **Let the paper record and the journal run.** Paper observation gives the rejected setups a live,
   out-of-sample test at zero risk; it needs about 15 closed trades before it says anything.
2. **Use the journal every session, and let the forward log accrue.** They are the only evidence that
   can't be fooled by better backtesting; both need calendar time.
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
