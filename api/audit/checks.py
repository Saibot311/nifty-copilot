"""Importing this module registers every audit check."""

from . import checks_data  # noqa: F401  Phase 0
from . import checks_platform  # noqa: F401  Phases 1-4
from . import checks_quant  # noqa: F401  Phase 5
from . import checks_backtest  # noqa: F401  Phases 6-8
from . import checks_live  # noqa: F401  Phases 9-12
from . import checks_market  # noqa: F401  market context engine
