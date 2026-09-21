"""APPROVED must mean the entry rule adds something beyond market drift.
Before this rule, Prev-Day-High Breakout was APPROVED at +0.043%/trade in
the holdout, less than simply being long over the same period."""

from backtest.walkforward import holdout_verdict


def test_profitable_but_below_drift_is_rejected():
    status, reason = holdout_verdict(
        dev_exp=0.2, holdout_exp=0.043, dev_baseline=0.35, holdout_baseline=0.4,
        holdout_n=95, min_holdout_trades=15, direction="long",
    )
    assert status == "REJECTED"
    assert "always-long" in reason


def test_beating_baseline_in_only_one_period_is_rejected():
    status, _ = holdout_verdict(0.9, 0.3, 0.4, 0.4, 50, 15, "long")
    assert status == "REJECTED"


def test_beats_baseline_in_both_with_enough_trades_is_approved():
    status, _ = holdout_verdict(0.9, 0.8, 0.4, 0.4, 50, 15, "long", holdout_t=2.5)
    assert status == "APPROVED"


def test_thin_holdout_that_clears_the_bar_is_conditional():
    # Significant, but on too few trades to trust: the one thing CONDITIONAL means.
    status, reason = holdout_verdict(0.9, 0.8, 0.4, 0.4, 10, 15, "long", holdout_t=4.0)
    assert status == "CONDITIONAL" and "only 10 holdout trades" in reason


def test_thin_holdout_does_not_skip_the_significance_test():
    # Found by the audit. This used to return CONDITIONAL with no t at all:
    # the sample-size check ran first and returned before significance was
    # ever tested. Bollinger Band Reversion held CONDITIONAL at t = 0.86.
    status, _ = holdout_verdict(0.9, 0.8, 0.4, 0.4, 10, 15, "long")
    assert status == "REJECTED"
    status, _ = holdout_verdict(3667, 3667, 100, -2000, 11, 15, "long", holdout_t=0.86, unit="₹")
    assert status == "REJECTED"


def test_less_evidence_never_earns_a_better_verdict():
    rank = {"REJECTED": 0, "CONDITIONAL": 1, "APPROVED": 2}
    for t in (0.2, 0.9, 1.8, 2.4, 3.5):
        few, _ = holdout_verdict(0.9, 0.8, 0.4, 0.4, 11, 15, "long", holdout_t=t)
        many, _ = holdout_verdict(0.9, 0.8, 0.4, 0.4, 60, 15, "long", holdout_t=t)
        assert rank[few] <= rank[many], f"t={t}: {few} on 11 trades beat {many} on 60"


def test_the_bar_rises_for_small_samples():
    from backtest.walkforward import significance_bar
    assert significance_bar(11) == 2.23
    assert significance_bar(1000) == 1.96
    # 2.1 clears the bar on 60 trades but not on 11.
    assert holdout_verdict(0.9, 0.8, 0.4, 0.4, 60, 15, "long", holdout_t=2.1)[0] == "APPROVED"
    assert holdout_verdict(0.9, 0.8, 0.4, 0.4, 11, 15, "long", holdout_t=2.1)[0] == "REJECTED"


def test_short_strategy_is_judged_against_always_short():
    # Always-short loses in a rising market, so a short rule that makes
    # money clears that baseline — but it still has to make money.
    status, reason = holdout_verdict(0.5, 0.6, -0.5, -0.4, 40, 15, "short", holdout_t=3.0)
    assert status == "APPROVED"
    assert "always-short" in reason
    status, _ = holdout_verdict(-0.1, 0.6, -0.5, -0.4, 40, 15, "short", holdout_t=3.0)
    assert status == "REJECTED"


def test_beating_baseline_by_noise_is_rejected():
    # The real case: MACD Bullish Crossover, +0.068%/trade over baseline, t = 0.18.
    status, reason = holdout_verdict(0.476, 0.062, 0.213, -0.006, 47, 15, "long", holdout_t=0.18)
    assert status == "REJECTED"
    assert "luck" in reason


def test_t_stat_matches_hand_calculation():
    from backtest.walkforward import excess_t_stat
    # mean 2, baseline 0, sample sd 1.1547, n 4 -> t = 2 / (1.1547 / 2) ≈ 3.46
    assert excess_t_stat([1.0, 3.0, 1.0, 3.0], 0.0) == round(2 / (1.1547005383792515 / 2), 2)
    assert excess_t_stat([1.0], 0.0) is None


def test_welch_includes_the_baselines_own_uncertainty():
    from backtest.walkforward import excess_t_stat, welch_t_stat
    a, b = [4.0, 6.0, 5.0, 7.0, 3.0], [1.0, 2.0, 0.0, 3.0, 1.0, 2.0]
    # By hand: means 5 and 1.5, variances 2.5 and 1.1, se = sqrt(2.5/5 + 1.1/6)
    assert welch_t_stat(a, b) == round(3.5 / (2.5 / 5 + 1.1 / 6) ** 0.5, 2)
    # Treating the baseline mean as exact always gives a larger t.
    assert excess_t_stat(a, 1.5) > welch_t_stat(a, b)


def test_rupee_unit_formats_reasons_in_rupees():
    status, reason = holdout_verdict(900, 50, 1200, -100, 40, 15, "long", 0.4, unit="₹",
                                     baseline_label="buying this CE with no signal")
    assert status == "REJECTED" and "₹900 vs ₹1,200" in reason
