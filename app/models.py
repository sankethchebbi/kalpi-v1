"""SQLAlchemy ORM models."""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    broker_connections = relationship("BrokerConnection", back_populates="user", cascade="all, delete-orphan")


class BrokerConnection(Base):
    """One row per (user, broker). Stores api_key/api_secret entered via UI,
    plus the access_token captured after OAuth-style login."""
    __tablename__ = "broker_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    broker_name = Column(String, nullable=False, index=True)  # 'zerodha', 'fyers', ...
    api_key = Column(String, nullable=True)
    api_secret = Column(String, nullable=True)
    access_token = Column(Text, nullable=True)
    connected_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="broker_connections")


class MockHolding(Base):
    """Simulated holdings — what the engine 'owns' after mock fills."""
    __tablename__ = "mock_holdings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    exchange = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    avg_price = Column(String, nullable=False, default="0")  # store as string to avoid float drift
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExecutionBatch(Base):
    """A single /execute call. One batch contains N orders."""
    __tablename__ = "execution_batches"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    broker_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="PENDING")  # PENDING, COMPLETED, FAILED
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    orders = relationship("Order", back_populates="batch", cascade="all, delete-orphan")


class Order(Base):
    """One mock order. Belongs to an ExecutionBatch."""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("execution_batches.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    side = Column(String, nullable=False)  # BUY or SELL
    quantity = Column(Integer, nullable=False)
    price = Column(String, nullable=True)  # filled price (mock = quote at fill time)
    status = Column(String, nullable=False, default="PENDING")  # PENDING, FILLED, FAILED
    broker_order_id = Column(String, nullable=True)  # synthetic for mock
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    batch = relationship("ExecutionBatch", back_populates="orders")
