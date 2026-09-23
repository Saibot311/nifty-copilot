# Design audit — 2026-09-23

Read against `DESIGN.md`. No code was changed to produce this. Heights are
measured, not estimated: rendered at 1440×900 against the running service,
`offsetHeight` per section.

**Totals as built:** Today **2,901px** · Research **5,504px** · Market **2,559px**
· Journal **1,199px**.

---

## A. Inventory

### Today — 2,901px

| Card | File | The one question it answers | Panel | Height |
|---|---|---|---|---|
| Live — during the session | `LivePatternsCard` | What would form if the market closed right now? | accent | 471 |
| Today's call | `RecommendationCard` | Is there a trade with proven evidence today? | **raised** | 552 |
| Price | `PriceChart` + `IndicatorGrid` | Where is price, against its own recent range? | plain | 552 |
| Copilot | `CopilotCard` | Can I ask about any of this in words? | plain | 187 |
| Patterns in play | `PatternTable` | Which patterns formed or could form, and what is their record? | plain | 348 |
| Forward track record | `ForwardLogCard` | What has the system said before the outcome was known? | plain | 496 |
| Implied volatility | `IVCard` | What do options cost now against the past year? | plain | 496 |
| Research briefing | `BriefingCard` | What does the rule-based evidence say for and against today? | **raised** | 711 |
| Similar past days | `SimilarityCard` | What followed days that looked like this one? | plain | 711 |

**Two-line questions (i.e. two cards):**
- *Price* answers "where is price" **and** "what do the indicators read" — the
  chart and `IndicatorGrid` are stacked in one section with one label.
- *Research briefing* answers "what is the evidence" **and** "what would confirm
  or invalidate it" — four sub-headings inside one card, 711px.

### Research — 5,504px

| Card | File | Question | Panel | Height |
|---|---|---|---|---|
| Every pattern, and the option it points to | `PatternTable` | Which patterns have any record, and how uncertain is it? | plain | 1,640 |
| Replicated on other indices | `ReplicationCard` | Does any pattern survive on BANKNIFTY, Sensex, Midcap? | plain | 1,142 |
| Strategy Playbook | `PlaybookCard` | What verdict did each strategy get on index returns? | plain | **2,666** |
| Strategy comparison | `ResearchCompare` | How does each strategy compare with buy-and-hold? | plain | **2,666** |

### Market — 2,559px

| Card | File | Question | Panel | Height |
|---|---|---|---|---|
| GIFT Nifty now | `GiftNiftyCard` | What are NIFTY futures doing while India is shut? | plain | 358 |
| Why it moved | `WhyItMovedCard` | How much of today's move do global cues explain? | plain | 358 |
| Who is on the other side | `WhoWinsCard` | Who makes money in this market, and who pays? | plain | 494 |
| Expiry days and unusual activity | `ExpiryCard` | Do expiry days show manipulation footprints? | plain | 399 |
| Beyond chart patterns | `StructuralCard` | Did any structural idea beat no signal? | plain | 427 |
| What the research says | `KnowledgeCard` | What does the literature say, with sources? | plain | 776 |

### Journal — 1,199px

| Card | File | Question | Panel | Height |
|---|---|---|---|---|
| Your trade journal | `JournalTab` form | What did I decide this session? | plain | 247 |
| How it's going | `JournalTab` stats | Am I better off following the system or overriding it? | plain | 177 |
| Entries | `JournalTab` list | What have I logged? | plain | 193 |
| Paper observation | `PaperCard` | What are the policies doing with real premiums? | plain | 500 |

---

## B. Violations

### §1.1 — a number the API did not compute

1. **`ReplicationCard`, per-index "edge" column** (lines 49–54). The browser
   computes `holdout.avg_return_pct − baseline_holdout_avg_pct`, displays it,
   colours it by sign, **and sorts the table by it**. This is a new statistic
   made in the client. The API returns both halves but not the difference.
   *Fix needs the API:* `/api/replication` should return `edge_pct` per index
   (and the pooled sort key). Until it does, the column is `Offline`.
