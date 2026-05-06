"""Angel One (SmartAPI) HTTP client. Auth uses clientcode+pin+TOTP — no redirect.

Important UX detail: TOTP rotates every 30s. We treat (pin, totp) as the
'request_token' shape — the user enters them at connect time. The
api_secret slot in our schema is repurposed to hold the user's clientcode.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

API_BASE = "https://apiconnect.angelone.in"


def authenticate(api_key: str, clientcode: str, pin: str, totp: str) -> tuple[Optional[str], Optional[str]]:
    """POST /rest/auth/angelbroking/user/v1/loginByPassword."""
    headers = {
        "Content-Type": "application/json", "Accept": "application/json",
        "X-UserType": "USER", "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": api_key,
    }
    payload = {"clientcode": clientcode, "password": pin, "totp": totp}
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.post(f"{API_BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
                       headers=headers, content=json.dumps(payload))
        data = r.json()
        if data.get("status") and data.get("data", {}).get("jwtToken"):
            return data["data"]["jwtToken"], None
        return None, data.get("message", "Angel auth failed")
    except Exception as e:
        return None, f"Angel auth error: {e}"


def _angel_exchange(exchange: str) -> str:
    return {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE", "MCX_INDEX": "MCX"}.get(exchange, exchange)


def get_quote(api_key: str, access_token: str, symbol: str, exchange: str = "NSE",
              token: str = "") -> dict:
    """Angel needs an instrument-token (numeric) to fetch a quote.

    Without the master-contract DB we can't resolve symbol->token, so for the
    demo we ship a tiny built-in lookup of well-known NSE equities/indices.
    Anything outside the lookup raises RuntimeError and the engine falls back
    to a deterministic mock price (same path as Zerodha-without-data-feed).
    """
    if not token:
        token = _well_known_token(symbol, exchange)
    if not token:
        raise RuntimeError(f"Angel: no instrument token for {symbol} on {exchange}")

    headers = {
        "Authorization": f"Bearer {access_token}", "Content-Type": "application/json",
        "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00", "X-PrivateKey": api_key,
    }
    payload = {"mode": "FULL", "exchangeTokens": {_angel_exchange(exchange): [token]}}
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(f"{API_BASE}/rest/secure/angelbroking/market/v1/quote/",
                       headers=headers, content=json.dumps(payload))
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Angel quote error: {e}") from e
    body = r.json()
    if not body.get("status"):
        raise RuntimeError(f"Angel quote non-ok: {body.get('message', body)}")
    fetched = body.get("data", {}).get("fetched") or []
    if not fetched:
        raise RuntimeError("Angel returned no fetched data")
    q = fetched[0]
    return {
        "symbol": symbol, "exchange": exchange,
        "ltp": float(q.get("ltp", 0)),
        "open": float(q.get("open", 0)),
        "high": float(q.get("high", 0)),
        "low": float(q.get("low", 0)),
        "prev_close": float(q.get("close", 0)),
        "volume": int(q.get("tradeVolume", 0)),
    }


def get_holdings(api_key: str, access_token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {access_token}", "Content-Type": "application/json",
        "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00", "X-PrivateKey": api_key,
    }
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(f"{API_BASE}/rest/secure/angelbroking/portfolio/v1/getAllHolding",
                      headers=headers)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Angel holdings error: {e}") from e
    body = r.json()
    if not body.get("status"):
        raise RuntimeError(f"Angel holdings non-ok: {body.get('message', body)}")
    h_data = (body.get("data") or {}).get("holdings") or []
    return [
        {
            "symbol": h.get("tradingsymbol", ""),
            "exchange": h.get("exchange", "NSE"),
            "quantity": h.get("quantity", 0),
            "avg_price": h.get("averageprice", 0),
            "ltp": h.get("ltp", 0),
            "pnl": h.get("profitandloss", 0),
        }
        for h in h_data
    ]


# Tiny built-in token map for the demo. Real prod = master-contract DB.
_TOKEN_MAP = {
    ("NSE", "RELIANCE"): "2885", ("NSE", "TCS"): "11536", ("NSE", "INFY"): "1594",
    ("NSE", "HDFCBANK"): "1333", ("NSE", "ICICIBANK"): "4963", ("NSE", "SBIN"): "3045",
    ("NSE", "WIPRO"): "3787", ("NSE", "ITC"): "1660", ("NSE", "LT"): "11483",
    ("NSE_INDEX", "NIFTY"): "99926000", ("NSE_INDEX", "BANKNIFTY"): "99926009",
}


def _well_known_token(symbol: str, exchange: str) -> str:
    return _TOKEN_MAP.get((exchange, symbol), "")
