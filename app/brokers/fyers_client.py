"""Minimal Fyers v3 HTTP client. Distilled from openalgo/broker/fyers."""
from __future__ import annotations

import hashlib
import urllib.parse
from typing import Optional

import httpx

API_BASE = "https://api-t1.fyers.in"


def build_login_url(api_key: str, redirect_uri: str = "http://localhost:8000/callback") -> str:
    """Fyers auth flow: redirect user, get back ?auth_code=...&state=..."""
    params = urllib.parse.urlencode({
        "client_id": api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": "trade_engine",
    })
    return f"https://api-t1.fyers.in/api/v3/generate-authcode?{params}"


def exchange_request_token(api_key: str, api_secret: str, auth_code: str) -> tuple[Optional[str], Optional[str]]:
    """Fyers takes app_id_hash = sha256("apikey:secret") + auth_code. Returns access_token."""
    app_id_hash = hashlib.sha256(f"{api_key}:{api_secret}".encode()).hexdigest()
    payload = {"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code}
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.post(f"{API_BASE}/api/v3/validate-authcode",
                       headers={"Content-Type": "application/json"}, json=payload)
        r.raise_for_status()
        data = r.json()
        if data.get("s") == "ok" and data.get("access_token"):
            return data["access_token"], None
        return None, f"Fyers auth failed: {data.get('message', data)}"
    except httpx.HTTPStatusError as e:
        try: msg = e.response.json().get("message", str(e))
        except Exception: msg = e.response.text or str(e)
        return None, f"Fyers auth HTTP error: {msg}"
    except Exception as e:
        return None, f"Fyers auth error: {e}"


def get_quote(api_key: str, access_token: str, symbol: str, exchange: str = "NSE") -> dict:
    """Fyers symbol convention: NSE:RELIANCE-EQ. Equities get -EQ, indices/derivatives don't."""
    fyers_symbol = f"{exchange}:{symbol}-EQ" if exchange in ("NSE", "BSE") else f"{exchange}:{symbol}"
    encoded = urllib.parse.quote(fyers_symbol)
    headers = {"Authorization": f"{api_key}:{access_token}"}
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{API_BASE}/data/quotes?symbols={encoded}", headers=headers)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        try: msg = e.response.json().get("message", str(e))
        except Exception: msg = e.response.text or str(e)
        raise RuntimeError(f"Fyers quote failed: {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Fyers quote error: {e}") from e
    body = r.json()
    if body.get("s") != "ok":
        raise RuntimeError(f"Fyers quote non-ok: {body.get('message', body)}")
    items = body.get("d") or []
    if not items:
        raise RuntimeError(f"Fyers returned no data for {fyers_symbol}")
    v = (items[0] or {}).get("v") or {}
    return {
        "symbol": symbol, "exchange": exchange,
        "ltp": v.get("lp", 0),
        "open": v.get("open_price", 0),
        "high": v.get("high_price", 0),
        "low": v.get("low_price", 0),
        "prev_close": v.get("prev_close_price", 0),
        "volume": v.get("volume", 0),
    }


def get_holdings(api_key: str, access_token: str) -> list[dict]:
    """Fyers /portfolio/holdings."""
    headers = {"Authorization": f"{api_key}:{access_token}"}
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(f"{API_BASE}/api/v3/holdings", headers=headers)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Fyers holdings error: {e}") from e
    body = r.json()
    if body.get("s") != "ok":
        raise RuntimeError(f"Fyers holdings non-ok: {body.get('message', body)}")
    return [
        {
            "symbol": h.get("symbol", ""),
            "exchange": "NSE",
            "quantity": h.get("quantity", 0),
            "avg_price": h.get("costPrice", 0),
            "ltp": h.get("ltp", 0),
            "pnl": h.get("pl", 0),
        }
        for h in (body.get("holdings") or [])
    ]
