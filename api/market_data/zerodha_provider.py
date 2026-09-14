from datetime import date

from .base import Candle


class ZerodhaProvider:
    """Not implemented yet — on purpose.

    Wiring this up needs two things you haven't approved yet (per the
    project's budget rule):
      1. A Kite Connect API subscription (₹500/month), which requires
         your existing Zerodha trading account.
      2. Generating an API key/secret and completing the login flow to
         get an access token.

    This class exists now only to prove the abstraction is real: it
    implements the exact same MarketDataProvider interface as CSVProvider
    and YFinanceProvider. When you're ready to pay for Kite Connect
    (likely around Phase 7, per the project plan), this is the only file
    that needs real implementation — nothing else in the app changes.
    """

    def __init__(self, api_key: str | None = None, access_token: str | None = None):
        self.api_key = api_key
        self.access_token = access_token

    def get_ohlc(self, symbol: str, timeframe: str, start: date, end: date) -> list[Candle]:
        raise NotImplementedError(
            "ZerodhaProvider is a stub. Set up Kite Connect (₹500/month) and pass "
            "an api_key/access_token before using this provider."
        )
