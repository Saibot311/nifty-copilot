# Design direction — the instrument

Proposed 2026-09-23, for approval before any rollout. This is the **aesthetic
layer only**: `DESIGN.md` §1, §4–§8 and §10 are frozen and nothing here touches
them. What changes is §2 (exact hues, type scale, spacing) and §3 (how a panel,
pill, stat and row look).

**The brief in one line:** a well-made measuring device — a bench instrument that
reads the market and mostly answers "no" — where the precision is the beauty and
nothing is decorative.

---

## The self-check first

The default result of "dark trading dashboard" is a near-black page, one bright
accent, and a grid of identical rounded cards. **That is what this codebase
already is**, and it is why the audit found 5,504px of Research reading as one
undifferentiated stack. So three things are deliberately *not* that:

1. **Most surfaces lose their box.** A card becomes a hairline rule and a column
   of aligned numbers. Borders are spent only where two measures genuinely
   separate. Fewer boxes, more alignment.
2. **The accent stops being decoration.** Indigo appears on focus and on the
   active tab, nowhere else. Nothing is "branded" a colour.
3. **One element per screen is allowed to be loud**, and it is always the
   finding, never the chrome.

If a screen ends up as evenly-weighted rounded cards again, the direction has
failed regardless of the palette.

---

## A. Palette

A graphite ramp, marginally cooler and darker than zinc, so the two semantic
hues sit on it like phosphor rather than like brand colours. Contrast is
measured against the ground (`#0A0C0D`); all text tokens clear WCAG AA for body
text, and the two money hues clear AAA for large text.

| Name | Hex | Job | Contrast |
|---|---|---|---|
| `ground` | `#0A0C0D` | the page. Darker than zinc-950 and slightly cooler | — |
| `surface` | `#101415` | a panel that still needs to be a panel | 1.06:1 on ground |
| `raised` | `#171D1E` | the one loud surface per screen | 1.15:1 |
| `line` | `#212829` | hairline between rows — the default separator | 1.31:1 |
| `line-hi` | `#303A3C` | a rule that means a real break (header/total) | 1.68:1 |
| `ink` | `#E8ECEC` | values you are meant to read | **16.5:1** |
| `ink-2` | `#A9B2B3` | prose | **9.1:1** |
| `muted` | `#6F7879` | labels, units, "as of" | **4.3:1** |
| `gain` | `#3ED9A4` | money made, a rule passed | **10.9:1** |
| `loss` | `#F8698F` | money lost, a rule failed | **6.9:1** |
| `caution` | `#E0B04A` | read this before acting (NO TRADE, "not counted") | **9.8:1** |
| `accent` | `#6EA8FA` | focus ring, active tab, links. **Never a value** | 8.1:1 |

**The colour-blind check, run not eyeballed.** `gain` vs `loss` scores ΔE 7.5
under deuteranopia (`validate_palette.js`), which is the 6–8 band: *legal only
with secondary encoding*. We have it — every value also carries a sign (`+`/`−`)
and most carry a word (`REJECTED`, `CALL`). It is a deliberate trade:

- The strongest pair tested was cyan `#37C8E0` vs rose (ΔE 12.9), but cyan for
  profit breaks the one convention every trader reads without thinking. Rejected.
- The current emerald/rose pair scores **ΔE 3.5** — worse than what is proposed.
  So this is an improvement to an existing, unstated problem, not a new one.
- Shifting `loss` from rose toward pink (`#F8698F`) buys most of the gain.

**What this replaces:** zinc → graphite is a small move (a few points cooler and
two steps darker at the ground). It matters because zinc-950 under emerald reads
as "default dark SaaS", and because a darker ground lets a hairline at `#212829`
be visible without being a box.

---

## B. Type

`Geist` and `Geist Mono` stay. Reason: Geist Mono's digits are genuinely good —
even width, unambiguous 0/O and 1/l — and the whole dashboard is digits. Nothing
would be gained by swapping for a display face; the instrument reads as an
instrument through *numerals and alignment*, not through personality.

| Step | Size / weight / tracking | Job |
|---|---|---|
| Readout | `28px / 600 / −0.02em`, mono, tabular | the live index price. One per screen |
| Finding | `19px / 600 / −0.01em`, sans | the sentence a card exists to say |
| Value | `13px / 500`, mono, tabular | every figure in a table |
| Body | `14px / 400 / 1.6`, sans | prose, max ~70 characters |
| Label | `11px / 500 / 0.04em`, sans, `muted` | column heads, field labels |
| Unit | `10px / 400`, mono, `muted` | `/lot`, `%`, `IST`, "as of" |

