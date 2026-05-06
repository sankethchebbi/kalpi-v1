"""Core execution engine.

Responsibilities:
  1. Validate instructions (symbol, qty, side)
  2. Order them: SELLs before BUYs (frees notional capital first)
  3. For each instruction:
       - Try to fetch a real quote from the broker for the fill price
       - On failure (e.g. Kite data feed not subscribed), fall back to a
         deterministic mock price so the demo still runs
       - Write a mock Order row + update MockHolding atomically
  4. On batch completion, fire notifications (console + WS)

NO real broker order placement — per assignment scope.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.brokers.factory import get_adapter
from app.engine.notifier import notify_batch_complete
from app.models import BrokerConnection, ExecutionBatch, MockHolding, Order

logger = logging.getLogger("executor")


# --- Instruction normalization -----------------------------------------------

def _to_side(action: str) -> str:
    """REBALANCE is buy-or-sell on existing position. For the demo, we treat
    a positive REBALANCE qty as BUY (the spec says payload is explicit;
    a real system would split positive/negative). Keeping it simple."""
    a = action.upper()
    if a == "SELL":
        return "SELL"
    return "BUY"  # BUY or REBALANCE both become BUY in the order book


def _instructions_to_orders(instructions: list[dict]) -> list[dict]:
    """Sort SELLs before BUYs so capital frees up before deployment."""
    normalized = [{**i, "side": _to_side(i["action"])} for i in instructions]
    sells = [o for o in normalized if o["side"] == "SELL"]
    buys = [o for o in normalized if o["side"] == "BUY"]
    return sells + buys


# --- Pricing -----------------------------------------------------------------

def _mock_price(symbol: str) -> str:
    """Deterministic stand-in price when real quotes aren't available
    (e.g. Kite personal API without data add-on). Hash the symbol to a
    plausible NSE-equity-range float so the same symbol always 'fills'
    at the same price during a demo."""
    h = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16)
    price = 100 + (h % 4900) + ((h >> 16) % 100) / 100  # 100.00 - 4999.99-ish
    return f"{price:.2f}"


def _fetch_fill_price(adapter, symbol: str, exchange: str) -> tuple[str, bool]:
    """Try real quote, fall back to mock. Returns (price, was_real)."""
    try:
        q = adapter.get_quote(symbol, exchange)
        ltp = q.get("ltp")
        if ltp and float(ltp) > 0:
            return f"{float(ltp):.2f}", True
    except Exception as e:
        logger.warning(f"Real quote failed for {exchange}:{symbol} ({e}); using mock price")
    return _mock_price(symbol), False


# --- Holdings update ---------------------------------------------------------

def _apply_fill_to_holdings(
    db: Session, user_id: int, symbol: str, exchange: str, side: str, qty: int, price: str
) -> None:
    """Update the local mock-holdings table after a successful fill.

    BUY  -> increase qty, recompute weighted-avg cost
    SELL -> decrease qty (clamped at 0; we don't model shorts)
    """
    h = (
        db.query(MockHolding)
        .filter(
            MockHolding.user_id == user_id,
            MockHolding.symbol == symbol,
            MockHolding.exchange == exchange,
        )
        .first()
    )
    p = Decimal(price)

    if h is None:
        if side == "SELL":
            # Shorting not modeled — record sell with a stub holding at 0
            h = MockHolding(
                user_id=user_id, symbol=symbol, exchange=exchange,
                quantity=0, avg_price=str(p),
            )
            db.add(h)
            return
        h = MockHolding(
            user_id=user_id, symbol=symbol, exchange=exchange,
            quantity=qty, avg_price=str(p),
        )
        db.add(h)
        return

    current_qty = int(h.quantity or 0)
    current_avg = Decimal(h.avg_price or "0")

    if side == "BUY":
        new_qty = current_qty + qty
        if new_qty > 0:
            new_avg = ((current_avg * current_qty) + (p * qty)) / new_qty
            h.avg_price = f"{new_avg:.4f}"
        h.quantity = new_qty
    else:  # SELL
        new_qty = max(0, current_qty - qty)
        h.quantity = new_qty
        # avg_price unchanged on partial sell; kept as historical cost basis


# --- Public entry point ------------------------------------------------------

def create_batch(db: Session, user_id: int, broker_name: str, instructions: list[dict]) -> int:
    """Persist a PENDING batch + its child orders. Returns batch_id."""
    batch = ExecutionBatch(user_id=user_id, broker_name=broker_name, status="PENDING")
    db.add(batch)
    db.flush()  # get batch.id

    for inst in _instructions_to_orders(instructions):
        order = Order(
            batch_id=batch.id,
            symbol=inst["symbol"],
            exchange=inst["exchange"],
            side=inst["side"],
            quantity=inst["quantity"],
            status="PENDING",
        )
        db.add(order)

    db.commit()
    db.refresh(batch)
    return batch.id


async def run_batch(SessionFactory, user_id: int, batch_id: int) -> None:
    """Execute every PENDING order in a batch. Called as a BackgroundTask.

    A new DB session is opened here because the request-scoped session
    closes when /execute returns the 202 response.
    """
    db: Session = SessionFactory()
    try:
        batch = db.query(ExecutionBatch).filter(ExecutionBatch.id == batch_id).first()
        if not batch:
            logger.error(f"Batch {batch_id} disappeared before execution")
            return

        conn = (
            db.query(BrokerConnection)
            .filter(
                BrokerConnection.user_id == user_id,
                BrokerConnection.broker_name == batch.broker_name,
            )
            .first()
        )
        adapter = None
        if conn and conn.api_key and conn.api_secret and conn.access_token:
            try:
                adapter = get_adapter(
                    batch.broker_name, conn.api_key, conn.api_secret, conn.access_token
                )
            except Exception as e:
                logger.warning(f"Could not build adapter ({e}); using mock prices throughout")

        orders = (
            db.query(Order)
            .filter(Order.batch_id == batch_id, Order.status == "PENDING")
            .all()
        )

        for order in orders:
            try:
                if adapter is not None:
                    price, was_real = _fetch_fill_price(adapter, order.symbol, order.exchange)
                else:
                    price, was_real = _mock_price(order.symbol), False

                _apply_fill_to_holdings(
                    db, user_id, order.symbol, order.exchange,
                    order.side, order.quantity, price,
                )
                order.price = price
                order.status = "FILLED"
                order.broker_order_id = f"MOCK-{uuid.uuid4().hex[:12]}"
                if not was_real:
                    order.error_message = "filled_with_mock_price"  # informational, not a failure
                db.commit()
            except Exception as e:
                logger.exception(f"Order {order.id} failed")
                order.status = "FAILED"
                order.error_message = str(e)[:500]
                db.commit()

        # Reload after all commits to get final state
        orders = db.query(Order).filter(Order.batch_id == batch_id).all()
        filled = sum(1 for o in orders if o.status == "FILLED")
        failed = sum(1 for o in orders if o.status == "FAILED")

        batch.status = "COMPLETED" if failed == 0 else ("FAILED" if filled == 0 else "PARTIAL")
        batch.completed_at = datetime.utcnow()
        db.commit()

        summary = {
            "batch_id": batch.id,
            "broker_name": batch.broker_name,
            "status": batch.status,
            "summary": {"filled": filled, "failed": failed, "total": len(orders)},
            "orders": [
                {
                    "symbol": o.symbol, "exchange": o.exchange,
                    "side": o.side, "quantity": o.quantity,
                    "price": o.price, "status": o.status,
                    "broker_order_id": o.broker_order_id,
                    "error_message": o.error_message,
                }
                for o in orders
            ],
        }
        await notify_batch_complete(user_id, summary)
    finally:
        db.close()
