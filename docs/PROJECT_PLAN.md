# NIFTY COPILOT — Project Plan

Living document — the *chronological* record of what was decided and when. For how the
system is structured (layers, invariants, the strategy lifecycle, how to extend it), see
**[ARCHITECTURE.md](ARCHITECTURE.md)**.

Current status: **Phases 1-12 done and audited (see AUDIT.md)** (Phase 12's copilot needs an API key to run), plus the options
integration and the pattern → option reframe built out of phase order on request.

**How the market works, who makes money, and a market context engine (2026-09-22).** Asked, after
every pattern was rejected: people do make money here — how? Researched and built; the write-up is
[MARKET_RESEARCH.md](MARKET_RESEARCH.md).

*The answer, from SEBI's client-level studies:* individuals lose and institutions trading with
algorithms win — 93% of individuals lost over FY22-FY24 (₹1.8 lakh crore); proprietary desks made
₹33,000 crore and FPIs ₹28,000 crore in FY24, 96-97% through algorithms; in FY26 87.7% of
individuals lost ₹91,685 crore, 92% of it on options, with 59% of index-options turnover in
same-day contracts. *And measured on this system's data:* options were priced above the volatility
that followed on 71% of 2,126 days since 2018, every year between 60% and 81% — the variance risk
premium sellers collect and buyers pay, until a crash (Feb-Mar 2020: ~16-24% priced, ~80-88%
delivered). Buying each pattern's option on a schedule with no signal lost a median ₹959 per lot.
The patterns' rejection is the expected result for a buyer of index options on public information.

*The engine* (`api/market_engine/`, the Market tab, `/api/market`): **why it moved** — NIFTY's
return against the S&P 500, the rupee and Brent, each from the last session that closed before
India opened, with betas fitted only on the year before; global cues explain 1-17% of daily
movement depending on the year. **Who is on the other side** — the variance risk premium, SEBI's
figures, and NSE's participant-wise open interest (1,913 sessions since 2019; longs equal shorts to
within 2 contracts every day). **Expiry days** — tests of the footprints manipulation would leave:
morning moves reversed in the afternoon (the pattern alleged in SEBI's Jane Street order, on Bank
Nifty), the last-30-minute settlement window, and closes pinned at strikes. On NIFTY, none is clear:
reversal z = -0.58 overall and 0.47 in Jan 2023-Mar 2025; pinning 22.5% vs 18.4% (z = 1.91), the
direction the literature reports. **Unusual strike activity** — each strike's share of volume against
the same point before expiry in the last 20 expiries; the first version flagged everything the day
before expiry, and z >= 3 still fired on 40% of sessions, so the threshold is 5, which fires on 8%.
**What the research says** — 13 sourced principles: how markets work, what moves NIFTY, the law
(SEBI Act s.12A, PFUTP 2003, PIT 2015; Rakhi Trading 2018, Sadhna Broadcast 2023, Jane Street 2025),
philosophy, and how manipulation works and reaches a retail trader.

*The copilot* gained a `market` route and scope (16/16 labelled routes on the live model). Its first
market answer was true sentence by sentence and graded 0.62 on honesty — it described option selling
as a way to make money without the crash risk. A rule now requires the risk alongside any way of
making money; the same question graded 0.95.

**Implied volatility — a description, and one test that failed honestly (2026-09-21).** The top
"trade recognition" recommendation from the audit. For someone buying options the volatility priced
in at entry matters as much as direction, and the archive already held everything needed to compute
it. `options/iv.py` backs implied volatility out of NSE closing prices with Black-76, reading each
expiry's forward and discount factor off put-call parity instead of assuming an interest rate
(rates ran from 3% to 7% over the period). `backtest/iv_research.py` builds a 30-day
constant-maturity series from 2018 by interpolating total variance between expiries.

*Checked against the exchange's own number.* India VIX is NSE's 30-day volatility from the same
market, computed differently (the whole strike range rather than at the money). Over 2,130 days the
two correlate at **0.983**, with VIX a median 1.25 points higher because it also prices the skew. Two
stress days caught real problems on the way: on 2024-06-04 the parity regression read a 9-day
discount factor of 0.978 — an 88% interest rate — because NSE's "close" is each strike's last trade
and on a violent day those are not simultaneous; and on 2020-03-23 no strike near spot had been
listed yet, so an "at-the-money" vol was being read off a strike 5% away. The forward now comes
from the median of the nearest strikes, a discount factor is kept only if its implied rate is
plausible, and no ATM vol is reported without a strike within 2% of the forward.

