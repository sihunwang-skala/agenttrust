from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ID = r"^[A-Za-z0-9_.:-]{1,64}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DelegationCreate(Strict):
    agent_id: str = Field(pattern=ID)
    total_budget_krw: int = Field(gt=0, le=100_000_000)
    per_item_max_krw: int = Field(gt=0, le=100_000_000)
    allowed_categories: list[str] = Field(min_length=1, max_length=20)
    allowed_merchants: list[str] = Field(min_length=1, max_length=50)
    require_free_returns: bool = True
    max_delivery_days: int = Field(default=7, ge=1, le=365)
    valid_for_minutes: int = Field(default=60, ge=1, le=43200)
    auto_purchase_allowed: bool = True


class Claims(Strict):
    unit_price_krw: int | None = Field(default=None, ge=0)
    category: str | None = Field(default=None, max_length=60)
    free_returns: bool | None = None
    delivery_days: int | None = Field(default=None, ge=0)


class PurchaseParams(Strict):
    merchant_id: str = Field(pattern=ID)
    product_id: str = Field(pattern=ID)
    quantity: int = Field(default=1, ge=1, le=100)
    claimed: Claims = Claims()
    rationale: str | None = Field(default=None, max_length=300)


class ActionRequest(Strict):
    agent_id: str = Field(pattern=ID)
    delegation_id: str = Field(pattern=ID)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    action: Literal["purchase"] = "purchase"
    parameters: PurchaseParams


class CancelRequest(Strict):
    reason: str = Field(min_length=1, max_length=300)


class RejectRequest(Strict):
    reason: str = Field(default="rejected by user", max_length=300)


class DisputeCreate(Strict):
    transaction_id: str = Field(pattern=ID)
    opened_by: Literal["USER", "AGENT_PROVIDER", "MERCHANT"] = "USER"
    reason: str = Field(min_length=1, max_length=500)


class DisputeClose(Strict):
    resolution_note: str = Field(default="closed", max_length=500)
