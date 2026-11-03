"""Agent adapter interface + deterministic Mock Agent and demo scenarios.

An adapter turns a task into a gateway action request. A LangGraph agent or an MCP tool wrapper can
implement `AgentAdapter` and call the same HTTP endpoint (POST /api/v1/agent/actions); the gateway
never trusts the adapter.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from .schemas import ActionRequest, PurchaseParams


class AgentAdapter(ABC):
    agent_id: str

    @abstractmethod
    def build_action(self, task: dict, delegation_id: str) -> ActionRequest: ...


class MockAgent(AgentAdapter):
    def __init__(self, agent_id: str = "agent_demo") -> None:
        self.agent_id = agent_id

    def build_action(self, task: dict, delegation_id: str, key: str | None = None) -> ActionRequest:  # type: ignore[override]
        params = PurchaseParams(merchant_id=task["merchant_id"], product_id=task["product_id"], quantity=task.get("quantity", 1),
                                claimed=task.get("claimed", {}), rationale=task.get("rationale"))
        return ActionRequest(agent_id=self.agent_id, delegation_id=delegation_id,
                             idempotency_key=key or "sim-" + uuid.uuid4().hex[:16], parameters=params)


SCENARIOS = {
    "normal_purchase": {"title": "Normal purchase", "description": "Headphones (120,000 KRW) within every delegated limit.",
                        "task": {"merchant_id": "m_techmart", "product_id": "p_headphones", "claimed": {"unit_price_krw": 120000, "free_returns": True},
                                 "rationale": "User asked for headphones"}},
    "over_budget": {"title": "Over-budget attempt", "description": "Quantity 2 of a 190,000 KRW monitor exceeds the 300,000 KRW budget.",
                    "task": {"merchant_id": "m_techmart", "product_id": "p_monitor", "quantity": 2, "rationale": "Buy two monitors"}},
    "free_returns_violation": {"title": "Free-returns violation", "description": "Webcam without free returns while the delegation requires it.",
                               "task": {"merchant_id": "m_techmart", "product_id": "p_webcam", "rationale": "Cheapest webcam"}},
    "false_claim": {"title": "Agent makes a false claim", "description": "Agent claims free returns, the merchant-signed quote says otherwise.",
                    "task": {"merchant_id": "m_techmart", "product_id": "p_webcam", "claimed": {"free_returns": True}, "rationale": "Free returns confirmed"}},
    "duplicate_request": {"title": "Duplicate request", "description": "The same request with the same idempotency key is sent twice.",
                          "task": {"merchant_id": "m_techmart", "product_id": "p_cable", "rationale": "Cable"}},
    "merchant_mismatch": {"title": "Merchant mismatch", "description": "Merchant quotes 80,000 KRW but its signed confirmation charges 95,000 KRW.",
                          "task": {"merchant_id": "m_gadgethub", "product_id": "p_tablet", "rationale": "Tablet"}},
    "merchant_failure": {"title": "Merchant error", "description": "Merchant returns an error; no order should exist.",
                         "task": {"merchant_id": "m_techmart", "product_id": "p_flaky"}},
    "merchant_timeout": {"title": "Merchant timeout", "description": "No merchant response: outcome stays UNKNOWN.",
                         "task": {"merchant_id": "m_techmart", "product_id": "p_timeout"}},
    "unlisted_merchant": {"title": "Unlisted merchant", "description": "Merchant is not on the delegation allow-list.",
                          "task": {"merchant_id": "m_shadydeals", "product_id": "p_shady"}},
    "cancel_request": {"title": "Purchase, then cancel", "description": "Buys a cable then requests cancellation (merchant approves).",
                       "task": {"merchant_id": "m_techmart", "product_id": "p_cable", "rationale": "Cable"}, "then_cancel": True},
    "cancel_rejected": {"title": "Cancel rejected by merchant", "description": "Non-cancellable item: merchant rejects the cancellation.",
                        "task": {"merchant_id": "m_gadgethub", "product_id": "p_engraved"}, "then_cancel": True},
}