*Described first.* Every pattern's trades now carry the IV they were bought at. It shows the
climate each pattern fires in — squeeze breakouts upward and overbought reversals buy cheap options
(24th-26th percentile), Bollinger Band Reversion, the bearish Supertrend flip and PCR capitulation
buy expensive ones (68th-73rd). And it shows something worth knowing before blaming volatility: the
*market's* 30-day IV barely moves while these trades are held (median -0.05 points), while the IV
of the contract held rises 1.8 — that is the contract sliding along the skew, not fear draining
out. What hurts these trades is time decay and direction, not an IV collapse.

*Then tested once, as fixed in advance.* The hypothesis — trades bought when 30-day IV is at or
below its one-year median earn more per lot — was committed on its own (d1aa408) before any IV
number existed, with a hash test that fails if it is edited. Pooled across every pattern's chosen
setup, one observation per entry day, Welch's t: low-IV entries did better in both periods
(development +₹1,291 per lot, holdout +₹964), but the holdout t is **0.43** against a bar of 1.97.
**Not adopted.** In the holdout both groups lost money anyway (-₹2,322 and -₹3,286 per lot), so the
filter would at best have made losing patterns lose less. The per-pattern table flips direction
from one pattern to the next; picking its favourable cells would have been choosing a filter after
seeing the answer, which is why the test was fixed first.

Surfaced as an Implied Volatility card on the dashboard (today's IV, its percentile, the past year,
and the test's verdict), a line on every pattern, and one sentence in the copilot's explanation.
Audit checks 0.8 (tracks VIX) and 5.6 (the percentile never looks ahead) added. Runs nightly.

**Deep audit of Phases 0–12: 14 bugs found and fixed (2026-09-21).** Full report in
[AUDIT.md](AUDIT.md). A new `api/audit/` package checks every phase against the data the system
actually runs on — real data rather than fixtures, independent reference implementations rather
than the same code run twice, and the *impact* of each problem measured rather than merely noted.
44 checks; `check_all.sh --deep` runs them.

*What changed for you:* **both CONDITIONAL verdicts are gone — all 26 patterns are now REJECTED.**
They held CONDITIONAL only because the verdict ladder checked sample size before significance and
returned early, so a pattern on fewer than 15 holdout trades skipped the t-test entirely. With t =
0.86 and 0.50 neither was close. The existing tests contained one that pinned this bug in place.
And **the system's best-looking record, Bollinger Upper Rejection at +₹9,266 per lot, was mostly an
artefact**: the Bollinger bands used pandas' sample standard deviation instead of Bollinger's
population one, 2.6% too wide, moving 76 signals across the two patterns built on them. With
correct bands it is +₹794.

*The rest:* the significance bar used the normal distribution where Student's t applies (2.79 vs
3.55 on 11 trades); the t-test treated the no-signal baseline as exact (now Welch); two development
trades were priced with holdout data (the split was on entry date; now purged); the options backfill
recorded "no file yet" as "done", so last Tuesday and Friday were silently missing and would never
have been fetched (14 sessions restored; a `--fill-gaps` mode now runs nightly); trades that could
not finish were counted as finished; the index engine held one session longer than everything else;
max drawdown ignored losses from the starting balance; four sessions of 15-minute bars carry bad
ticks up to 230 points outside the day's range (now clamped on load); the regime classifier labelled
30 bars instead of raising; arbitrary symbols reached Yahoo; and the one irreplaceable file, the
forward log, had no backup (now nightly, verified).

*What held:* no indicator, regime label, strategy or analog uses the future — checked at random cut
points across every series, all 26 strategies and 410 instrumented similarity test points. Five of
seven indicators match Wilder's and Lane's definitions exactly. No secret appears anywhere in git
history. Phases 9–12, the most recent work, were clean on the first run; every bug was in the older
foundations.

*What to do next,* ranked in AUDIT.md by how much evidence each adds rather than how much signal:
replicate every pattern on BANKNIFTY options, run the fast audit nightly, store every trade with
each research run. Ten of 26 patterns are judged on fewer than 15 trades; the binding constraint is
sample size, and every new indicator is a new hypothesis that raises the bar for all the others.

