"""Routes for kicking off an execution batch and inspecting results."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.brokers.factory import supported_brokers
from app.db import SessionLocal, get_db
from app.engine.executor import create_batch, run_batch
from app.models import ExecutionBatch, MockHolding, Order, User
from app.schemas import BatchResult, ExecuteRequest, OrderResult

router = APIRouter(tags=["execute"])


@router.post("/execute", status_code=status.HTTP_202_ACCEPTED)
def execute(
    payload: ExecuteRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kick off a batch. Returns immediately with batch_id; execution runs
    in the background and a notification fires on completion."""
    if payload.broker_name not in supported_brokers():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported broker. Supported: {supported_brokers()}",
        )

    instructions = [i.model_dump() for i in payload.instructions]
    batch_id = create_batch(db, user.id, payload.broker_name, instructions)

    # Run async — passes SessionLocal so the bg task can open its own session.
    background.add_task(run_batch, SessionLocal, user.id, batch_id)

    return {"batch_id": batch_id, "status": "PENDING"}


@router.get("/batches/{batch_id}", response_model=BatchResult)
def get_batch(
    batch_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = (
        db.query(ExecutionBatch)
        .filter(ExecutionBatch.id == batch_id, ExecutionBatch.user_id == user.id)
        .first()
    )
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    orders = db.query(Order).filter(Order.batch_id == batch_id).all()
    filled = sum(1 for o in orders if o.status == "FILLED")
    failed = sum(1 for o in orders if o.status == "FAILED")

    return BatchResult(
        batch_id=batch.id,
        broker_name=batch.broker_name,
        status=batch.status,
        summary={"filled": filled, "failed": failed, "total": len(orders)},
        orders=[
            OrderResult(
                symbol=o.symbol, exchange=o.exchange, side=o.side,
                quantity=o.quantity, price=o.price, status=o.status,
                broker_order_id=o.broker_order_id, error_message=o.error_message,
            )
            for o in orders
        ],
    )


@router.get("/mock-holdings")
def mock_holdings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the engine's local view of holdings — what we would 'own'
    after all the mock fills. This is what /execute mutates."""
    rows = (
        db.query(MockHolding)
        .filter(MockHolding.user_id == user.id)
        .order_by(MockHolding.symbol)
        .all()
    )
    return {
        "holdings": [
            {
                "symbol": r.symbol,
                "exchange": r.exchange,
                "quantity": r.quantity,
                "avg_price": r.avg_price,
            }
            for r in rows
        ]
    }
