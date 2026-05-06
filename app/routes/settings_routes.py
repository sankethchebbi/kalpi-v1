"""Broker credentials settings — set once via UI on first boot.
This is where the user enters BROKER_API_KEY / BROKER_API_SECRET per broker."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import BrokerConnection, User
from app.schemas import BrokerCredentials, BrokerConnectionStatus

router = APIRouter(prefix="/settings", tags=["settings"])

SUPPORTED_BROKERS = {"zerodha", "fyers", "angel", "groww", "upstox"}


@router.post("/broker-credentials")
def save_broker_credentials(
    payload: BrokerCredentials,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save or update API key/secret for a broker. Upsert by (user_id, broker_name)."""
    if payload.broker_name not in SUPPORTED_BROKERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported broker. Use one of: {sorted(SUPPORTED_BROKERS)}",
        )

    conn = (
        db.query(BrokerConnection)
        .filter(
            BrokerConnection.user_id == user.id,
            BrokerConnection.broker_name == payload.broker_name,
        )
        .first()
    )

    if conn:
        conn.api_key = payload.api_key
        conn.api_secret = payload.api_secret
    else:
        conn = BrokerConnection(
            user_id=user.id,
            broker_name=payload.broker_name,
            api_key=payload.api_key,
            api_secret=payload.api_secret,
        )
        db.add(conn)

    db.commit()
    return {"status": "ok", "broker": payload.broker_name}


@router.get("/broker-status", response_model=list[BrokerConnectionStatus])
def get_broker_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return status of every supported broker for the current user."""
    rows = (
        db.query(BrokerConnection)
        .filter(BrokerConnection.user_id == user.id)
        .all()
    )
    by_name = {r.broker_name: r for r in rows}

    result = []
    for broker in sorted(SUPPORTED_BROKERS):
        row = by_name.get(broker)
        result.append(
            BrokerConnectionStatus(
                broker_name=broker,
                has_credentials=bool(row and row.api_key and row.api_secret),
                is_connected=bool(row and row.access_token),
            )
        )
    return result
