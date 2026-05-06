"""Zerodha implementation of BrokerAdapter.

Uses the standalone kite_client (no openalgo framework deps). This adapter is
intentionally thin — its job is to translate between the broker-agnostic
BrokerAdapter interface and Kite's HTTP protocol.

Note: place_order is NOT implemented here. The execution engine writes mock
orders directly to the local DB (per assignment scope — no real trades).
"""
from app.brokers.base import BrokerAdapter
from app.brokers.kite_client import (
    build_login_url,
    exchange_request_token,
    get_holdings,
    get_quote,
)


class ZerodhaAdapter(BrokerAdapter):
    name = "zerodha"

    def get_login_url(self) -> str:
        return build_login_url(self.api_key)

    def exchange_request_token(self, request_token: str) -> tuple[str | None, str | None]:
        return exchange_request_token(self.api_key, self.api_secret, request_token)

    def get_holdings(self) -> list[dict]:
        if not self.access_token:
            raise RuntimeError("Not authenticated — call exchange_request_token first")
        return get_holdings(self.api_key, self.access_token)

    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if not self.access_token:
            raise RuntimeError("Not authenticated — call exchange_request_token first")
        return get_quote(self.api_key, self.access_token, symbol, exchange)
