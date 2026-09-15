from backtest.costs import CostModel
from backtest.options_engine import OptionsCostModel


def test_index_round_trip_cost_is_positive_and_small():
    cost = CostModel().round_trip_cost_pct()
    assert cost > 0
    # A sanity band, not a precise assertion -- catches a decimal-point
    # or unit error (e.g. accidentally returning a fraction instead of a
    # percentage) without being brittle to a deliberate rate-card tweak.
    assert 0.05 < cost < 2.0


def test_options_round_trip_cost_exceeds_index_cost():
    """Options costs scale with premium, not notional, and premium is a
    small fraction of the underlying -- so proportionally, option costs
    must come out higher than index costs. If this ever inverts, the cost
    model has a unit bug."""
    index_cost = CostModel().round_trip_cost_pct()
    options_cost = OptionsCostModel().round_trip_cost_fraction() * 100
    assert options_cost > index_cost


def test_zero_slippage_model_is_cheaper_than_default():
    default = OptionsCostModel()
    zero_slippage = OptionsCostModel(premium_slippage_pct=0.0)
    assert zero_slippage.round_trip_cost_fraction() < default.round_trip_cost_fraction()
