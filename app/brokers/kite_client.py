"""Minimal Kite Connect HTTP client.

Distilled from openalgo/broker/zerodha/api/{auth_api,data}.py — same protocol,
no framework deps. Handles:
  - login URL construction
  - request_token → access_token exchange (sha256 checksum)
  - quote fetching by exchange:symbol pair
  - holdings fetching

Reference: https://kite.trade/docs/connect/v3/
"""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Any, Optional

import httpx

KITE_API_BASE = "https://api.kite.trade"
KITE_LOGIN_BASE = "https://kite.zerodha.com/connect/login"


def build_login_url(api_key: str) -> str:
    """Step 1 of Kite's auth flow — user is redirected here to log in.
    On success Kite redirects to the URL registered in the developer console
    with `?request_token=XXX&action=login&status=success` appended."""
    return f"{KITE_LOGIN_BASE}?api_key={api_key}&v=3"


def exchange_request_token(api_key: str, api_secret: str, request_token: str) -> tuple[Optional[str], Optional[str]]:
    """Step 2 of Kite's auth flow — POST request_token + sha256 checksum,
    receive an access_token valid until ~6am IST next day.

    Returns (access_token, error_message). One of them is always None.
    """
    checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()
    payload = {"api_key": api_key, "request_token": request_token, "checksum": checksum}
    headers = {"X-Kite-Version": "3"}

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(f"{KITE_API_BASE}/session/token", headers=headers, data=payload)
        response.raise_for_status()
        data = response.json()
        access_token = data.get("data", {}).get("access_token")
        if not access_token:
            return None, "Kite responded but did not include access_token"
        return access_token, None
    except httpx.HTTPStatusError as e:
        try:
            msg = e.response.json().get("message", str(e))
        except Exception:
            msg = e.response.text or str(e)
        return None, f"Kite auth failed: {msg}"
    except Exception as e:
        return None, f"Kite auth error: {e}"


def _auth_header(api_key: str, access_token: str) -> dict:
    return {
        "X-Kite-Version": "3",
        "Authorization": f"token {api_key}:{access_token}",
    }


def get_quote(api_key: str, access_token: str, symbol: str, exchange: str = "NSE") -> dict:
    """Fetch a single quote. Returns a dict with ltp/open/high/low/close/volume.
    Raises RuntimeError on API failure."""
    instrument = f"{exchange}:{symbol}"
    encoded = urllib.parse.quote(instrument)

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{KITE_API_BASE}/quote?i={encoded}",
                headers=_auth_header(api_key, access_token),
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        try:
            msg = e.response.json().get("message", str(e))
        except Exception:
            msg = e.response.text or str(e)
        raise RuntimeError(f"Kite quote API failed: {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Kite quote error: {e}") from e

    body = response.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Kite quote API returned non-success: {body.get('message', body)}")

    quote = body.get("data", {}).get(instrument)
    if not quote:
        raise RuntimeError(f"No quote data for {instrument}")

    ohlc = quote.get("ohlc", {}) or {}
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ltp": quote.get("last_price", 0),
        "open": ohlc.get("open", 0),
        "high": ohlc.get("high", 0),
        "low": ohlc.get("low", 0),
        "prev_close": ohlc.get("close", 0),
        "volume": quote.get("volume", 0),
    }


def get_holdings(api_key: str, access_token: str) -> list[dict]:
    """Fetch the user's long-term holdings from Kite."""
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                f"{KITE_API_BASE}/portfolio/holdings",
                headers=_auth_header(api_key, access_token),
            )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        try:
            msg = e.response.json().get("message", str(e))
        except Exception:
            msg = e.response.text or str(e)
        raise RuntimeError(f"Kite holdings API failed: {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Kite holdings error: {e}") from e

    body = response.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Kite holdings API returned non-success: {body.get('message', body)}")

    holdings = body.get("data", []) or []
    # Normalize to a small canonical shape — only fields we care about
    return [
        {
            "symbol": h.get("tradingsymbol", ""),
            "exchange": h.get("exchange", ""),
            "quantity": h.get("quantity", 0),
            "avg_price": h.get("average_price", 0),
            "ltp": h.get("last_price", 0),
            "pnl": h.get("pnl", 0),
        }
        for h in holdings
    ]
