# Design — how this dashboard looks, and why

The reference for anything visual. `ARCHITECTURE.md` says how the system is built;
this says how it is *shown*, and it is as much about honesty as about taste: a
dashboard for a system whose answer is usually "no" has to make "no" readable and
make uncertainty visible, or the design quietly lies.

Read this before adding a card, a chart or a colour.

---

## 1. The five rules

1. **Never show a number the code did not compute.** Not a placeholder, not a
   rounded version of one, not a browser-side calculation. If a figure is missing,
   the card says so (`<Offline what="…" />`). Rounding a confidence interval for
   the copilot once broke audit 12.2 — that check exists for this.
2. **Show the uncertainty next to the number.** An average with 13 trades behind
   it gets its 95% range; a verdict gets its t against its bar. The range bars in
   `PatternTable` exist because "every interval touches ₹0" is the finding.
3. **Say each caveat once.** The old Today tab repeated the same sentence on 26
   cards. A caveat belongs in the section footnote or behind a click, not on
   every row.
4. **Weight by importance, not by habit.** One card per idea, not one card per
   number. Border, fill, radius and shadow each say "separate thing" — spend them
   on the one thing that matters on the screen. Exactly one thing per screen may
   be loud: a raised panel, a coloured column, or a single chart. Everything else
   is held by alignment.
5. **A stale number is worse than a missing one.** Everything carries an "as of".
   Live things say they are live and when they last ticked; end-of-day things say
   which close they are from, and every clock says IST. A card showing sourced
   literature rather than measurements says so instead of carrying a date.

---

## 2. Tokens

### Colour

Dark only — this is a trading dashboard used at 15:30 and at 19:30, and the theme
is committed to rather than half-supported.

| Role | Token | Used for |
|---|---|---|
| Ground | `bg-zinc-950` | the page |
| Surface | `bg-zinc-900/40`, `bg-zinc-950/60` | panels, and rows inside panels |
| Raised | `bg-zinc-900/80` + `shadow-lg` | the one card that matters on a screen |
| Line | `border-zinc-800/80`, `border-zinc-800/60` | panel edges, table rules |
| Ink | `text-zinc-100` | headline values |
| Ink 2 | `text-zinc-300` / `text-zinc-400` | body |
| Muted | `text-zinc-500` / `text-zinc-600` | labels, footnotes, "as of" |
| Accent | `indigo-400/500` | interaction only: focus rings, links, the active tab |
| Good | `emerald-300/400` | profit, "live", a passing verdict |
| Bad | `rose-300/400` | loss, a failing verdict |
| Warning | `amber-200/300/400` | NO TRADE, "not counted", "not paired" |

**Semantic colour is reserved.** Emerald means money made or a rule passed; rose
means money lost or a rule failed; amber means "read this before acting". None of
them is ever decoration, and indigo is never used for a value.

