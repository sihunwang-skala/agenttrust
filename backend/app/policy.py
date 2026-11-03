"""Deterministic policy evaluation. Pure function: no I/O, no LLM, no randomness."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .clock import parse_iso


@dataclass
class PolicyInput:
    delegation: dict | None          # effective delegation (ACTIVE version) or None
    delegation_problem: str | None   # violation code when delegation is unusable
    agent_id: str
    merchant_id: str
    quote: dict | None               # verified merchant quote payload; None if not found / invalid
    quote_problem: str | None
    quantity: int
    claims: dict[str, Any]
    spent_krw: int
    now: datetime
    duplicate_found: bool
    user_approved: bool = False


@dataclass
class PolicyResult:
    decision: str
    violations: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    amount_krw: int = 0

    def reason(self) -> dict:
        return {"violations": self.violations, "checks": self.checks, "engine": "deterministic/1"}


def evaluate(i: PolicyInput) -> PolicyResult:
    res = PolicyResult(decision="ALLOW")

    def check(name: str, ok: bool, code: str, msg: str, **detail: Any) -> None:
        res.checks.append({"check": name, "passed": ok})
        if not ok:
            res.violations.append({"code": code, "message": msg, **detail})

    check("delegation_valid", i.delegation_problem is None, i.delegation_problem or "", "No usable approved delegation")
    d = i.delegation
    if d is not None and i.delegation_problem is None:
        check("delegation_not_expired", i.now < parse_iso(d["expires_at"]), "DELEGATION_EXPIRED", "Delegation has expired")
        check("agent_matches", i.agent_id == d["agent_id"], "AGENT_MISMATCH", "Agent is not the delegated agent")
        check("merchant_allowed", i.merchant_id in d["allowed_merchants"], "MERCHANT_NOT_ALLOWED",
              f"Merchant {i.merchant_id} is not on the allow-list")
    check("product_found", i.quote_problem is None, i.quote_problem or "", "Product could not be verified with the merchant")
    q = i.quote
    if q is not None:
        res.amount_krw = q["unit_price_krw"] * i.quantity
        for f, qv in (("unit_price_krw", q["unit_price_krw"]), ("category", q["category"]),
                      ("free_returns", q["free_returns"]), ("delivery_days", q["delivery_days"])):
            if f in i.claims and i.claims[f] is not None:
                check(f"claim_{f}_consistent", i.claims[f] == qv, "AGENT_CLAIM_MISMATCH",
                      f"Agent claimed {f}={i.claims[f]!r} but merchant-signed quote says {qv!r}",
                      field=f, claimed=i.claims[f], verified=qv)
        if d is not None and i.delegation_problem is None:
            check("category_allowed", q["category"] in d["allowed_categories"], "CATEGORY_NOT_ALLOWED",
                  f"Category {q['category']} is not allowed")
            check("per_item_limit", q["unit_price_krw"] <= d["per_item_max_krw"], "PER_ITEM_LIMIT_EXCEEDED",
                  f"Unit price {q['unit_price_krw']} exceeds per-item max {d['per_item_max_krw']}")
            remaining = d["total_budget_krw"] - i.spent_krw
            check("budget_remaining", res.amount_krw <= remaining, "BUDGET_EXCEEDED",
                  f"Amount {res.amount_krw} exceeds remaining budget {remaining}", remaining_krw=remaining)
            check("free_returns", (not d["require_free_returns"]) or q["free_returns"], "FREE_RETURNS_REQUIRED",
                  "Free returns are required but not offered")
            check("delivery_deadline", q["delivery_days"] <= d["max_delivery_days"], "DELIVERY_TOO_SLOW",
                  f"Delivery {q['delivery_days']}d exceeds limit {d['max_delivery_days']}d")
    check("not_duplicate", not i.duplicate_found, "DUPLICATE_SUSPECTED",
          "Same agent/delegation/product/quantity was already submitted within the duplicate window")

    if res.violations:
        res.decision = "DENY"
    elif d is not None and not d["auto_purchase_allowed"] and not i.user_approved:
        res.decision = "REQUIRE_APPROVAL"
    return res
