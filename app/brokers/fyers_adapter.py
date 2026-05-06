"""Fyers BrokerAdapter."""
from app.brokers.base import BrokerAdapter
from app.brokers import fyers_client as cli


class FyersAdapter(BrokerAdapter):
    name = "fyers"

    def get_login_url(self) -> str:
        return cli.build_login_url(self.api_key)

    def exchange_request_token(self, request_token: str):
        return cli.exchange_request_token(self.api_key, self.api_secret, request_token)

    def get_holdings(self) -> list[dict]:
        if not self.access_token:
            raise RuntimeError("Not authenticated")
        return cli.get_holdings(self.api_key, self.access_token)

    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if not self.access_token:
            raise RuntimeError("Not authenticated")
        return cli.get_quote(self.api_key, self.access_token, symbol, exchange)