**A copilot that can write without a model (2026-09-21).** Asked whether Jev could be trained
alongside Gemini and eventually replace it. It cannot: there is no fine-tuning, and Jev does not
generate prose at all — every output is a probability distribution over options you supply. But the
question has a better answer than no.

Every guard in `copilot/` exists because a language model might invent something. The daily
explanation asks the same question every day over structured data, so `composer.py` now assembles it
in Python from the same context the guards check against. Invention becomes impossible by
construction: I2 stops being an invariant we police and becomes one the code cannot break. What is
given up is fluency and the ability to answer an unanticipated question, which is why typed
questions still go to the model.

It is put through the same three guards deliberately, rather than trusted. It should never be
blocked — every number in it came from the context — so a block would mean either a template says
something the data does not support or a guard is wrong. `composed_blocked` in the record is the
alarm for that, and should stay at zero.

*The comparison is the point.* Both versions run every day and the same judge grades both, so
whether to drop the model is settled on the record rather than on taste. First readings: composed
scores **1.99 honesty / 1.38 clarity** against Gemini's **1.79 / 1.53** — exactly the predicted
shape, winning on honesty (it can be written to always state the weakness) and losing on clarity.
If that gap closes, the model goes.

*It earned its place the same afternoon.* Gemini's free tier returned HTTP 503, and instead of a
502 the dashboard served its own explanation. That exposed a bug immediately: the fallback was
cached, so one transient outage would have been the day's explanation until tomorrow. Only a model
answer is cached now — the composed one costs nothing to rebuild.

Three small things the first render caught: a numeral opening a sentence ("2 patterns formed"), a
doubled full stop from embedding the analog verdict (which is itself a whole sentence with its
explanation after a colon), and 202 words against a 180 target.

**Copilot: the context follows the question (2026-09-21).** Route-scoped context, the last
unbuilt item — and it turned out not to be the token-saving exercise it was written up as.

The default digest carries the patterns that formed on the last close plus those near firing. Asked
"which pattern has the best option record?", the copilot answered from those four and named
Stochastic Oversold Reversal, which **lost ₹1,170 per lot**. The three best records — Bollinger
Upper Rejection at +₹9,266, Bollinger Band Reversion at +₹3,667, RSI Overbought Reversal at +₹915 —
were not formed that day, so they were not in the context at all. Every figure in that answer was
real and checked. The answer was still wrong, and no guard could have caught it: the guards verify
what an answer says against the context, and the context was the thing at fault.

`build_context(scope=...)` now serves three views. `today` is the dashboard as it stands and is what
the daily explanation still gets, unchanged. `pattern_record` carries all 26 researched patterns
ranked by measured record, with unmeasured ones kept and marked — "not measured" is a different
answer from "did badly" — and skips the analog search entirely, so it is also faster. `method`
carries the system's own rules and the analog test's verdict, and drops the pattern lists and live
data. The rules themselves are now written down in `HOW_IT_DECIDES`, including what development and
holdout mean, after the copilot honestly answered "the word holdout is not explicitly in the data".

The scope is applied only when the router is sure (>0.7 on the chosen route); below that, and on any
router outage, the full context goes, which is what happened before routing existed. A wrong slice
removes the very facts an answer needs, so uncertainty has to fall back, not guess.

Re-asked afterwards, the copilot named Bollinger Upper Rejection, explained that its t of 1.48 still
leaves it REJECTED against a bar of 2.79, said no pattern is APPROVED, and listed both CONDITIONAL
ones. Graded 1.93 honest, 1.47 clear.

**Copilot: grades, drafts and a record (2026-09-21).** The rest of the planned Jev/Gemini pairing,
built. The theme is the same one the whole project runs on — measure it rather than assert it.

*A record (`storage/copilot_log_db.py`, `/api/copilot/record`).* Until now a review was computed,
used once to decide whether to show an answer, and thrown away. Nobody could say how often a guard
fires, on what, or whether a wording change helped — all 42 labelled cases were synthetic, written
by the same hand that wrote the questions. Every answer is now recorded with what the guards made of
it, and the summary lists withheld answers specifically, because each is a candidate labelled case.
This is the copilot's forward log. Unlike the forward log its rows may be deleted: they hold the
questions the user typed, and nothing in it feeds a verdict.

