"""Action Receipt Engine: canonical JSON + SHA-256 hash chain + Ed25519 signature."""
from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .clock import Clock, iso
from .crypto import GENESIS_HASH, Signer, canonical_json, digest_of, verify_sig
from .models import ReceiptRow

SCHEMA_VERSION = "agenttrust.receipt/1"
# PAYMENT_CONFIRMED is intentionally absent: no payment provider is integrated in this MVP.
VERIFICATION_LEVELS = ("UNKNOWN", "SELF_REPORTED", "GATEWAY_VERIFIED", "MERCHANT_CONFIRMED")
_RANK = {lvl: i for i, lvl in enumerate(VERIFICATION_LEVELS)}


def best_level(levels: list[str]) -> str:
    return max(levels, key=_RANK.get, default="UNKNOWN")  # type: ignore[arg-type]


def evidence(source: str, kind: str, summary: str, data: Any = None) -> dict:
    if source not in VERIFICATION_LEVELS:
        raise ValueError(f"invalid evidence level {source}")
    return {"evidence_id": "ev_" + uuid.uuid4().hex[:10], "level": source, "type": kind, "summary": summary,
            "digest": digest_of(data) if data is not None else None}


def append_receipt(db: Session, signer: Signer, clock: Clock, *, event_type: str, agent_id: str, delegation_id: str | None,
                   delegation_version: int | None, requested_action: str, action_parameters: dict, policy_decision: str,
                   policy_reason: dict, evidence_references: list[dict], merchant_response: dict | None,
                   execution_status: str, transaction_id: str | None) -> dict:
    """Must run inside the caller's write transaction (BEGIN IMMEDIATE) so the chain cannot fork."""
    last = db.execute(select(ReceiptRow).order_by(ReceiptRow.seq.desc()).limit(1)).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    previous_hash = last.current_hash if last else GENESIS_HASH
    body = {
        "schema_version": SCHEMA_VERSION, "receipt_id": "r_" + uuid.uuid4().hex[:16], "seq": seq,
        "transaction_id": transaction_id, "timestamp": iso(clock.now()), "event_type": event_type, "agent_id": agent_id,
        "delegation_id": delegation_id, "delegation_version": delegation_version, "requested_action": requested_action,
        "action_parameters": action_parameters, "policy_decision": policy_decision, "policy_reason": policy_reason,
        "evidence_references": evidence_references, "merchant_response": merchant_response,
        "execution_status": execution_status,
        "verification_level": best_level([e["level"] for e in evidence_references]),
        "signer_key_id": signer.key_id, "previous_hash": previous_hash,
    }
    body["current_hash"] = digest_of(body)
    body["signature"] = signer.sign_hex(body["current_hash"])
    db.add(ReceiptRow(seq=seq, receipt_id=body["receipt_id"], transaction_id=transaction_id, delegation_id=delegation_id,
                      event_type=event_type, current_hash=body["current_hash"], body_json=canonical_json(body)))
    db.flush()
    return body


def load(row: ReceiptRow) -> dict:
    return json.loads(row.body_json)


def check_receipt(r: dict, public_hex: str) -> dict:
    core = {k: v for k, v in r.items() if k not in ("current_hash", "signature")}
    hash_ok = digest_of(core) == r.get("current_hash")
    sig_ok = hash_ok and verify_sig(public_hex, r["current_hash"], r.get("signature", ""))
    return {"hash_valid": hash_ok, "signature_valid": sig_ok}


def check_chain(receipts: list[dict], public_hex: str) -> dict:
    problems: list[dict] = []
    prev_hash, prev_seq = GENESIS_HASH, 0
    for r in receipts:
        c = check_receipt(r, public_hex)
        if not c["hash_valid"]:
            problems.append({"seq": r.get("seq"), "problem": "HASH_MISMATCH"})
        elif not c["signature_valid"]:
            problems.append({"seq": r.get("seq"), "problem": "BAD_SIGNATURE"})
        if r.get("previous_hash") != prev_hash:
            problems.append({"seq": r.get("seq"), "problem": "BROKEN_CHAIN_LINK"})
        if r.get("seq") != prev_seq + 1:
            problems.append({"seq": r.get("seq"), "problem": "SEQUENCE_GAP"})
        prev_hash, prev_seq = r.get("current_hash"), r.get("seq", prev_seq)
    return {"valid": not problems, "receipt_count": len(receipts), "problems": problems}
