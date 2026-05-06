"""Abstract base class every broker adapter implements.

Adding a new broker = create a new module that subclasses BrokerAdapter and
implements these methods, then register it in factory.py. Engine + routes
+ frontend stay untouched.
"""
from abc import ABC, abstractmethod


class BrokerAdapter(ABC):
    """Standardized interface across all brokers.

    The constructor receives api_key + api_secret (entered by user via UI).
    `access_token` is set after the OAuth-ish callback completes.
    """

    name: str = "base"

    def __init__(self, api_key: str, api_secret: str, access_token: str | None = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token

    @abstractmethod
    def get_login_url(self) -> str:
        """Return the broker's hosted login URL the user is redirected to."""

    @abstractmethod
    def exchange_request_token(self, request_token: str) -> tuple[str | None, str | None]:
        """Exchange the broker's redirect-back token for a long-lived access_token.
        Returns (access_token, error). Exactly one is not None."""

    @abstractmethod
    def get_holdings(self) -> list[dict]:
        """Return a list of {symbol, exchange, quantity, avg_price, ltp, pnl}."""

    @abstractmethod
    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        """Return {symbol, exchange, ltp, open, high, low, prev_close, volume}."""