2. **`PaperCard`**, `rs(-account.below_high_water_rs)` — a sign flip for display
   only. Minor, but it is arithmetic on a figure before showing it; better as a
   returned signed value.

*Not violations:* `RangeBar`, `EquityCurve`, `IVCard`, `PriceChart` scale maths —
chart geometry is explicitly allowed. Sorting by a returned field is fine.

### §1.2 — a figure without its uncertainty

3. **`StructuralCard`** rows show `−₹3,577/lot vs −₹131` on the face; the 95%
   range exists but only after expanding the row.
4. **`PaperCard`** tiles show totals (`₹0`, `0 closed`) with the "needs ~15
   closed trades" caveat 300px lower, at the bottom of the card.
5. **`ForwardLogCard`** shows "Avg 10d return" as a stat with no interval and no
   n beside it — on two usable rows.

### §1.3 — the same caveat per row instead of once

6. **`PlaybookCard`** stamps `checked <datetime>` on all 26 rows. One "as of"
   above the table would do.
7. **`StructuralCard`** repeats "with this few trades the average could have
   been…" inside every expanded row.

### §1.4 — weight spent where there is no separate idea

8. **Today carries three loud surfaces**: `RecommendationCard` (raised),
   `BriefingCard` (raised) and `LivePatternsCard` (accent). The rule is one.
   The briefing is supporting evidence; it should be plain.
9. **`PlaybookCard`** gives 26 rows a radius and a fill each — 26 objects where
   there is one table.

### §1.5 — no "as of"

Measured from the rendered DOM: sections containing no `YYYY-MM-DD` anywhere.

10. **Copilot** — no date at all; the saved explanation is per trading day.
11. **Beyond chart patterns** (`StructuralCard`) — no date; it is a nightly run.
12. **How it's going** and **Your trade journal** (Journal) — no "as of".
13. **Strategy Playbook** — per-row timestamps but no section date.
14. **Live — during the session** — shows `15:30` with **no IST** on the face.
15. **`LiveTicker`** clock shows `13:04:34` with IST only in the `title`.

*Proposed exemption:* `KnowledgeCard` is sourced literature, not time-varying.
DESIGN.md should say that explicitly rather than leaving it a silent breach.

### §3 — more than ~6 similar items as cards

16. **`PlaybookCard`: 26 stacked cards, 2,666px.** This is §10's first
    anti-pattern by name, still in the codebase, and the single biggest
    offender on the site.
17. **`KnowledgeCard`**: 13 `<details>` rows, 776px. Borderline — a list, not
    cards — but it is the second tallest thing on Market.

### §4 — numbers, dates, money

18. **`fmtPct` in `ui.tsx` emits a hyphen-minus.** `v.toFixed()` produces `-3.68`,
    not `−3.68`. Used by the briefing, forward log, similarity and pattern cards
    — so most negative percentages on the site violate §4. One-line fix in the
    primitive.
19. **`PlaybookCard`** renders `new Date(checked_at).toLocaleString("en-IN")` —
    non-ISO (`23/9/2026, 5:12:56 pm`), against §4's ISO rule.
20. **`LiveTicker`** and **`LivePatternsCard`** show times without IST on the face.

### §5 — chart integrity

