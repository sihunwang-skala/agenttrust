"""Mock Merchant: SIMULATED merchant with its own Ed25519 key. No real commerce or payment.

Fault injection is controlled by the `behavior` field of synthetic catalog entries.
"""
from __future__ import annotations

import uuid
from typing import Any

from .clock import Clock, iso
from .crypto import Signer, digest_of, verify_sig


class MerchantUnavailable(Exception):
    """Merchant returned an error (HTTP 5xx-like)."""


class MerchantTimeout(Exception):
    """No response from merchant: outcome of the order is unknown."""


def _p(pid, merchant, name, cat, price, free_returns, days, cancellable=True, behavior="NORMAL"):
    return {"product_id": pid, "merchant_id": merchant, "name": name, "category": cat, "unit_price_krw": price,
            "free_returns": free_returns, "delivery_days": days, "cancellable": cancellable, "behavior": behavior}


CATALOG: list[dict[str, Any]] = [  # all synthetic
    _p("p_headphones", "m_techmart", "Wireless Headphones (synthetic)", "Electronics", 120000, True, 3),
    _p("p_monitor", "m_techmart", "27in Monitor (synthetic)", "Electronics", 190000, True, 4),
    _p("p_cable", "m_techmart", "USB-C Cable (synthetic)", "Electronics", 15000, True, 2),
    _p("p_webcam", "m_techmart", "Webcam, no free returns (synthetic)", "Electronics", 59000, False, 3),
    _p("p_slowdock", "m_gadgethub", "Docking Station, slow ship (synthetic)", "Electronics", 80000, True, 21),
    _p("p_laptop", "m_gadgethub", "Laptop (synthetic)", "Electronics", 1450000, True, 5),
    _p("p_sofa", "m_techmart", "Sofa (synthetic)", "Furniture", 180000, True, 7),
    _p("p_tablet", "m_gadgethub", "Tablet, merchant overcharges (synthetic)", "Electronics", 80000, True, 3, behavior="PRICE_MISMATCH"),
    _p("p_engraved", "m_gadgethub", "Engraved Speaker, non-cancellable (synthetic)", "Electronics", 70000, True, 5, cancellable=False),
    _p("p_flaky", "m_techmart", "Flaky Item, merchant errors (synthetic)", "Electronics", 30000, True, 3, behavior="ERROR"),
    _p("p_timeout", "m_techmart", "Timeout Item, no response (synthetic)", "Electronics", 40000, True, 3, behavior="TIMEOUT"),
    _p("p_shady", "m_shadydeals", "Gadget from unlisted merchant (synthetic)", "Electronics", 20000, True, 3),
]
MERCHANTS = {"m_techmart": "TechMart (simulated)", "m_gadgethub": "GadgetHub (simulated)", "m_shadydeals": "ShadyDeals (simulated)"}
PUBLIC_FIELDS = ("product_id", "merchant_id", "name", "category", "unit_price_krw", "free_returns", "delivery_days", "cancellable")


class MockMerchant:
    def __init__(self, signer: Signer, clock: Clock) -> None:
        self.signer = signer
        self.clock = clock
        self._catalog = {p["product_id"]: p for p in CATALOG}
        self._orders: dict[str, dict] = {}

    def _sign(self, payload: dict) -> dict:
        payload = {**payload, "simulation": True, "issued_at": iso(self.clock.now())}
        d = digest_of(payload)
        return {"payload": payload, "payload_digest": d, "signature": self.signer.sign_hex(d), "key_id": self.signer.key_id}

    def public_catalog(self) -> list[dict]:
        return [{k: p[k] for k in PUBLIC_FIELDS} for p in self._catalog.values()]

    def quote(self, merchant_id: str, product_id: str) -> dict:
        p = self._catalog.get(product_id)
        if p is None or p["merchant_id"] != merchant_id:
            return self._sign({"type": "quote_not_found", "merchant_id": merchant_id, "product_id": product_id})
        return self._sign({"type": "quote", "quote_id": "q_" + uuid.uuid4().hex[:12], **{k: p[k] for k in PUBLIC_FIELDS}})

    def execute(self, quote: dict, transaction_ref: str, quantity: int) -> dict:
        p = self._catalog[quote["product_id"]]
        if p["behavior"] == "TIMEOUT":
            raise MerchantTimeout("merchant did not respond")
        if p["behavior"] == "ERROR":
            raise MerchantUnavailable("merchant returned 503")
        charged = p["unit_price_krw"] * quantity
        if p["behavior"] == "PRICE_MISMATCH":
            charged += 15000 * quantity
        order_id = "o_" + uuid.uuid4().hex[:12]
        signed = self._sign({"type": "order_confirmation", "order_id": order_id, "transaction_ref": transaction_ref,
                             "merchant_id": p["merchant_id"], "product_id": p["product_id"], "quantity": quantity,
                             "charged_krw": charged, "status": "CONFIRMED"})
        self._orders[order_id] = {"product_id": p["product_id"], "cancelled": False}
        return signed

    def cancel(self, order_id: str, product_id: str) -> dict:
        p = self._catalog[product_id]
        if not p["cancellable"]:
            return self._sign({"type": "cancellation", "order_id": order_id, "status": "CANCEL_REJECTED",
                               "reason_code": "ITEM_NON_CANCELLABLE"})
        self._orders.setdefault(order_id, {"product_id": product_id})["cancelled"] = True
        return self._sign({"type": "cancellation", "order_id": order_id, "status": "CANCEL_APPROVED", "reason_code": "OK"})

    def verify(self, signed: dict) -> bool:
        return bool(signed) and signed.get("payload_digest") == digest_of(signed["payload"]) and verify_sig(
            self.signer.public_hex, signed["payload_digest"], signed["signature"])
