"""The 26 patterns and the option grid their verdicts rest on are frozen.

Every other study here carries a pre-registration hash with a literal
tripwire: structural, replication, the IV filter, the news tone. The
patterns — 19 of the 53 hypotheses judged on 2024-26 — had none. Retuning a
pattern's RSI period, or its option grid, would have been re-judged by the
next nightly run as if it were the same hypothesis, and nothing would have
counted it as a new one. This makes any such edit fail loudly.

The fingerprint covers each rule's parameters, direction, option type and
the rule's own code (as a syntax tree, so comments and formatting do not
trip it), and the grid, split and sizing the option research uses. It does
not cover the shared indicator functions each rule calls.

If this fails because a pattern was deliberately changed: that is a new
hypothesis. Register it under a new name, keep the old one, and let the
family count — and the evidence bar for everything — rise with it.
"""

import ast
import hashlib
import inspect
import json
import textwrap

FROZEN = "a1f5ad23cd652119"  # a literal: computing it live would pass any edit


def _fingerprint() -> str:
    import backtest.pattern_options as po
    from backtest.strategies import STRATEGY_REGISTRY

    def shape(fn) -> str:
        return ast.dump(ast.parse(textwrap.dedent(inspect.getsource(fn))), include_attributes=False)

    patterns = {name: {"params": spec["params"], "direction": spec.get("direction"),
                       "option_type": spec.get("option_type"), "rule": shape(spec["fn"])}
                for name, spec in sorted(STRATEGY_REGISTRY.items())}
    grid = {"moneyness": po.MONEYNESS_PCT, "min_dte": po.MIN_DTE, "hold": po.HOLD_DAYS,
            "options_start": po.OPTIONS_START, "split": po.SPLIT_DATE, "min_dev": po.MIN_DEV_TRADES,
            "min_holdout": po.MIN_HOLDOUT_TRADES, "lot": po.LOT_SIZE}
    blob = json.dumps({"patterns": patterns, "grid": grid}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def test_the_judged_patterns_and_their_option_grid_have_not_been_edited():
    assert _fingerprint() == FROZEN


def test_there_are_still_26_patterns():
    from backtest.strategies import STRATEGY_REGISTRY
    assert len(STRATEGY_REGISTRY) == 26
