"""Routes that wrap the broker adapter for the current user.

Flow:
  1. User saves credentials via /settings/broker-credentials (Step 1)
  2. GET /broker/{name}/login-url → redirect URL to Kite
  3. User logs in on Kite, gets redirected back with ?request_token=...
  4. Frontend POSTs that token to /broker/{name}/callback
  5. Now /broker/{name}/holdings and /broker/{name}/quote work
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.brokers.factory import get_adapter, supported_brokers
from app.db import get_db
from app.models import BrokerConnection, User

router = APIRouter(prefix="/broker", tags=["broker"])


class CallbackPayload(BaseModel):
    request_token: str


def _load_connection(db: Session, user_id: int, broker_name: str) -> BrokerConnection:
    """Fetch the user's saved credentials for a broker. Raises 400 if missing."""
    if broker_name not in supported_brokers():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported broker. Supported: {supported_brokers()}",
        )

    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user_id,
            BrokerConnection.broker_name == broker_name,
        )
        .first()
    )
    if not conn or not conn.api_key or not conn.api_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No saved credentials for {broker_name}. Save them via /settings/broker-credentials first.",
        )
    return conn


@router.get("/{broker_name}/login-url")
def login_url(
    broker_name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the broker's hosted login URL. User opens this in a new tab,
    logs in, and is redirected back to the URL registered with the broker."""
    conn = _load_connection(db, user.id, broker_name)
    adapter = get_adapter(broker_name, conn.api_key, conn.api_secret)
    return {"login_url": adapter.get_login_url()}


@router.post("/{broker_name}/callback")
def callback(
    broker_name: str,
    payload: CallbackPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Exchange the broker's request_token for an access_token. Persist it."""
    conn = _load_connection(db, user.id, broker_name)
    adapter = get_adapter(broker_name, conn.api_key, conn.api_secret)

    access_token, error = adapter.exchange_request_token(payload.request_token)
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    conn.access_token = access_token
    conn.connected_at = datetime.utcnow()
    db.commit()
    return {"status": "ok", "broker": broker_name, "connected_at": conn.connected_at.isoformat()}


def _connected_adapter(db: Session, user_id: int, broker_name: str):
    """Fetch a fully-authenticated adapter or raise 401."""
    conn = _load_connection(db, user_id, broker_name)
    if not conn.access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{broker_name} not connected. Complete the login flow first.",
        )
    return get_adapter(broker_name, conn.api_key, conn.api_secret, conn.access_token)


@router.get("/{broker_name}/holdings")
def holdings(
    broker_name: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch real holdings from the broker."""
    adapter = _connected_adapter(db, user.id, broker_name)
    try:
        return {"holdings": adapter.get_holdings()}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/{broker_name}/quote/{symbol}")
def quote(
    broker_name: str,
    symbol: str,
    exchange: str = "NSE",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch a real-time quote for one symbol."""
    adapter = _connected_adapter(db, user.id, broker_name)
    try:
        return adapter.get_quote(symbol.upper(), exchange.upper())
    except Exception as e:
        # Most common cause: Kite personal API without market-data add-on
        # ("PermissionException"). Surface the broker's exact message.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{broker_name} quote error: {e}",
        )



@router.get("/auth-flows")
def auth_flows():
    """Return per-broker auth UX hints so the frontend can render the right form."""
    from app.brokers.factory import AUTH_FLOWS, supported_brokers
    return {b: AUTH_FLOWS.get(b, {}) for b in supported_brokers()}
