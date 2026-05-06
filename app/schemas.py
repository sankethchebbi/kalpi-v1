"""Pydantic request/response schemas."""
from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    email: str

    class Config:
        from_attributes = True


class BrokerCredentials(BaseModel):
    broker_name: str
    api_key: str
    api_secret: str


class BrokerConnectionStatus(BaseModel):
    broker_name: str
    has_credentials: bool
    is_connected: bool


# ---- Execution payload ----
from typing import List, Literal
from pydantic import Field, field_validator


class ExecutionInstruction(BaseModel):
    """One trade instruction in an execution batch.

    Per the spec, the engine doesn't compute deltas — the caller provides
    explicit BUY/SELL/REBALANCE instructions.
    """
    action: Literal["BUY", "SELL", "REBALANCE"]
    symbol: str
    exchange: str = "NSE"
    quantity: int = Field(gt=0)

    @field_validator("symbol")
    @classmethod
    def _upper_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("exchange")
    @classmethod
    def _upper_exchange(cls, v: str) -> str:
        return v.strip().upper()


class ExecuteRequest(BaseModel):
    broker_name: str
    instructions: List[ExecutionInstruction] = Field(min_length=1)


class OrderResult(BaseModel):
    symbol: str
    exchange: str
    side: str
    quantity: int
    price: str | None = None
    status: str
    broker_order_id: str | None = None
    error_message: str | None = None


class BatchResult(BaseModel):
    batch_id: int
    broker_name: str
    status: str
    summary: dict  # {filled: N, failed: N, total: N}
    orders: List[OrderResult]
