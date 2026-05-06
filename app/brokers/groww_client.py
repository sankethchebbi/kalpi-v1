"""Groww HTTP client. Auth is server-side (no redirect): API key+secret -> token via checksum."""
from __future__ import annotations

import hashlib
import time
from typing import Optional

import httpx

API_BASE = "https://api.groww.in"


def get_access_token(api_key: str, api_secret: str) -> tuple[Optional[str], Optional[str]]:
    """Groww auth: POST { key_type, checksum=sha256(secret+ts), timestamp } with Bearer api_key."""
    timestamp = str(int(time.time()))
    checksum = hashlib.sha256(f"{api_secret}{timestamp}".encode("utf-8")).hexdigest()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"key_type": "approval", "checksum": checksum, "timestamp": timestamp}
    try:
        with httpx.Client(timeout=20.0) as c:
            r = c.post(f"{API_BASE}/v1/token/api/access", headers=headers, json=payload)
        if r.status_code == 200:
            tok = r.json().get("token")
            if tok:
                return tok, None
            return None, "Groww: no token in response"
        try:
            msg = r.json().get("message", r.text)
        except Exception:
            msg = r.text
        return None, f"Groww auth failed ({r.status_code}): {msg}"
    except Exception as e:
        return None, f"Groww auth error: {e}"


def _segment(exchange: str) -> str:
    return "FNO" if exchange in ("NFO", "BFO") else "CASH"


def _groww_exchange(exchange: str) -> str:
    if exchange in ("NFO", "NSE_INDEX"): return "NSE"
    if exchange in ("BFO", "BSE_INDEX"): return "BSE"
    return exchange


def get_quote(api_key: str, access_token: str, symbol: str, exchange: str = "NSE") -> dict:
    """Groww /v1/live-data/quote with exchange + segment + trading_symbol params."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    params = {
        "exchange": _groww_exchange(exchange),
        "segment": _segment(exchange),
        "trading_symbol": symbol,
    }
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{API_BASE}/v1/live-data/quote", headers=headers, params=params)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        try: msg = e.response.json().get("message", str(e))
        except Exception: msg = e.response.text or str(e)
        raise RuntimeError(f"Groww quote failed: {msg}") from e
    except Exception as e:
        raise RuntimeError(f"Groww quote error: {e}") from e
    body = r.json()
    if body.get("status") != "SUCCESS":
        raise RuntimeError(f"Groww quote non-SUCCESS: {body.get('message', body)}")
    p = body.get("payload") or {}
    ohlc = p.get("ohlc") or {}
    if isinstance(ohlc, str):
        # Some Groww responses serialize ohlc as a stringified dict — parse defensively.
        ohlc_dict = {}
        try:
            for part in ohlc.strip("{}").split(","):
                k, v = part.split(":")
                ohlc_dict[k.strip()] = float(v.strip())
            ohlc = ohlc_dict
        except Exception:
            ohlc = {}
    return {
        "symbol": symbol, "exchange": exchange,
        "ltp": p.get("last_price", 0),
        "open": ohlc.get("open", 0),
        "high": ohlc.get("high", 0),
        "low": ohlc.get("low", 0),
        "prev_close": ohlc.get("close", 0),
        "volume": p.get("volume", 0),
    }


def get_holdings(api_key: str, access_token: str) -> list[dict]:
    """Groww /v1/holdings/user."""
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get(f"{API_BASE}/v1/holdings/user", headers=headers)
        r.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Groww holdings error: {e}") from e
    body = r.json()
    if body.get("status") != "SUCCESS":
        raise RuntimeError(f"Groww holdings non-SUCCESS: {body.get('message', body)}")
    return [
        {
            "symbol": h.get("trading_symbol", ""),
            "exchange": h.get("exchange", "NSE"),
            "quantity": h.get("quantity", 0),
            "avg_price": h.get("average_price", 0),
            "ltp": h.get("last_price", 0),
            "pnl": h.get("pnl", 0),
        }
        for h in ((body.get("payload") or {}).get("holdings") or [])
    ]