*Grades (`copilot/grading.py`).* The guards are pass/fail and none of them can tell a properly
hedged explanation from a technically-true one that leaves a beginner over-confident — which is the
entire product. Two 0-2 scores now ride the same Jev request as the guards, so they cost nothing:
honesty about how weak the evidence is, and clarity for a beginner. They never block; a low grade is
recorded, not acted on. Their value is the trend, so a prompt change can be judged instead of
guessed at.

*Best of two drafts.* The daily explanation is written twice and the better-graded one kept — it is
read every day and costs one extra call a day. A typed question is written once: the guards already
decide whether it is safe, and grades only choose between two safe answers. A clean draft always
beats a better-written blocked one.

*The grading cases caught two bugs in my own writing.* Four answers were written to check the score
ordering (a hedged answer must outrank a flattering one on honesty; a plain one must outrank a
jargon wall on clarity — 4/4 correct, and the flattering answer scored 0.4 on honesty against 2.0).
But the answer written to be the *ideal* one was blocked by two guards, and both were right.
"So there is nothing here worth acting on" is the writer telling the reader what to do, at 0.51.
And "nothing that formed on the last close has ever shown a reliable edge" presupposes patterns that
formed, when DATA says none did, at 0.95 not-in-data. Both are now labelled cases. 48/48.

Also fixed: when a rewrite and the draft before it both failed, the tie went to the draft, so the
reported answer was the one the model produced *before* it saw the feedback.

**Intraday archive put to work — on assumptions, not edge (2026-09-21).** 11.7 years of 15-minute
bars had been sitting unused since the backfill. The tempting use was mining them for intraday
patterns; the right first use was not. A new intraday pattern is a new hypothesis family that raises
the Bonferroni bar for all 26 daily patterns, and it could only ever be scored in index points,
because the options archive is end-of-day. Testing the *execution assumption* every existing number
already rests on costs no hypotheses at all. `backtest/intraday.py`, three studies:

*A. The opening print is not a price you can get.* The archive and the daily series agree on the
open to within a hundredth of a point, so the data is sound — but the index sits 0.042% **below**
that print 15 minutes later, and it does so in 12 years out of 12, dev t=-6.96 and holdout t=-2.13.
Probably the pre-open call auction rather than anything tradeable. The consequence for this system:
a long entered slightly late is bought cheaper than the backtest assumes and a short sold cheaper,
so every CE result is mildly conservative and every PE result mildly optimistic by about that much
per trade. Too small to overturn any current verdict — and nothing here is close enough for it to
matter — but the right size to matter for one that ever gets close. The larger number is the std:
being 15 minutes late adds 0.31% of noise to every entry, which dwarfs any per-trade edge claimed
so far.

*B. No entry time beats the next open — and the way it failed is the finding.* Five fixed entry
times, the same signals, the same exits. The first cut said "enter at the close, +0.098% on the
holdout, t=3.8". That was confounded: entering later means less time in the market, and the holdout
is a falling period for mostly-long strategies. Adding a direction-matched baseline (the same fix
the strategy verdicts already use) did not rescue it either — the excess was -0.032% on development
data (t=-4.8) and +0.047% on the holdout (t=+4.0). Two significant results pointing in opposite
directions measure the period, not the execution. `_verdict` now requires the sign to agree across
both periods before anything is called a finding, and reports UNSTABLE when it does not. The
next-open rule (I1) stands, unchanged and now actually tested.

*C. When the index moves.* Descriptive only: range by 15-minute slot, busiest at the open. Three of
25 slots have drift clearing |t|>2, which is roughly what testing 25 slots at once produces by
chance, and it is stated next to the number.

No new hypotheses were added to the evidence bar. The studies are saved by
`scripts/intraday_research.py` and served at `/api/intraday/research`; there is no dashboard card,
because none of this is a daily decision input.

**Copilot guards built out: claims, routing, one call (2026-09-21).** The planned Jev/Gemini pairing
below is now built, except context slicing. Three things changed.

*A claim guard (`copilot/claim_guard.py`).* The number guard catches invented figures and the
forecast guard catches predictions, but neither catches "volatility has been elevated all month" —
no figure, no forecast, and nothing in the data behind it. One Jev choice question per sentence now
asks how DATA relates to it: supported, contradicted, not in data, or not a factual claim at all.
That fourth option is what makes it usable — an explanation is mostly framing and caveats, and
scoring those as unsupported would withhold every honest answer. Flags above 0.6 combined
contradicted + not-in-data, looser than the forecast guard's 0.3 on purpose: a forecast getting
through breaks the promise, while a twitchy claim check just makes the copilot useless, and the
number guard already covers the dangerous case.

