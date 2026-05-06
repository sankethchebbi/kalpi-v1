"""Angel One BrokerAdapter.

Auth shape is unique: (clientcode, pin, totp) instead of OAuth redirect.
We fit it into BrokerAdapter by:
  - api_secret slot stores the clientcode
  - request_token is "PIN:TOTP" (frontend joins them on submit)
  - get_login_url returns "" (no redirect)
"""
from app.brokers.base import BrokerAdapter
from app.brokers import angel_client as cli


class AngelAdapter(BrokerAdapter):
    name = "angel"

    def get_login_url(self) -> str:
        return ""  # No browser redirect — frontend shows a TOTP form.

    def exchange_request_token(self, request_token: str):
        # request_token format: "PIN:TOTP". api_secret holds clientcode.
        if ":" not in (request_token or ""):
            return None, "Angel expects 'PIN:TOTP' as the request token"
        pin, totp = request_token.split(":", 1)
        clientcode = self.api_secret  # repurposed slot
        return cli.authenticate(self.api_key, clientcode, pin.strip(), totp.strip())

    def get_holdings(self) -> list[dict]:
        if not self.access_token:
            raise RuntimeError("Not authenticated")
        return cli.get_holdings(self.api_key, self.access_token)

    def get_quote(self, symbol: str, exchange: str = "NSE") -> dict:
        if not self.access_token:
            raise RuntimeError("Not authenticated")
        return cli.get_quote(self.api_key, self.access_token, symbol, exchange)
