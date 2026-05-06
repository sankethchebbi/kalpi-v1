"""Broker registry.

Adding a new broker = create app/brokers/<name>_adapter.py implementing
BrokerAdapter, then add one line to ADAPTERS below. Engine, routes, schemas,
and frontend stay untouched. This is the assignment's "6th broker in minimal
code change" claim, made literal.
"""
from app.brokers.base import BrokerAdapter
from app.brokers.angel_adapter import AngelAdapter
from app.brokers.fyers_adapter import FyersAdapter
from app.brokers.groww_adapter import GrowwAdapter
from app.brokers.upstox_adapter import UpstoxAdapter
from app.brokers.zerodha_adapter import ZerodhaAdapter

ADAPTERS: dict[str, type[BrokerAdapter]] = {
    "zerodha": ZerodhaAdapter,
    "fyers":   FyersAdapter,
    "upstox":  UpstoxAdapter,
    "groww":   GrowwAdapter,
    "angel":   AngelAdapter,
}


def get_adapter(broker_name: str, api_key: str, api_secret: str,
                access_token: str | None = None) -> BrokerAdapter:
    cls = ADAPTERS.get(broker_name)
    if cls is None:
        raise KeyError(f"Unknown broker: {broker_name}. Supported: {sorted(ADAPTERS.keys())}")
    return cls(api_key=api_key, api_secret=api_secret, access_token=access_token)


def supported_brokers() -> list[str]:
    return sorted(ADAPTERS.keys())


# Per-broker auth UX hints — frontend uses these to render the right form.
AUTH_FLOWS: dict[str, dict] = {
    "zerodha": {"flow": "redirect",  "field_label": "request_token",
                "secret_label": "API Secret", "needs_redirect": True},
    "fyers":   {"flow": "redirect",  "field_label": "auth_code",
                "secret_label": "API Secret", "needs_redirect": True},
    "upstox":  {"flow": "redirect",  "field_label": "code",
                "secret_label": "API Secret", "needs_redirect": True},
    "groww":   {"flow": "server",    "field_label": "",
                "secret_label": "API Secret", "needs_redirect": False},
    "angel":   {"flow": "totp",      "field_label": "PIN:TOTP",
                "secret_label": "Client Code", "needs_redirect": False},
}