*Both guards ride one request (`copilot/review.py`).* They are independent judgments over the same
evidence, so they go together: one round trip, one bill, and the forecast questions now see what the
system actually computed rather than judging tone alone. The number check runs first and
short-circuits the Jev call — a draft already being rewritten is not also paid for semantically. One
retry now names every problem at once (bad numbers, unsupported sentences, forecasts) instead of
numbers only.

*A router (`copilot/router.py`).* A Jev choice classifies the question before Gemini is called at
all. An off-topic question is refused by code — no model call, nothing to guard. This copilot
explains one dashboard; it is not a general chatbot. The other three routes are recorded but not yet
acted on: sending only the relevant slice of context is the obvious next step, but a narrower
context also narrows what the answer may mention, so it needs its own labelled cases first.

*Measured, not asserted.* `scripts/check_guards.py` (was `check_prediction_guard.py`) now holds 42
labelled cases across all three guards and prints an accuracy sweep over candidate thresholds. First
live run: 15/17 forecast, 15/15 claims, 10/10 routes. The two failures were both false alarms where
reporting a computed verdict read as advice — "buy a 2% ITM call, hold 10 days" at 0.32, and "that
option lost ₹1,170 per lot, so it is rejected" at 0.31. The sweep showed a threshold of 0.4 would
have made them disappear, which is exactly the wrong fix: it hides the confusion and blinds the
guard elsewhere. Adding two criteria examples (naming the option the system computed is part of the
verdict; REJECTED is a finding, not a warning to stay out) moved them to 0.15 and 0.07 — 42/42, with
the highest pass at 0.15 and the lowest block at 0.44.

*Two bugs the live run found.* The splitter treated a whole bulleted block as one claim, so a false
sentence could have averaged out against true ones beside it — it now splits lines before sentences.
And a sentence scored 1.0 supported was reported with verdict "contradicted", because the label was
a tie-break between two of the four options rather than the model's own pick. Both have tests.

**Copilot: how to improve Jev and its pairing with Gemini (2026-09-21, planned — claims, routing and
the single call are now built; best-of-N drafts and daily grading are not).**
Jev cannot be fine-tuned — it is a hosted judgment model. "Training" it here means improving the
questions, the state it sees, and the thresholds, measured against labelled cases:

1. *Questions and criteria are the biggest lever.* Rewriting one question around whose claim it is
   moved a false positive from 0.64 to 0.05. Worked examples in the criteria did most of that.
2. *Grow the labelled set.* `scripts/check_guards.py` holds 42 cases. Every answer the
   guard gets wrong in real use should be added, with the right label, and the script re-run after
   any wording change — the unit tests mock the service, so only this measures the real model.
3. *Tune the threshold on those cases,* not by taste. 0.3 today, chosen because a missed forecast
   is worse than a withheld explanation.
4. *Give it more state.* It currently sees only the answer text. Passing the computed verdict
   alongside would let it check "is this claim attributed to the system, and does the system
   actually say that", rather than judging tone alone.

Pairing with Gemini (Gemini writes, Jev judges — each doing what it is built for):

- **Verify claims, not just numbers.** A noul per sentence: "is this supported by DATA?" — the
  citation-check pattern. Catches unsupported non-numeric claims the current guards miss.
- **Pick the best of N drafts.** Gemini's free tier makes 2-3 drafts cheap; a Jev *choice* selects
  the clearest one, or a *score* rates it and anything below the bar is regenerated.