21. **`PriceChart` has no `role="img"` and no `aria-label`** — the one chart on
    Today that a screen reader cannot read. (`IVCard`, `RangeBar` and
    `EquityCurve` all comply, and `IVCard`'s label states the finding.)

*Clean:* no dual axes anywhere; no colour by rank or index; zero lines present
where sign matters.

### §6 — copy

22. **`Offline` tells the user to run a dev command** (`uvicorn main:app
    --reload`). Since Phase 15 the app runs as a service; the correct next
    action is `./scripts/install_app_services.sh --status`. An error with the
    wrong next action is worse than none.

### §7 — accessibility

23. **`CopilotCard`** (both buttons) and **`PaperCard`** ("Set funds") have no
    `focus-visible` ring.
24. **`DashboardTabs`** implements `role="tablist"`/`tab`/`tabpanel` but **no
    arrow-key navigation and no roving `tabindex`** — the ARIA pattern it claims.
25. **`PatternTable` signals CE/PE with a coloured dot alone** — colour as the
    only signal. The old cards said CALL/PUT in words.
26. `JournalTab` inputs show focus as a border-colour change only; thinner than
    the ring used elsewhere, and inconsistent with it.

### §8 — phone

27. **Seven tables/charts carry a `min-w` and side-scroll instead of hiding
    low-priority columns**: `ReplicationCard` 640px, `PaperCard` 560,
    `ExpiryCard` 560, `PriceChart` svg 560, `ForwardLogCard` 480, `WhoWinsCard`
    480, `SimilarityCard` 420 ×2. §8 asks for hidden columns, as `PatternTable`
    already does.
28. **Unverified:** this pane reports the layout viewport inconsistently
    (`innerWidth` 602 vs `clientWidth` 375), so I could not confirm whether the
    *page* scrolls sideways at 375. It must be checked on a real phone before
    anyone calls it fixed.

### §10 — named anti-patterns still present

- "**26 identical cards where one table belonged**" — `PlaybookCard`.
- "**A caveat on every row**" — `PlaybookCard` timestamps, `StructuralCard` range
  sentence.

### Polling outside `AutoRefresh`/`LiveTicker`

29. **`PaperCard`** runs its own 3s/60s `setTimeout` loop; **`LivePatternsCard`**
    runs its own `setInterval`. Three independent clocks now poll the same API.

---

## C. Navigation

### Is each tab holding what it should?

`DESIGN.md §9` defines: Today = what now; Research = what the record says;
Market = how this market works; Journal = what you did and the paper book.

- **Misfiled: `SimilarityCard` ("Similar past days", 711px) on Today.** Its own
  verdict is "no demonstrated predictive value". It is a research finding about a
  method, not something to act on this session. → Research.
- **Misfiled by relevance: `PlaybookCard` and `ResearchCompare`, 4,332px of
  Research (79% of the tab).** Both judge *index-return* strategies — the
  question the project abandoned when it moved to pattern→option research. They
  are history, and they currently dominate the tab that should lead with the
  option record. → keep, but demote below the option work and collapse by default.
- **`BriefingCard` on Today is right** but is two cards (evidence / what would
  change it).

### Ordering

Today is currently ordered by when each card was written: live tracking (Phase
10) first because it was added first, the briefing near the bottom despite being
raised. Proposed order, decided by **"what would change my next action, soonest"**:

1. **Today's call** — the decision, and the only thing on the page that is one.
2. **Live / Price** — what is happening right now, beside it.
3. **Patterns in play** — what could change the call at the next close.
4. **Copilot** — ask about any of the above.
5. **Context row** (forward record · implied volatility · briefing) — quieter.

Research, decided by **"how much unseen data stands behind it"**: option record
→ replication → (collapsed) index-return history. Market and Journal are already
in a defensible order.

### Cold in five seconds?

Today and Journal, yes. Research and Market, no — "Strategy Playbook" and
"Strategy comparison" name the artefact, not the question, and sit next to each
other with near-identical labels. Proposed labels and hints:

| Now | Proposed label | Hint |
|---|---|---|
| Every pattern, and the option it points to | **What each pattern's option actually made** | 2024–26, data the choice never saw |
| Replicated on other indices | **The same rules on four indices** | a shared date counts once |
| Strategy Playbook | **Older work: index-return verdicts** | superseded by the option record above |
| Strategy comparison | **Older work: vs buy-and-hold** | same costs, same hold, every strategy |
| Beyond chart patterns: six structural tests | **Ideas that are not chart shapes** | pre-registered, one look each |
| What the research says | **What the literature says** | 13 principles, each with its source |

### Header, thumb reach, keyboard, deep state

- **Sticky header** works and stays legible; the live price is in it, which is
  right.
- **Thumb reach:** the tab bar is pinned to the top on phone — the furthest point
  from the thumb. It should move to the bottom below `sm`.
- **Keyboard:** tabs are not arrow-navigable (§7.24). `PatternTable` rows are
  real buttons and tab through correctly — the good case to copy.
- **Deep state is lost.** Active tab and expanded row are component state only:
  a reload lands on Today, and no view is linkable. `?tab=research` (and
  optionally `#pattern=bollinger_reversion`) would fix both, and would also let
  the phone open straight to the Journal.

---

## D. Fix list, in order

Honesty first, then density and navigation, then polish.

| # | Fix | Rule | Height saved |
|---|---|---|---|
| 1 | `fmtPct` minus sign → U+2212 | §4.18 | 0 |
| 2 | `ReplicationCard` edge column → `Offline` until the API returns it (+ name the field) | §1.1.1 | 0 |
| 3 | Uncertainty onto the face of Structural / Paper / Forward-log figures | §1.2 | +40 |
| 4 | "As of" on Copilot, Structural, Journal, Playbook; IST on every clock | §1.5, §4.20 | +20 |
| 5 | `Offline` copy → the service command | §6.22 | 0 |
| 6 | **`PlaybookCard` → table**, one "as of" above it | §3.16, §1.3.6, §10 | **−2,000** |
| 7 | Phone: hide low-priority columns instead of `min-w` scrolling (7 tables) | §8.27 | −150 |
| 8 | `KnowledgeCard` → compact list | §3.17 | −300 |
| 9 | Today: one loud surface — briefing to plain; reorder per §C | §1.4.8 | −100 |
| 10 | Move `SimilarityCard` to Research; collapse the two legacy cards | §9 | −700 (Today) |
| 11 | Focus rings (Copilot, Paper), arrow-key tabs, CE/PE in words | §7.23–26 | 0 |
| 12 | `PriceChart` `role="img"` + a label that states the finding | §5.21 | 0 |
| 13 | One clock: `PaperCard` and `LivePatternsCard` through the shared poller | §9 checklist | 0 |
| 14 | `?tab=` in the URL; bottom tab bar on phone | navigation | 0 |

Research goes **5,504 → ~3,200px**; Today **2,901 → ~2,100px**; Market
**2,559 → ~2,200px**. Nothing above changes a computed number.

---

## E. Where the doc and the code disagree

1. **DESIGN.md §9 defines the tabs in a checklist item**, which is why two
   legacy cards drifted into Research unchallenged. Proposed §9 opener:
   > **Today** is what would change your next action. **Research** is what the
   > record says, newest evidence first. **Market** is how this market works.
   > **Journal** is what you did and what the paper book did. A card that does
   > not answer its tab's question belongs in another tab, however good it is.
2. **"One raised Panel per screen" (§1.4) will conflict with the direction
   brief's "one memorable element per screen."** Proposed amended wording:
   > Exactly one thing per screen may be loud — a raised panel, a coloured
   > column or a single chart. Everything else is held by alignment.
3. **§1.5 is silent on things that are not time-varying.** Proposed addition:
   > A card that shows sourced literature rather than measurements says so
   > instead of carrying an "as of".
4. **§5 says charts need `role="img"` and a label**; `PriceChart` predates it.
   The doc is right, the code is wrong — no amendment needed.
5. **§6 says an error must give a next action**, but does not say the action must
   still be true. Proposed addition:
   > When the way to fix something changes, the error text changes with it. A
   > stale instruction is worse than none.
6. **The doc does not mention client-side state.** Proposed §7 addition:
   > Which tab is open, and which row is expanded, belong in the URL. A view you
   > cannot link to or reload is a view you cannot share with yourself.

---

## Not recommended

- Touching `compute`/API to make any of the above easier, except the one named
  field in fix #2, which is a genuine gap: the client should not be inventing an
  edge figure.
- Any change to `PatternTable`. It is the one card that already follows every
  rule in this document, and it is the model for fixes #6 and #7.
