"""Upstox v2/v3 HTTP client. Distilled from openalgo/broker/upstox."""
from __future__ import annotations

import urllib.parse
from typing import Optional

import httpx

API_V2 = "https://api.upstox.com/v2"
API_V3 = "https://api.upstox.com/v3"


def build_login_url(api_key: str, redirect_uri: str = "http://localhost:8000/callback") -> str:
    """Upstox auth flow: redirect, callback ?code=..."""
    params = urllib.parse.urlencode({
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
    })
    return f"https://api.upstox.com/v2/login/authorization/dialog?{params}"


def exchange_request_token(api_key: str, api_secret: str, code: str,
                            redirect_uri: str = "http://localhost:8000/callback"):
    """Standard OAuth: POST code + client_id + client_secret + redirect_uri."""
    payload = {
        "code": code, "client_id": api_key, "client_secret": api_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(f"{API_V2}/login/authorization/token", data=payload)
        if r.status_code == 200:
            tok = r.json().get("access_token")
            if tok:
                return tok, None
            return None, "Upstox: no access_token in response"
        try:
            errs = r.json().get("errors", [])
            msg = "; ".join(e.get("message", "") for e in errs) or r.text
        except Exception:
            msg = r.text
        return None, f"Upstox auth failed ({r.status_code}): {msg}"
    except Exception as e:
        return None, f"Upstox auth error: {e}"


def _instrument_key(symbol: str, exchange: str) -> str:
    """Upstox uses NSE_EQ|INE002A01018-style keys ideally, but accepts NSE_EQ:RELIANCE
    via the legacy lookup. For demo we use the human-readable shorthand."""
    if exchange in ("NSE", "BSE"):
        return f"{exchange}_EQ|{symbol}"
    if exchange in ("NSE_INDEX", "BSE_INDEX"):
        return f"{exchange}|{symbol}"
    return f"{exchange}|{symbol}"


def get_quote(api_key: str, access_token: str, symbol: str, exchange: str = "NSE") -> dict:
    """Upstox v3 OHLC endpoint with interval=1d."""
    key = _instrument_key(symbol, exchange)
    encoded = urllib.parse.quote(key)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{API_V3}/market-quote/ohlc?instrument_key={encoded}&interval=1d",
                      headers=headers)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        try: msg = e.response.json().get("message", str(e))
        except Exception: msg = e.response.text or str(e)
        raise RuntimeError(f"Upstox quote failed: {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Upstox quote error: {e}") from e

    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox quote non-success: {body}")
    data = body.get("data") or {}
    if not data:
        raise RuntimeError(f"Upstox returned no data for {key}")
    quote = next(iter(data.values()))
    live = quote.get("live_ohlc") or {}
    prev = quote.get("prev_ohlc") or {}
    return {
        "symbol": symbol, "exchange": exchange,
        "ltp": quote.get("last_price", 0),
        "open": live.get("open", 0),
        "high": live.get("high", 0),
        "low": live.get("low", 0),
        "prev_close": prev.get("close", 0),
        "volume": live.get("volume", 0),
    }


def get_holdings(api_key: str, access_token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(f"{API_V2}/portfolio/long-term-holdings", headers=headers)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Upstox holdings error: {e}") from e
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Upstox holdings non-success: {body}")
    return [
        {
            "symbol": h.get("trading_symbol", ""),
            "exchange": h.get("exchange", "NSE"),
            "quantity": h.get("quantity", 0),
            "avg_price": h.get("average_price", 0),
            "ltp": h.get("last_price", 0),
            "pnl": h.get("pnl", 0),
        }
        for h in (body.get("data") or [])
    ]