- **Route questions before answering.** A *choice* over the question ("about today / about a
  pattern's record / about method / off-topic") decides which slice of context to send — smaller
  prompts, better answers, and off-topic questions answered without a model call.
- **Grade the copilot daily.** Score each saved explanation for honesty and clarity; track it over
  time so prompt changes can be judged instead of guessed at.

All of this is cheap (~$0.042/M input tokens, output free) and none of it may put model output into
the decision path: Jev gates or selects text, never produces a number the dashboard shows.

**Phase 12 verified live (2026-09-21):** both keys added; copilot works end to end. Two things the
live run taught us. (1) `gemini-2.5-flash` is closed to new keys — default is now `gemini-3.6-flash`,
the model Google's own error names. (2) Gemini 3.x are reasoning models: they spend tokens thinking
before any visible text, so a small `max_tokens` returns an empty message with finish_reason
"length" and no error status. Budget is now 4000 and the client raises a clear error on empty text.
Guard tuning against the real model: the first wording blocked "the system recommends a CALL
because…" at 0.64 — a false positive on the copilot's own job. Rewritten around *whose* claim it is
(writer's forecast vs reporting a computed verdict), with examples: 9/9 labelled cases now correct,
kept as scripts/check_guards.py. Asked directly for a prediction and a buy signal, the
copilot refuses and reports the verdict instead.

**Copilot gains a forecast guard via TypeSafe Jev (2026-09-21):** the number guard can't catch
"this looks set to rise" — a prediction with no figures in it. That judgment is semantic, so it
goes to Jev (TypeSafe's System One model), which returns typed probabilities rather than prose:
two noul questions asked together — does the text predict the market, does it tell the reader to
trade — with criteria that explicitly allow *reporting* the system's own verdict. Blocks above 0.3,
deliberately low because letting a forecast through breaks the product's promise while a withheld
explanation costs one click. Optional and fails open: no key or a service outage marks the answer
"forecast check skipped" rather than blocking. ~$0.042/M input tokens, output free.

**Phase 12 built — LLM copilot on a free tier (2026-09-18):** you chose a free hosted API over
paid Anthropic (~$0.35-19/month depending on model) and a local model (8 GB M2 too small for good
ones). Provider-agnostic client for any OpenAI-compatible endpoint (Gemini free tier recommended;
Groq preset too), so switching — including to a paid provider later — is a config change.
"Explain today" (saved once per trading day) and "Ask". I2 enforced in code, not just the prompt:
every number in an answer must match the computed data it was given (display rounding allowed),
else one retry, then the answer is withheld. Guard bugs caught while building: the "30" in "15:30"
could vouch for an invented ₹3,000 (x100 reading now fractions-only), and 3-decimal values like
0.452 failed their own check. Free-tier caveat, shown in the UI: questions and market figures sent
to the provider may be used to improve its models. Verified live on 2026-09-21 (see above).

**Phase 11 done — historical similarity (2026-09-18):** kept to the plan's "3-5 features, hard
stop": 20-day return, distance from EMA50, RSI(14), 20-day realised vol, distance below the 52-week
high; 20 nearest past days, spaced ≥5 days apart, each old enough that its outcome was known.
Outcomes always shown beside the all-days base rate, plus ATM call/put ₹/lot on analog days since
2018. Tested walk-forward (410 non-overlapping points since 2010): rank correlation 0.001, t 0.03,
51% direction hit rate — no predictive value, so the card leads with "context, not a forecast".
Instructive on day one: today's analogs look bullish (70% higher after 5 days vs 56% base; ATM
call +₹4,802/lot) — exactly the kind of read the walk-forward test shows is noise.

**Phase 10 done — live trigger tracking (2026-09-18):** during market hours the dashboard builds
today's candle from completed 15-minute bars and runs every pattern on it: which would form if the
day closed now, and how many points the rest are from their trigger. Provisional until 15:30;
changes only on a 15-minute close. Before it: the recommendation now comes from option verdicts
with a Bonferroni bar (t ≥ ~2.8 across patterns judged), stale EMA-Pullback cards/endpoints were
removed, and a weekday 19:30 LaunchAgent records the forward log and tops up all archives.
Found along the way: a cache deadlock (one global lock held while computing; nested cached calls
hung the recommendation) — now per-key locks; and "could form" levels were only accurate to the
0.25% grid (~58 pts) — edges now bisected to ~1 pt, verified against the real prior-day high/low.

**Option choice switched to ₹ per lot (2026-09-18):** choosing each pattern's option by average
% return favoured ₹20-50 far-OTM weeklies — huge percentages, little money. Now chosen and judged
by rupee profit per lot. Picks moved to ITM options; Supertrend Flip (bull), the % leader, is
REJECTED in rupees. Also fixed a cross-process race in the hypothesis log (API server and a
research script both rewriting it) by moving to append-only JSON Lines under an OS file lock.

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
