from __future__ import annotations

from sqlalchemy import JSON, Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class DelegationRow(Base):
    """One row per (delegation_id, version). Approved versions are immutable."""
    __tablename__ = "delegations"
    __table_args__ = (UniqueConstraint("delegation_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delegation_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))  # PENDING_APPROVAL | ACTIVE | SUPERSEDED | REVOKED
    total_budget_krw: Mapped[int] = mapped_column(Integer)
    per_item_max_krw: Mapped[int] = mapped_column(Integer)
    allowed_categories: Mapped[list] = mapped_column(JSON)
    allowed_merchants: Mapped[list] = mapped_column(JSON)
    require_free_returns: Mapped[bool] = mapped_column(Boolean)
    max_delivery_days: Mapped[int] = mapped_column(Integer)
    valid_for_minutes: Mapped[int] = mapped_column(Integer)
    auto_purchase_allowed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[str] = mapped_column(String(32))
    approved_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approval_surface: Mapped[str | None] = mapped_column(String(40), nullable=True)
    conditions_hash: Mapped[str] = mapped_column(String(64))


class TransactionRow(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("agent_id", "idempotency_key"),)

    transaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    delegation_id: Mapped[str] = mapped_column(String(64), index=True)
    delegation_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merchant_id: Mapped[str] = mapped_column(String(64))
    product_id: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    amount_krw: Mapped[int] = mapped_column(Integer, default=0)       # authorized total (from signed quote)
    charged_krw: Mapped[int | None] = mapped_column(Integer, nullable=True)  # merchant-reported
    status: Mapped[str] = mapped_column(String(24), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    policy_reason: Mapped[dict] = mapped_column(JSON)
    agent_claims: Mapped[dict] = mapped_column(JSON)
    rationale: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quote: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    merchant_confirmation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cancellation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    discrepancies: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class ReceiptRow(Base):
    __tablename__ = "receipts"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    receipt_id: Mapped[str] = mapped_column(String(64), unique=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    delegation_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(40))
    current_hash: Mapped[str] = mapped_column(String(64))
    body_json: Mapped[str] = mapped_column(Text)  # exact canonical JSON that was hashed and signed


class DisputeRow(Base):
    __tablename__ = "disputes"

    dispute_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(64), index=True)
    opened_by: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24))  # OPEN | CLOSED
    created_at: Mapped[str] = mapped_column(String(32))
    closed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
