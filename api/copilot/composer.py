"""The daily explanation, written in Python instead of by a model.

Every guard in this package exists because a language model might invent
something. If the sentences are assembled here from the same context the
guards check against, invention is impossible by construction rather than
caught afterwards — I2 stops being an invariant we police and becomes one
the code cannot break.

What is lost is fluency and the ability to answer a question nobody
anticipated. The daily explanation asks the same question every day, so it
is the one place that trade is clearly worth making. Typed questions still
go to the model.

Nothing here decides anything. It reads the context and says what is in it,
including — especially — when what is in it is disappointing.

Run shadow against the model's version and graded by the same judge, so the
choice between them is made on the record rather than on taste.
"""

ACTIONS = {
    "NO_TRADE": "The system says no trade today.",
    "CONSIDER_CALL": "The system says a call is worth considering today.",
    "CONSIDER_PUT": "The system says a put is worth considering today.",
}
MAX_DETAILED = 2  # patterns described in full; the rest are named only

# Small counts read badly as numerals at the start of a sentence.
_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
          6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}


def _count(n: int, noun: str) -> str:
    return f"{_WORDS.get(n, str(n))} {noun}{'' if n == 1 else 's'}"


def _num(x) -> str:
    """23346.4 -> 23,346.4 — the same rendering the number guard accepts."""
    if x is None:
        return ""
    f = float(x)
    return f"{f:,.0f}" if f == int(f) else f"{f:,}"


def _rupees(x) -> str:
    return f"₹{_num(abs(float(x)))}"


def _record_sentence(name: str, rec: dict | None) -> str:
    if not rec:
        return f"{name} has no measured option record yet."
    profit, t, trades = rec.get("avg_profit_per_lot_rs"), rec.get("t_stat"), rec.get("trades_2024_26")
    verdict = rec.get("verdict")
    if profit is None or trades is None:
        return f"{name}'s option setup is marked {verdict}, with too few trades to measure."

    made = "made" if profit >= 0 else "lost"
    s = (f"{name}'s setup — {rec['option']} — {made} an average of {_rupees(profit)} per lot "
         f"over {trades} trades on 2024-2026 data")
    if t is not None:
        # The weakness is stated every time. A reader who skims must still
        # come away knowing this is not evidence of anything.
        s += (f", with a t-statistic of {_num(t)}"
              + (", which is well under 2 and so cannot be told apart from luck" if abs(float(t)) < 2 else ""))
    return s + f". The system marks it {verdict}."


def _formed(ctx: list) -> list[str]:
    if not ctx:
        return []
    names = [p["name"] for p in ctx]
    out = [f"{_count(len(names), 'pattern')} formed on the last close: " + ", ".join(names) + "."]
    out += [_record_sentence(p["name"], p.get("option_record")) for p in ctx[:MAX_DETAILED]]
    return out


def _could_form(ctx: list) -> list[str]:
    if not ctx:
        return ["No pattern is close enough to form on the next close."]
    p = ctx[0]
    out = []
    ranges = p.get("forms_on_close_between") or []
    if ranges and len(ranges[0]) == 2:
        lo, hi = ranges[0]
        out.append(f"{p['name']} would form on a close between {_num(lo)} and {_num(hi)}.")
    else:
        out.append(f"{p['name']} could form on the next close.")
    rec = p.get("option_record")
    if rec and rec.get("verdict"):
        out.append(f"Its option record is {rec['verdict']}.")
    if len(ctx) > 1:
        others = ", ".join(x["name"] for x in ctx[1:MAX_DETAILED + 1])
        out.append(f"Also close: {others}.")
    return out


def _analogs(sim: dict | None) -> list[str]:
    if not sim:
        return []
    test = sim.get("predictive_test") or {}
    count = sim.get("count")
    if not count:
        return []
    out = [f"The {count} most similar past days are context, not a forecast."]
    # The stored verdict is a full sentence with its own explanation after a
    # colon; only the verdict itself belongs mid-sentence.
    verdict = (test.get("verdict") or "").split(":")[0].strip().rstrip(".")
    if verdict:
        out.append(f"The system's own test of whether they predict anything returned {verdict.lower()}.")
    return out


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _iv(iv: dict | None) -> list[str]:
    if not iv or iv.get("iv_30d_pct") is None:
        return []
    s = f"Options are priced at {_num(iv['iv_30d_pct'])}% implied volatility"
    if iv.get("percentile_1y") is not None:
        s += f", the {_ordinal(int(iv['percentile_1y']))} percentile of the past year"
    out = [s + "."]
    if iv.get("tested_as_filter") and iv["tested_as_filter"] != "CANDIDATE FILTER":
        # The one test of using it as a rule failed; saying so stops the
        # number being read as advice to buy when it is low.
        out.append("Buying only below its one-year median was tested and did not beat luck: context, not a signal.")
    return out


def _forward(fwd: dict | None) -> list[str]:
    if not fwd or not fwd.get("days_logged"):
        return []
    days = fwd["days_logged"]
    s = f"The forward log holds {days} day{'s' if days != 1 else ''}, recorded before each outcome was known."
    # Saying the sample is too small matters more than any figure in it.
    return [s, "That is far too few to judge anything yet."] if days < 30 else [s]


def compose(ctx: dict) -> str:
    """The whole explanation, as plain paragraphs."""
    rec = ctx.get("recommendation") or {}
    opening = [ACTIONS.get(rec.get("action"), "The system has no recommendation today.")]
    if rec.get("headline"):
        opening.append(rec["headline"] if rec["headline"].endswith(".") else rec["headline"] + ".")

    bar = rec.get("bar") or {}
    judged = bar.get("hypotheses_judged") or bar.get("patterns_judged")
    if bar.get("min_t") is not None and judged:
        opening.append(
            f"With {judged} hypotheses judged on the same holdout data, a result now has to clear a t-statistic "
            f"of at least {_num(bar['min_t'])} to count as an edge, more when it rests on few trades, because "
            "testing many ideas makes one look good by chance.")

    paragraphs = [
        " ".join(opening),
        " ".join(_formed(ctx.get("patterns_formed_on_last_close") or [])),
        " ".join(_could_form(ctx.get("patterns_that_could_form_next_close") or [])),
        " ".join(_analogs(ctx.get("similar_past_days"))),
        " ".join(_iv(ctx.get("implied_volatility"))),
        " ".join(_forward(ctx.get("forward_track_record"))),
    ]
    return "\n\n".join(p for p in paragraphs if p.strip())
