"""Groww BrokerAdapter. Server-side auth — no redirect URL needed.

UX implication: there's no get_login_url for Groww. Instead, the
exchange_request_token method ignores its argument and uses api_key/api_secret
directly. Frontend handles this by showing 'Connect (server-side)' which POSTs
straight to /broker/groww/callback with an empty request_token.
"""
from app.brokers.base import BrokerAdapter
from app.brokers import groww_client as cli


class GrowwAdapter(BrokerAdapter):
    name = "groww"

    def get_login_url(self) -> str:
        # No browser redirect needed; the UI shows a "no redirect needed" message.
        return ""

    def exchange_request_token(self, request_token: str):
        # `request_token` is ignored — Groww's auth is purely server-side.
        return cli.get_access_token(self.api_key, self.api_secret)

    def get_holdings(self) -> list[dict]:
        if not self.access_token:
            raise RuntimeError("Not authenticated")
        return cli.get_holdings(self.api_key, self.access_token)

    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if not self.access_token:
            raise RuntimeError("Not authenticated")
        return cli.get_quote(self.api_key, self.access_token, symbol, exchange)