### The small-caps section label

**Replaced.** `text-[11px] uppercase tracking-[0.12em]` is the commonest
generated-UI tell, and it currently does two jobs badly: it names the section and
parks the "as of" hint at the far right, where the eye does not go.

The replacement is a **ruled header**: sentence-case name at Label size in `ink`,
the hint immediately after it in `muted` at Unit size, and a `line-hi` hairline
running from the end of the text to the right edge. The rule is not decoration —
it is the top boundary of the measure below it, and it stops where the data
starts. Two pieces of information stay, in reading order, and the tracked-out
caps go.

```
Every pattern's option  2024–26, data the choice never saw ─────────────────
```

---

## C. Structure as information

Every mark earns its place:

| Mark | Means |
|---|---|
| Hairline `line` between rows | one row, one thing measured |
| Hairline `line-hi` | a real break: header from body, body from total |
| A rule that stops early | the measure ends here; what follows is commentary |
| Tick on the RangeBar | ₹0 — the only threshold that matters on that scale |
| A gap (no rule) | a break in time or subject, not a separator |
| Right-aligned mono column | comparable quantities; the eye scans down |
| A box (border + fill) | genuinely separable object — used sparingly |

Deleted because they mean nothing: the border on every stat tile, the radius on
every list row, the shadow under panels that are not the loud one, and the
vertical rules between table columns that alignment already does.

**Instrument vernacular is allowed only over a real quantity.** A tick mark
appears where a threshold exists (₹0, the evidence bar t). No fake bezels, no
knurling, no "terminal" ASCII framing around things that are not measurements.

---

## D. The loud element, per screen

| Screen | The one loud thing | Why it earns it |
|---|---|---|
| **Today** | the readout — live index, its change, and the tick clock | it is the only thing that changes while you watch |
| **Research** | the **RangeBar column**: every 95% interval on one shared scale with ₹0 marked | that every interval touches zero *is* the finding |
| **Market** | the variance-risk-premium line: options priced above delivered on 71% of days | it is the answer to "who makes money" |
| **Journal** | the equity curve against the dashed line of what you put in | the only line on the site that moves with money |

Everything else on that screen is held by alignment and hairlines. This is the
amendment already made to `DESIGN.md` §1.4: one thing per screen may be loud.

---

## E. Density — the hierarchy of surfaces

Four levels, in descending order of weight, and most content lives at level 3:

1. **Boxed** (`surface` + `line` border + `rounded-lg`): the loud element, and
   forms that take input. At most two per screen.
2. **Filled, no border** (`surface`, no radius, full-bleed to the section edge):
   tables. The fill says "one measure"; the hairlines inside say "one row each".
3. **Ruled only** (no fill, `line` hairlines): stat rows, lists, most of Market.
4. **Aligned only** (nothing but a shared column edge): units, footnotes, hints.

Chrome shrinks: table rows go from `py-2.5` to `py-2`, panel padding from `p-4`
to `px-4 py-3`, and the gap between sections from 28px to 20px with the ruled
header doing the separating. **Estimated saving: a further 10–15% of height on
Research and Market**, with no data removed.

---

## F. Motion

- **One page-load sequence:** the readout counts from the previous close to the
  current price over 400ms, once, on first paint. Nothing else animates in.
- **Motion that answers a click:** a row expanding (160ms height), a tab
  changing (no transition — instant is honest).
- **Motion that reports:** the live price flashes its new value for 120ms in
  `gain`/`loss` when it ticks, and the "live" dot pulses. That is the whole list.
- No hover transitions on cards, no staggered section entrances, no skeleton
  shimmer — an empty state says what is missing instead.
- `prefers-reduced-motion` disables every item above, including the pulse.

---

## G. Wireframes

### Research — desktop (1440)