**Charts get their colours from the same set**, and a categorical pair must pass
the colour-blind check before use (the `dataviz` skill's validator). The pair in
use — emerald `#34d399` against rose `#fb7185`, with zinc `#a1a1aa` for "could be
either" — was checked that way.

### Type

`Geist` for text, `Geist Mono` for every number (`app/layout.tsx`).

| Role | Classes |
|---|---|
| Page value (the index price) | `font-mono text-2xl font-semibold tabular-nums` |
| Card headline | `text-xl font-semibold tracking-tight` |
| Section label | `text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500` |
| Body | `text-sm leading-relaxed text-zinc-300` |
| Detail / footnote | `text-[11px] leading-relaxed text-zinc-500` |
| Any figure | `font-mono tabular-nums` — always, so columns line up |

### Spacing and shape

- Page: `max-w-7xl`, `px-4 sm:px-8`, sections `gap-6`/`gap-7`.
- Panels: `rounded-xl`, inner rows `rounded-lg`, padding `p-4` (`p-3` for rows).
- Grids: `lg:grid-cols-12` for the hero row (7 + 5), `lg:grid-cols-2` for pairs,
  `sm:grid-cols-4` for stat rows. Everything stacks at phone width.

---

## 3. The pieces

Shared primitives live in `components/ui.tsx`; use them rather than restyling.

| Component | For |
|---|---|
| `Panel` (`plain` / `raised` / `accent`) | any card. `raised` at most once per screen |
| `Pill` (`good`/`bad`/`warn`/`info`/`neutral`) | a verdict, a state, a label on a row |
| `Stat` | label + value + sub, the unit of a stat row |
| `SectionLabel` | the small caps heading, with an optional `hint` on the right — the hint is where "as of" and method notes go |
| `Offline` | what a card shows when the figure is not available |
| `PatternTable` | many rows of the same shape: one row per idea, click to expand |
| `RangeBar` (in `PatternTable`) | a 95% interval on a scale shared by every row, with ₹0 marked |
| `TodayChart` | the Today tab's chart, answering "what close would change the call". Interactive: 5m / 15m / 1H / 4H / 1D (remembered per browser; 1H is NSE's hourly blocks from 09:15, the last 15:15–15:30), drag or swipe to scroll back with a "Latest →" to return, pinch or −/+ to zoom, an indigo crosshair reading the price under the pointer, and EMA and band layers that switch off. Default view: 4-hour candles (NSE's 09:15–13:15 and 13:15–15:30 blocks) with the EMAs of those closes, labelled "(4h)" because they are not the grid's daily EMAs, the previous high/low, the price now on the axis, a "next close" column of amber bands where a pattern with an APPROVED option verdict would form (none while all 26 are rejected; the note says so), a strip of the days each formed, and a crosshair readout. Drawn at the box's real width (30 candles on a phone, 60 on a desk), never a wide SVG scrolling sideways The breakout card's nearest resistance (amber) and support (sky) cross today as dashed lines with their names; they move when NIFTY crosses a level. |
| `IndicatorGrid` | the eight readings under Today's call, filling the space beside the chart: four to a row when the card itself is 42rem or wider (a container query, not the window), two otherwise. Each tile is a name, a figure, the state in plain words ("between 30 and 70", "IV above realised") and one line of context; no green or red dots, because none of these is money made or a rule passed. The header says which candle they include; a tile from another moment (the VIX, the option chain) carries its own time. In a session it refreshes every minute and wears the amber "provisional" pill. Every tile is a button: hovering it (or tapping, or Enter) opens a panel with what the indicator is, why it is read, how it reacts to the market, what it means for a buyer, today's reading in words, and what followed closes in today's bucket since 2015 at a move size the reader picks, beside all days; a click pins it until Escape, ✕ or a click elsewhere |
| `IndicesCard` | the Market tab's first card: NIFTY, Bank Nifty, Sensex and GIFT Nifty, one row each with the change, a marker for where the price sits in the day's range, and its own time (a row minutes behind the others wears an amber "behind" pill). Below them, the commentary lines exactly as the API wrote them. Changes are zinc with a sign, not emerald and rose: an index rising is not money made to a put buyer. Updates from the shared live tick, never a timer of its own |
| `CourseResearchCard` | the Research tab's "Your course strategies": one row per strategy with each period on its own line (per-trade option return against no signal, trades, t, index points), the judged period in brighter ink, and the verdict pill (rose is a rule failed). The footnote says the option returns are modelled and why the breakout pair is judged on 2015-17 |
| `NiftyPipelineCard` | the Research tab's "Strategies searched for NIFTY": first a small table of what one point of NIFTY exposure costs a buyer a session (nearest vs monthly expiry, at the money, held 1/3/5 days, with and without the assumed slippage), then one row per pre-registered rule laid out as `CourseResearchCard`, with the rule itself behind "the rule". The footnote says which returns are real closes and which are modelled |
| `IntradayCard` | the Today tab's "Intraday rules", under "Live — during the session": one block per rule with its side (CE/PE in emerald/rose, as everywhere a side is named), a state pill (waiting, triggered, done, no trigger), the verdict pill, the API's sentence, the levels it acts on, the contract with its price now from the shared tick, the modelled 2024-26 record and the record at real prices. Out of session it shows the last session, dated. No timer of its own |
| `WeekdayCard` | the Today tab's "How Thursdays move": every session of this weekday since January 2015, each in % of its own open, shown as points at today's level — four stats (typical range, how often it went up first and when the first swing ends, the first swing and swing back each way), an hour-by-hour table of the typical level with the middle half of days beside today's, today's swings, the past same-weekday sessions most like today so far with what each did after (both outcomes, "not a forecast"), the measured why lines, and the intraday rules that tried to catch the move with their verdicts. No timer; refreshed with the page |
| `OptionMovesCard` | the Today tab's "What a move does to option prices", under the weekday card: 8 strikes either side of the money for the nearest expiry that does not expire today, the call's and the put's premium change if NIFTY moves up or down by 25 / 50 / 100 / 200 points (buttons pick the size, and a second row when: instantly or by a session's close, so the decay is in the figure; a \"no move\" column from `md`, and a one-line waiting cost at the money on a phone; in a session a \"Live now\" button shows each contract repriced at the index now from the shared tick, labelled as following the index, not leading it; every figure is the API's), emerald for a gain and rose for a loss, the ATM row indigo-tinted; from `sm` the price now and the measured premium per index point beside each. Columns fall away on a phone, never a sideways page scroll |
| `DayForecastCard` | the Today tab's "The next session", under the call and chart: the next session's expected move, the 68% and 95% close bands and the expected range as four tiles (event and expiry pills when they apply, and when it was written), the lean in its own colour with its base rate and its 2024–26 record beside it, then how past forecasts turned out — each with an in-band / outside pill, the lean right or wrong, and the reasons for a miss — and the method's check on 2024–26 |
| `KronosCard` | the Today tab's "Kronos (AI model)", under the next-session card: the live next-hour forecast (a small indigo band chart: 95% and 68% shaded, the median line, the last close dashed) while the market is open; Kronos's next-session median and bands beside ours; a scoreboard — forward next-session, ours on the same sessions, forward next-hour, and the 2024–26 past checks, the Kronos one flagged as possibly inside its training data — with band coverage, direction and typical miss; then recent outcomes with in-band and direction pills |
| `JournalTab` | the Journal tab: the form (the verdict is looked up, never typed; the expiry cannot precede the session, and quantity is in units with the index's lot size beside it), the tiles (followed and overrode count decisions, so staying out on a no-trade day shows as ₹0, and a group with none shows a dash), and each entry. An open trade carries its position panel: price now (Kite on the shared tick, else its last close, labelled), what selling now nets after costs, days to expiry, time decay a day if the index holds, the result at expiry if it stays put, and the breakeven, then the API's own sentences. The user's stop and target sit under it; the one amber line, "Consider exiting…", appears only when the price reaches one of them. The sale date is limited to the session through expiry, and a contract past expiry gets "Held to expiry", settled at the index close. Money made emerald, money lost rose |
| `OptionChainCard` | the Today tab's option chain, and since 2026-09-29 its only open-interest view: the old separate card's summary (put/call ratio, heaviest put and call strikes, contracts opened today) is the stat row at the top for whichever expiry is picked, and its bars sit behind the OI figures, growing away from the strike column, the two heaviest brightest. Every expiry NSE lists in a picker, every strike in a table that scrolls inside its own box and opens at the money ("Back to the money" returns there), calls left and puts right as on NSE and Kite. In-the-money cells are zinc-shaded, a bright rule marks where NIFTY sits, and the picked contract is indigo. Picking a price opens the buyer's view — one lot at the ask, charges both ways at the backtests' rate card, the real spread, the breakeven at expiry — all computed by `options/chain_table.py`. Columns fall away with width: OI and price on a phone, with the day's change under the price until the Chg column appears; IV from `sm`, change, volume and OI change from `lg`, bid/ask from `xl` |
| `EquityCurve` (in `PaperCard`) | what the paper book's trades have made over time, against a dashed line at ₹0 — deposits and withdrawals do not move it |
| `BreakoutLevelsCard` | the Today tab's breakout levels, under Intraday rules, built for one decision: enter on a break or not. On top, an entry check for the nearest level above (resistance, call side) and below (support, put side): the at-the-money option's ask now, the NIFTY move it needs to get the money back within the window picked (15, 30 or 60 minutes; both legs' charges and the spread, as in Before you buy), how often a break of that level travelled that far in that time since 2015 beside random lines, and one verdict in words ("No edge: same as a random line"; "Better than a random line, beyond chance" only past |z| 3). Below, every level highest first in one line each (name, price, distance, "crossed ↑ 14:20"), levels at one price merged, the two key ones marked R and S, NIFTY between them; the day's floor pivots (P, R1, R2, S1, S2) among them. The full record (any move size, time, sessions like today, both directions, today's breaks with the option's ask) sits behind "Show the history". Up and down are zinc, never emerald and rose |
| `PrecheckCard` | the Journal tab's "Before you buy": call or put, expiry, strike, lots, an optional price (the ask otherwise) and when the reader plans to sell, from 15 minutes to expiry. It answers with four figures (the NIFTY move that gets the money back by then, the result if NIFTY does not move, charges both ways, selling straight away) and the checks as sentences, each naming its threshold; one that crosses it carries an amber "marked" and a left rule, never a red light or a verdict. "Fill the journal with this" fills the form below and saves nothing. The option chain's buyer view links here with `?tab=journal&check=CE:22800:13-Oct-2026` |
| `FreshnessStrip` | one line under the header from the watchdog's freshness check (`briefing/freshness.py`, every ten minutes): "All N sources current", or in amber which cards are behind and why, sources not answering, and a service running older code than is on disk. A card behind also wears an amber "behind" pill beside its section label (`SectionLabel behind=`), its reason on hover. `AutoRefresh` reloads a tab whose refreshes stop changing the page's render stamp. Under it, `SystemHealth`: "All system checks passing" with the time and whether alerts reach the phone, or a banner with the open incidents (amber, rose only for critical, the word saying which) that opens to each one's repairs and their results. |
| `LiveTicker`, `AutoRefresh` | keeping the page current; nothing else polls |

### Tables over cards

A list of more than about six similar things is a table, not a stack of cards.
One row per thing, the numbers in aligned mono columns, and the detail behind a
click. This took the Today tab from 4,344px to 2,640px and made the finding
visible instead of repeated.

---

## 4. Numbers, dates, money

- **Rupees:** `₹` + `toLocaleString("en-IN")` — so ₹1,00,000, not ₹100,000.
- **A profit carries its sign** (`+₹8,267` / `−₹1,232`); **a balance does not**
  (`₹50,000`). Two helpers, `rs()` and `money()`, exist for exactly this.
- **Percentages:** one decimal for returns, two for the index change.
- **Minus is `−` (U+2212)**, not a hyphen, in any displayed figure.
- **Dates** are ISO (`2026-09-23`) in tables and "as of" hints; times are IST and
  say so.
- **Every figure is `tabular-nums`.** Numbers that jiggle as they tick look broken.

---

## 5. Charts

- One shared scale per chart, and a zero line whenever the sign matters.
- No dual axes. Ever. Two measures of different scale are two charts.
- Colour by meaning (profit/loss/uncertain), never by rank or by series index.
- Label the ends of the scale once, under the chart, not on every mark.
- Thin marks: 2–3px lines, 4px dots, a 1px zero rule in `zinc-700`.
- Everything gets `role="img"` and an `aria-label` that states the finding, plus
  a `<title>` for the hover.
- Draw in inline SVG with a `viewBox`; no chart library has been needed yet.

---

## 6. Copy

The writing is part of the design, and the rules mirror the copilot's:

- Plain English, short sentences, no jargon that the card does not explain.
- **Name what a number means**, not what it is called: "could as easily have been
  anywhere from −₹10,770 to +₹26,960" beats "95% CI".
- **Never advise.** "Consider" is as far as the recommendation goes, and the paper
  book's own rows say "no proven edge" where that is true.
- Buttons say what will happen (`Add to journal`, `Set funds`, `Close trade`).
- An error says what went wrong and what to do: "Pair this device: open the
  dashboard on the Mac and scan the code." When the way to fix something
  changes, the error text changes with it — `Offline` told people to start a dev
  server for a month after the app became a service.
- British-style plain wording, sentence case everywhere except the small-caps
  section labels.

---

## 7. Accessibility and interaction

- Focus is always visible: `focus-visible:ring-2 focus-visible:ring-indigo-500/60`.
- Every control is a real `<button>`, `<a>`, `<input>` or `<label>` with an `id`.
- Hit targets ≥ 32px high; rows that expand are buttons spanning the row.
- Colour is never the only signal — a pill's word carries it too.
- Charts carry `aria-label`; icons carry `title`.
- Respect `prefers-reduced-motion`; the only animation is the "live" pulse.
- Which tab is open belongs in the URL (`?tab=research`). A view you cannot
  link to, or that a reload throws away, is a view you cannot send to yourself.
- A tab bar claims the ARIA tabs pattern, so it owes the behaviour: arrow keys
  move between tabs, Home and End jump, and only the selected tab is tabbable.

---

## 8. Phone

The dashboard is usable at 375px and is reached from a paired phone
(`install_app_services.sh --lan`).

- Single column below `lg`; stat rows go 4 → 2; tables hide the least important
  columns (`hidden sm:table-cell`, `hidden lg:table-cell`) rather than scrolling
  horizontally.
- 16px side gutters minimum, and the page never scrolls sideways — only a table
  or a chart may, inside its own `overflow-x-auto`. **A grid or flex child is
  `min-width: auto` by default**, so give every column `min-w-0` or one wide
  chart stretches the whole page instead of scrolling inside its own box.
- The header stays sticky; the tab bar sits at the bottom below `sm`, where the
  thumb is, and in the flow above it.

---

## 9. The tabs, and adding a card

**Today** is what would change your next action. **Research** is what the record
says, newest evidence first. **Market** is how this market works. **Journal** is
what you did and what the paper book did. A card that does not answer its tab's
question belongs in another tab, however good the card is — "Days like this one"
sat on Today for weeks while its own verdict was "no demonstrated predictive
value", which is a research finding, not something to act on this session.

1. What single question does it answer? If you cannot write it in one line, it is
   two cards.
2. Which tab? See above, and be strict about it.
3. Use `SectionLabel` + `Panel`. Put the method note in the label's `hint`.
4. Numbers from the API only, `font-mono tabular-nums`, `rs()`/`money()` for
   rupees, and the uncertainty beside the figure.
5. Missing data → `Offline`, never a zero or a dash pretending to be a value.
6. Check it at 375px, and check the focus ring on every control.
7. If it polls, it polls through `AutoRefresh`/`LiveTicker` — not its own timer.

---

## 10. Anti-patterns, all of them seen in this project

- **26 identical cards** where one table belonged.
- **The same caveat on every row** instead of once in the footnote.
- **A single narrow column at 1400px** with half the screen empty.
- **A page that never updates** — server-rendered once and frozen at page load.
- **A rounded number** handed to the copilot that no computed source contained.
- **An interval hidden in prose** when a bar would show it at a glance.
- **"+₹1,00,000" for a balance** — the sign belongs to profit, not to money.
- **A statistic computed in the browser.** The replication table subtracted two
  returned numbers to show each index's edge, coloured it and sorted by it. If it
  is a number someone could quote, Python computes it.
- **A minus sign that is a hyphen.** `toFixed()` emits `-3.68`; the primitive
  that formats percentages has to fix it once for every card.
- **An error that names a command which no longer exists.**
- **A wide chart with no `min-w-0` on its column**, which scrolls the whole page
  sideways on a phone rather than itself.
- **Three timers polling one endpoint.** One poller, many subscribers.
