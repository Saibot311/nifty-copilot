"""How many hypotheses have had their one look at the 2024-26 holdout — the
count the recommendation's evidence bar is corrected for (I5).

Every study that judged something on the holdout is counted, from what it
actually stored rather than from a number typed into a file: the patterns
with holdout trades, the pre-registered IV filter, the six structural
tests, the replications on other indices, and the news-tone tests. Each was
another chance for luck to clear a bar, so each raises it for all of them.

This used to be `structural_research.holdout_tests_judged`, which stopped at
the structural six. Replication and the news study were added later and
never joined the count, so the gate asked for t >= 2.89 (26 hypotheses) when
53 had been judged and the honest bar was 3.11. That function is left where
it is — it sits in a pre-registered file — and nothing calls it any more.

A registered study's own bar is frozen with it (`TESTS_IN_FAMILY` in each
file, inside its pre-registration hash). This count is what a result has to
clear *now*, and it only ever goes up.
"""


def holdout_family(pattern_research: dict | None) -> dict:
    """{family: hypotheses judged} plus "total"."""
    from .iv_research import load_iv_research
    from .news_research import load_news_research
    from .replication import load_replication
    from .structural_research import load_structural_research

    def _count(load) -> int:
        try:
            return len((load() or {}).get("hypotheses", []))
        except Exception:
            return 0

    try:
        iv = 1 if load_iv_research() else 0
    except Exception:
        iv = 0
    family = {
        "patterns": sum(1 for p in (pattern_research or {}).get("patterns", [])
                        if (p.get("holdout") or {}).get("num_trades")),
        "iv_filter": iv,
        "structural": _count(load_structural_research),
        "replication": _count(load_replication),
        "news_tone": _count(load_news_research),
    }
    return {**family, "total": sum(family.values())}