```
┌ NIFTY 50  23,446.8  +117.80 (+0.50%) ● LIVE 13:04 IST      VIX 10.29  Zerodha ✓ ┐
├ Today │ Research │ Market │ Journal ───────────────────────────────────────────┤

  What each pattern's option made   2024–26, data the choice never saw ───────────
   PATTERN                     TRADES   AVG/LOT      WHAT IT COULD REALLY BE   VERDICT
  ─────────────────────────────────────────────────────────────────────────────────
   CALL Bollinger Reversion        13   +₹8,267    ├──────●────────┤           REJECTED
        6.4×/yr                won 54%  no sig −₹6,163      │                        
   PUT  RSI Overbought Rev.        11     +₹915      ├───●─────┤   │           REJECTED
        2.3×/yr                won  9%  no sig −₹589        │                        
   …                                                        ₹0                       
  ─────────────────────────────────────────────────────────────────────────────────
   −₹14k                             ₹0                            +₹10k
   a range touching ₹0 means the edge could be nothing · click a row for detail

  The same rules on four indices   a date traded on several counts once ───────────
   IDEA                    POOLED vs NO SIGNAL   NIFTY  BANK  MID  SENSEX  VERDICT
  ─────────────────────────────────────────────────────────────────────────────────
   RSI Overbought Rev.     +24.3% vs −10.6%      +108%  +33%  +4%   +73%   REJECTED
                           could be −46.7 to +127.8
   …
  ▸ Older work — index-return verdicts, superseded above
```

### Research — 375

```
┌ NIFTY 50 23,446.8      ┐
│ +117.80 (+0.50%) ●LIVE │
├────────────────────────┤
 What each pattern's
 option made ────────────
 2024–26, unseen data

 CALL Bollinger Rev.
 13 trades      +₹8,267
 ├────────●────────┤
      ₹0
              REJECTED
 ────────────────────────
 PUT  RSI Overbought
 11 trades        +₹915
 ├───●────┤
      ₹0
              REJECTED
 ────────────────────────
 −₹14k    ₹0     +₹10k

 [ Today │ Research │ … ]  ← fixed, bottom
```

The range bar survives the phone because it *is* the finding; the t-statistic
and the date count are the columns that go.

### Today — desktop (1440)

```
┌ NIFTY 50  23,446.8  +117.80 (+0.50%) ● LIVE 13:04 IST ──────────────────────────┐
├ Today │ Research │ Market │ Journal ───────────────────────────────────────────┤

  ┌───────────────────────────────────────────┐  Price  20- and 50-day EMAs ──────
  │  NO TRADE                    TREND BEAR   │   ╭╮  ╷                      
  │  No pattern formed on the last close.     │  ╭╯╰─╮╷╰╮   ╭──╮             
  │                                           │ ─╯    ╰╯ ╰──╯  ╰─            
  │  None of the 26 formed on 2026-09-22.     │  2026-05-06 → 2026-09-22     
  │  Could form next: Prev-Day-Low Breakdown… │  ─────────────────────────────
  │  ▸ evidence bar: t ≥ 2.89, 19 judged      │  EMA20 23,626 · RSI 34.6 · ADX 30.7
  └───────────────────────────────────────────┘  ATR 187.6 · HV20 7.5%

  Live — during the session   provisional until 15:30 ───────────────────────────
   If today closed at 23,453 (+0.53%)    15-min close 13:00 IST
   CALL Prev-Day-High Breakout  +37 pts   REJECTED  …

  Patterns in play   from the close of 2026-09-22 (23,329) ───────────────────────
   …same table shape as Research, four rows…

  Copilot ───────────────────────────────────────────────────────────────────────
   [ Explain today in plain language ]   [ ask… ]
```

### Today — 375

```
 NIFTY 50 23,446.8
 +117.80 (+0.50%) ● LIVE
 ─────────────────────────
 NO TRADE      TREND BEAR
 No pattern formed on the
 last close.
 ▸ evidence bar
 ─────────────────────────
 Price ───────────────────
  ╭╮ ╷  ╭──╮
 ─╯╰─╯╰─╯  ╰──
 EMA20 23,626 · RSI 34.6
 ─────────────────────────
 Patterns in play ────────
 …
 [ Today │ Research │ … ]
```

---

## What I would build first, and stop

The **Research tab**, because the RangeBar column is the hardest case: it has to
be the loudest thing on the screen while staying a column in a dense table, and
it has to survive 375px. If the direction works there it works anywhere on this
site; if it does not, nothing else is worth converting.

The prototype is applied behind a `data-skin="instrument"` attribute on the
Research panel only, so Today, Market and Journal are untouched and the two can
be compared side by side before anything is rolled out.
