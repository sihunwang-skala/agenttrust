"""Gateway services: delegations, action submission, execution, cancellation, disputes.

Every state-changing operation runs in a SQLite BEGIN IMMEDIATE transaction (see db.py), so the
policy check, budget reservation and receipt-chain append are atomic and serialized.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .clock import iso, parse_iso
from .crypto import digest_of
from .errors import AppError
from .masking import scrub_text
from .merchant import MerchantTimeout, MerchantUnavailable
from .models import DelegationRow, DisputeRow, ReceiptRow, TransactionRow
from .policy import PolicyInput, evaluate
from .receipts import append_receipt, evidence
from .runtime import Runtime
from .schemas import ActionRequest, DelegationCreate

DEMO_USER = "demo-user"
APPROVAL_SURFACE = "DEMO_TRUSTED_SURFACE"
COMMITTED = ("AUTHORIZED", "EXECUTED", "DISCREPANCY", "UNKNOWN")  # statuses that consume budget
APPROVAL_NOTE = ("Approved on the Demo Trusted Surface. This is NOT a cryptographic signature by the user; "
                 "user identity and intent are not proven.")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------- delegations
def _conditions(r: DelegationRow) -> dict:
    return {"agent_id": r.agent_id, "total_budget_krw": r.total_budget_krw, "per_item_max_krw": r.per_item_max_krw,
            "allowed_categories": sorted(r.allowed_categories), "allowed_merchants": sorted(r.allowed_merchants),
            "require_free_returns": r.require_free_returns, "max_delivery_days": r.max_delivery_days,
            "valid_for_minutes": r.valid_for_minutes, "auto_purchase_allowed": r.auto_purchase_allowed}


def spent_krw(db: Session, delegation_id: str) -> int:
    rows = db.execute(select(TransactionRow).where(TransactionRow.delegation_id == delegation_id,
                                                   TransactionRow.status.in_(COMMITTED))).scalars()
    return sum(max(t.amount_krw, t.charged_krw or 0) for t in rows)


def delegation_view(rt: Runtime, db: Session, r: DelegationRow) -> dict:
    status = r.status
    if status == "ACTIVE" and r.expires_at and rt.clock.now() >= parse_iso(r.expires_at):
        status = "EXPIRED"
    spent = spent_krw(db, r.delegation_id)
    return {"delegation_id": r.delegation_id, "version": r.version, "status": status, "user_id": r.user_id,
            **_conditions(r), "created_at": r.created_at, "approved_at": r.approved_at, "expires_at": r.expires_at,
            "revoked_at": r.revoked_at, "approval_surface": r.approval_surface, "conditions_hash": r.conditions_hash,
            "spent_krw": spent, "remaining_krw": r.total_budget_krw - spent,
            "approval_note": APPROVAL_NOTE if r.approval_surface else None}


def _versions(db: Session, delegation_id: str) -> list[DelegationRow]:
    return list(db.execute(select(DelegationRow).where(DelegationRow.delegation_id == delegation_id)
                           .order_by(DelegationRow.version.desc())).scalars())


def _new_version(rt: Runtime, db: Session, delegation_id: str, version: int, req: DelegationCreate) -> DelegationRow:
    if req.per_item_max_krw > req.total_budget_krw:
        raise AppError(422, "VALIDATION_ERROR", "per_item_max_krw cannot exceed total_budget_krw")
    row = DelegationRow(delegation_id=delegation_id, version=version, user_id=DEMO_USER, agent_id=req.agent_id,
                        status="PENDING_APPROVAL", total_budget_krw=req.total_budget_krw,
                        per_item_max_krw=req.per_item_max_krw, allowed_categories=req.allowed_categories,
                        allowed_merchants=req.allowed_merchants, require_free_returns=req.require_free_returns,
                        max_delivery_days=req.max_delivery_days, valid_for_minutes=req.valid_for_minutes,
                        auto_purchase_allowed=req.auto_purchase_allowed, created_at=iso(rt.clock.now()),
                        conditions_hash="")
    row.conditions_hash = digest_of(_conditions(row))
    db.add(row)
    return row


def create_delegation(rt: Runtime, db: Session, req: DelegationCreate) -> dict:
    row = _new_version(rt, db, new_id("dlg"), 1, req)
    db.commit()
    return delegation_view(rt, db, row)


def revise_delegation(rt: Runtime, db: Session, delegation_id: str, req: DelegationCreate) -> dict:
    rows = _versions(db, delegation_id)
    if not rows:
        raise AppError(404, "DELEGATION_NOT_FOUND", "Delegation not found")
    if any(r.status == "REVOKED" for r in rows):
        raise AppError(409, "DELEGATION_REVOKED", "A revoked delegation cannot be revised; create a new one")
    for r in rows:
        if r.status == "PENDING_APPROVAL":
            r.status = "SUPERSEDED"
    row = _new_version(rt, db, delegation_id, rows[0].version + 1, req)
    db.commit()
    return delegation_view(rt, db, row)


def approve_delegation(rt: Runtime, db: Session, delegation_id: str) -> dict:
    rows = _versions(db, delegation_id)
    if not rows:
        raise AppError(404, "DELEGATION_NOT_FOUND", "Delegation not found")
    pending = next((r for r in rows if r.status == "PENDING_APPROVAL"), None)
    if pending is None:
        raise AppError(409, "NOTHING_TO_APPROVE", "No version is pending approval")
    now = rt.clock.now()
    for r in rows:
        if r.status == "ACTIVE":
            r.status = "SUPERSEDED"
    pending.status, pending.approved_at = "ACTIVE", iso(now)
    pending.expires_at = iso(now + timedelta(minutes=pending.valid_for_minutes))
    pending.approval_surface = APPROVAL_SURFACE
    append_receipt(db, rt.signer, rt.clock, event_type="DELEGATION_APPROVED", agent_id=pending.agent_id,
                   delegation_id=delegation_id, delegation_version=pending.version, requested_action="delegation.approve",
                   action_parameters=_conditions(pending), policy_decision="ALLOW",
                   policy_reason={"note": APPROVAL_NOTE, "expires_at": pending.expires_at},
                   evidence_references=[evidence("GATEWAY_VERIFIED", "delegation_approval",
                                                 "Approval recorded by gateway on Demo Trusted Surface (unsigned by user)",
                                                 {"conditions_hash": pending.conditions_hash})],
                   merchant_response=None, execution_status="DELEGATION_ACTIVE", transaction_id=None)
    db.commit()
    return delegation_view(rt, db, pending)


def revoke_delegation(rt: Runtime, db: Session, delegation_id: str) -> dict:
    rows = _versions(db, delegation_id)
    if not rows:
        raise AppError(404, "DELEGATION_NOT_FOUND", "Delegation not found")
    live = [r for r in rows if r.status in ("ACTIVE", "PENDING_APPROVAL")]
    if not live:
        raise AppError(409, "NOT_REVOCABLE", "Delegation has no active or pending version")
    now = iso(rt.clock.now())
    for r in live:
        r.status, r.revoked_at = "REVOKED", now
    append_receipt(db, rt.signer, rt.clock, event_type="DELEGATION_REVOKED", agent_id=live[0].agent_id,
                   delegation_id=delegation_id, delegation_version=live[0].version, requested_action="delegation.revoke",
                   action_parameters={}, policy_decision="ALLOW", policy_reason={"note": "revoked on Demo Trusted Surface"},
                   evidence_references=[evidence("GATEWAY_VERIFIED", "delegation_revocation", "Revocation recorded by gateway")],
                   merchant_response=None, execution_status="DELEGATION_REVOKED", transaction_id=None)
    db.commit()
    return delegation_view(rt, db, live[0])


def resolve_delegation(db: Session, delegation_id: str) -> tuple[DelegationRow | None, str | None, int | None]:
    rows = _versions(db, delegation_id)
    if not rows:
        return None, "DELEGATION_NOT_FOUND", None
    active = next((r for r in rows if r.status == "ACTIVE"), None)
    if active:
        return active, None, active.version
    if any(r.status == "REVOKED" for r in rows):
        return None, "DELEGATION_REVOKED", rows[0].version
    return None, "DELEGATION_NOT_APPROVED", rows[0].version


# ---------------------------------------------------------------- actions
def tx_view(db: Session, t: TransactionRow, **extra) -> dict:
    ids = [r for r in db.execute(select(ReceiptRow.receipt_id).where(ReceiptRow.transaction_id == t.transaction_id)
                                 .order_by(ReceiptRow.seq)).scalars()]
    return {"transaction_id": t.transaction_id, "agent_id": t.agent_id, "delegation_id": t.delegation_id,
            "delegation_version": t.delegation_version, "merchant_id": t.merchant_id, "product_id": t.product_id,
            "quantity": t.quantity, "amount_krw": t.amount_krw, "charged_krw": t.charged_krw, "status": t.status,
            "decision": t.decision, "policy_reason": t.policy_reason, "agent_claims": t.agent_claims,
            "rationale": t.rationale, "discrepancies": t.discrepancies, "cancellation": t.cancellation,
            "created_at": t.created_at, "updated_at": t.updated_at, "receipt_ids": ids,
            "simulation": True, **extra}


def _evaluate(rt: Runtime, db: Session, *, agent_id: str, delegation_id: str, merchant_id: str, product_id: str,
              quantity: int, claims: dict, user_approved: bool, exclude_tx: str | None):
    d_row, problem, d_version = resolve_delegation(db, delegation_id)
    signed_quote = rt.merchant.quote(merchant_id, product_id)
    quote, quote_problem = None, None
    if not rt.merchant.verify(signed_quote):
        quote_problem = "QUOTE_SIGNATURE_INVALID"
    elif signed_quote["payload"]["type"] != "quote":
        quote_problem = "PRODUCT_NOT_FOUND"
    else:
        quote = signed_quote["payload"]
    now = rt.clock.now()
    cutoff = now - timedelta(seconds=rt.settings.duplicate_window_seconds)
    cands = db.execute(select(TransactionRow).where(
        TransactionRow.agent_id == agent_id, TransactionRow.delegation_id == delegation_id,
        TransactionRow.merchant_id == merchant_id, TransactionRow.product_id == product_id,
        TransactionRow.quantity == quantity,
        TransactionRow.status.in_(COMMITTED + ("PENDING_APPROVAL",)))).scalars()
    dup = any(c.transaction_id != exclude_tx and parse_iso(c.created_at) >= cutoff for c in cands)
    d = None
    if d_row is not None:
        d = {**_conditions(d_row), "expires_at": d_row.expires_at}
    res = evaluate(PolicyInput(delegation=d, delegation_problem=problem, agent_id=agent_id, merchant_id=merchant_id,
                               quote=quote, quote_problem=quote_problem, quantity=quantity, claims=claims,
                               spent_krw=spent_krw(db, delegation_id), now=now, duplicate_found=dup,
                               user_approved=user_approved))
    return res, signed_quote, d_row, d_version


def _policy_evidence(claims: dict, rationale, res, d_row, signed_quote) -> list[dict]:
    ev = [evidence("SELF_REPORTED", "agent_claims", "Agent-supplied claims and rationale (unverified)",
                   {"claims": claims, "rationale": rationale}),
          evidence("GATEWAY_VERIFIED", "policy_evaluation", "Deterministic policy checks executed by the gateway",
                   res.checks)]
    if d_row is not None:
        ev.append(evidence("GATEWAY_VERIFIED", "delegation_snapshot", f"Delegation v{d_row.version} loaded from gateway store",
                           {"conditions_hash": d_row.conditions_hash}))
    if signed_quote["payload"]["type"] == "quote" and signed_quote.get("payload_digest"):
        ev.append(evidence("MERCHANT_CONFIRMED", "merchant_quote",
                           "Merchant-signed quote verified by gateway (SIMULATED merchant)", signed_quote["payload"]))
    return ev


def submit_action(rt: Runtime, req: ActionRequest, idempotency_key: str) -> dict:
    p = req.parameters
    claims = p.claimed.model_dump()
    rationale = scrub_text(p.rationale)
    request_hash = digest_of({"agent_id": req.agent_id, "delegation_id": req.delegation_id, "action": req.action,
                              "merchant_id": p.merchant_id, "product_id": p.product_id, "quantity": p.quantity,
                              "claimed": claims})
    with rt.sessions() as db:
        existing = db.execute(select(TransactionRow).where(TransactionRow.agent_id == req.agent_id,
                                                           TransactionRow.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency key was used with a different request")
            return tx_view(db, existing, replayed=True)
        res, signed_quote, d_row, d_version = _evaluate(
            rt, db, agent_id=req.agent_id, delegation_id=req.delegation_id, merchant_id=p.merchant_id,
            product_id=p.product_id, quantity=p.quantity, claims=claims, user_approved=False, exclude_tx=None)
        status = {"ALLOW": "AUTHORIZED", "DENY": "DENIED", "REQUIRE_APPROVAL": "PENDING_APPROVAL"}[res.decision]
        now = iso(rt.clock.now())
        tx = TransactionRow(transaction_id=new_id("tx"), agent_id=req.agent_id, idempotency_key=idempotency_key,
                            request_hash=request_hash, delegation_id=req.delegation_id, delegation_version=d_version,
                            merchant_id=p.merchant_id, product_id=p.product_id, quantity=p.quantity,
                            amount_krw=res.amount_krw, status=status, decision=res.decision,
                            policy_reason=res.reason(), agent_claims=claims, rationale=rationale,
                            quote=signed_quote if signed_quote["payload"]["type"] == "quote" else None,
                            discrepancies=[], created_at=now, updated_at=now)
        db.add(tx)
        append_receipt(db, rt.signer, rt.clock, event_type="POLICY_DECISION", agent_id=req.agent_id,
                       delegation_id=req.delegation_id, delegation_version=d_version, requested_action=req.action,
                       action_parameters={"merchant_id": p.merchant_id, "product_id": p.product_id,
                                          "quantity": p.quantity, "claimed": claims, "rationale": rationale},
                       policy_decision=res.decision, policy_reason=res.reason(),
                       evidence_references=_policy_evidence(claims, rationale, res, d_row, signed_quote),
                       merchant_response=signed_quote, execution_status=status, transaction_id=tx.transaction_id)
        db.commit()
        tx_id = tx.transaction_id
    if status == "AUTHORIZED":
        execute_authorized(rt, tx_id)
    with rt.sessions() as db:
        return tx_view(db, db.get(TransactionRow, tx_id), replayed=False)


def execute_authorized(rt: Runtime, tx_id: str) -> None:
    """Phase 2: call merchant, record the outcome. Budget stays reserved until the outcome is known."""
    with rt.sessions() as db:
        tx = db.get(TransactionRow, tx_id)
        if tx is None or tx.status != "AUTHORIZED":
            return
        quote = tx.quote["payload"]
        merchant_response, ev, new_status, exec_status, discrepancies = None, [], "UNKNOWN", "NO_MERCHANT_RESPONSE", []
        try:
            signed = rt.merchant.execute(quote, tx.transaction_id, tx.quantity)
            merchant_response = signed
            if not rt.merchant.verify(signed):
                ev = [evidence("UNKNOWN", "merchant_response_invalid", "Merchant response signature did not verify")]
                exec_status = "INVALID_MERCHANT_SIGNATURE"
            else:
                o = signed["payload"]
                tx.charged_krw = o["charged_krw"]
                tx.merchant_confirmation = signed
                for f, exp, obs in (("charged_krw", tx.amount_krw, o["charged_krw"]), ("product_id", tx.product_id, o["product_id"]),
                                    ("merchant_id", tx.merchant_id, o["merchant_id"]), ("quantity", tx.quantity, o["quantity"]),
                                    ("transaction_ref", tx.transaction_id, o["transaction_ref"])):
                    if exp != obs:
                        discrepancies.append({"stage": "MERCHANT_EXECUTION", "field": f, "expected": exp, "observed": obs,
                                              "expected_source": "MERCHANT_CONFIRMED (signed quote)",
                                              "observed_source": "MERCHANT_CONFIRMED (signed order confirmation)"})
                new_status = "DISCREPANCY" if discrepancies else "EXECUTED"
                exec_status = "EXECUTED_WITH_DISCREPANCY" if discrepancies else "EXECUTED"
                ev = [evidence("MERCHANT_CONFIRMED", "merchant_order_confirmation",
                               "Merchant-signed order confirmation (SIMULATED; not a payment confirmation)", o)]
        except MerchantUnavailable as e:
            new_status, exec_status = "FAILED", "MERCHANT_ERROR"
            ev = [evidence("GATEWAY_VERIFIED", "merchant_error", f"Merchant call failed: {e}. No order confirmation received.")]
        except MerchantTimeout as e:
            ev = [evidence("UNKNOWN", "merchant_timeout", f"{e}; the order outcome is unknown")]
        tx.status, tx.discrepancies, tx.updated_at = new_status, discrepancies, iso(rt.clock.now())
        append_receipt(db, rt.signer, rt.clock, event_type="EXECUTION_RESULT", agent_id=tx.agent_id,
                       delegation_id=tx.delegation_id, delegation_version=tx.delegation_version, requested_action="purchase",
                       action_parameters={"merchant_id": tx.merchant_id, "product_id": tx.product_id, "quantity": tx.quantity},
                       policy_decision="ALLOW", policy_reason={"discrepancies": discrepancies}, evidence_references=ev,
                       merchant_response=merchant_response, execution_status=exec_status, transaction_id=tx.transaction_id)
        db.commit()


def _get_tx(db: Session, tx_id: str) -> TransactionRow:
    tx = db.get(TransactionRow, tx_id)
    if tx is None:
        raise AppError(404, "TRANSACTION_NOT_FOUND", "Transaction not found")
    return tx


def approve_transaction(rt: Runtime, tx_id: str) -> dict:
    with rt.sessions() as db:
        tx = _get_tx(db, tx_id)
        if tx.status != "PENDING_APPROVAL":
            raise AppError(409, "NOT_PENDING_APPROVAL", f"Transaction is {tx.status}")
        res, signed_quote, d_row, d_version = _evaluate(
            rt, db, agent_id=tx.agent_id, delegation_id=tx.delegation_id, merchant_id=tx.merchant_id,
            product_id=tx.product_id, quantity=tx.quantity, claims=tx.agent_claims, user_approved=True, exclude_tx=tx.transaction_id)
        tx.decision = res.decision
        tx.status = "AUTHORIZED" if res.decision == "ALLOW" else "DENIED"
        tx.amount_krw, tx.policy_reason, tx.delegation_version = res.amount_krw, res.reason(), d_version
        tx.quote = signed_quote if signed_quote["payload"]["type"] == "quote" else tx.quote
        tx.updated_at = iso(rt.clock.now())
        ev = _policy_evidence(tx.agent_claims, tx.rationale, res, d_row, signed_quote)
        ev.append(evidence("GATEWAY_VERIFIED", "user_approval", "Per-action approval on Demo Trusted Surface (unsigned by user)"))
        append_receipt(db, rt.signer, rt.clock, event_type="USER_APPROVAL", agent_id=tx.agent_id, delegation_id=tx.delegation_id,
                       delegation_version=d_version, requested_action="purchase",
                       action_parameters={"merchant_id": tx.merchant_id, "product_id": tx.product_id, "quantity": tx.quantity},
                       policy_decision=res.decision, policy_reason=res.reason(), evidence_references=ev,
                       merchant_response=signed_quote, execution_status=tx.status, transaction_id=tx.transaction_id)
        db.commit()
        authorized = tx.status == "AUTHORIZED"
    if authorized:
        execute_authorized(rt, tx_id)
    with rt.sessions() as db:
        return tx_view(db, _get_tx(db, tx_id))


def reject_transaction(rt: Runtime, tx_id: str, reason: str) -> dict:
    with rt.sessions() as db:
        tx = _get_tx(db, tx_id)
        if tx.status != "PENDING_APPROVAL":
            raise AppError(409, "NOT_PENDING_APPROVAL", f"Transaction is {tx.status}")
        tx.status, tx.decision, tx.updated_at = "REJECTED", "DENY", iso(rt.clock.now())
        append_receipt(db, rt.signer, rt.clock, event_type="USER_REJECTION", agent_id=tx.agent_id, delegation_id=tx.delegation_id,
                       delegation_version=tx.delegation_version, requested_action="purchase",
                       action_parameters={"product_id": tx.product_id}, policy_decision="DENY",
                       policy_reason={"note": scrub_text(reason)},
                       evidence_references=[evidence("GATEWAY_VERIFIED", "user_rejection", "Rejected on Demo Trusted Surface")],
                       merchant_response=None, execution_status="REJECTED", transaction_id=tx.transaction_id)
        db.commit()
        return tx_view(db, tx)


def cancel_transaction(rt: Runtime, tx_id: str, reason: str) -> dict:
    reason = scrub_text(reason) or ""
    with rt.sessions() as db:
        tx = _get_tx(db, tx_id)
        if tx.status not in ("EXECUTED", "DISCREPANCY"):
            raise AppError(409, "NOT_CANCELLABLE", f"Transaction in status {tx.status} has no merchant-confirmed order to cancel",
                           {"status": tx.status})
        order_id = tx.merchant_confirmation["payload"]["order_id"]
        base = dict(agent_id=tx.agent_id, delegation_id=tx.delegation_id, delegation_version=tx.delegation_version,
                    transaction_id=tx.transaction_id)
        append_receipt(db, rt.signer, rt.clock, event_type="CANCEL_REQUESTED", requested_action="cancel",
                       action_parameters={"order_id": order_id, "reason": reason}, policy_decision="ALLOW",
                       policy_reason={"note": "user cancellation request"},
                       evidence_references=[evidence("SELF_REPORTED", "cancel_reason", "User-stated reason (unverified)", reason)],
                       merchant_response=None, execution_status="CANCEL_REQUESTED", **base)
        signed = rt.merchant.cancel(order_id, tx.product_id)
        valid = rt.merchant.verify(signed)
        approved = valid and signed["payload"]["status"] == "CANCEL_APPROVED"
        event = "CANCEL_APPROVED" if approved else "CANCEL_REJECTED"
        append_receipt(db, rt.signer, rt.clock, event_type=event, requested_action="cancel",
                       action_parameters={"order_id": order_id}, policy_decision="ALLOW",
                       policy_reason={"merchant_reason_code": signed["payload"].get("reason_code")},
                       evidence_references=[evidence("MERCHANT_CONFIRMED" if valid else "UNKNOWN", "merchant_cancellation",
                                                     "Merchant-signed cancellation response (SIMULATED)", signed["payload"])],
                       merchant_response=signed, execution_status=event, **base)
        tx.cancellation = {"result": event, "reason_code": signed["payload"].get("reason_code"), "reason": reason}
        if approved:
            prev, tx.status = tx.status, "CANCELLED"
            append_receipt(db, rt.signer, rt.clock, event_type="TRANSACTION_STATE_CHANGED", requested_action="state_change",
                           action_parameters={"from": prev, "to": "CANCELLED"}, policy_decision="ALLOW", policy_reason={},
                           evidence_references=[evidence("GATEWAY_VERIFIED", "state_change", f"{prev} -> CANCELLED after merchant approval")],
                           merchant_response=None, execution_status="CANCELLED", **base)
        tx.updated_at = iso(rt.clock.now())
        db.commit()
        return tx_view(db, tx, cancellation_outcome=event)


# ---------------------------------------------------------------- disputes
def dispute_view(d: DisputeRow) -> dict:
    return {c.name: getattr(d, c.name) for c in DisputeRow.__table__.columns} | {"simulation": True}


def open_dispute(rt: Runtime, tx_id: str, opened_by: str, reason: str) -> dict:
    with rt.sessions() as db:
        tx = _get_tx(db, tx_id)
        if db.execute(select(DisputeRow).where(DisputeRow.transaction_id == tx_id, DisputeRow.status == "OPEN")).first():
            raise AppError(409, "DISPUTE_ALREADY_OPEN", "An open dispute already exists for this transaction")
        d = DisputeRow(dispute_id=new_id("dsp"), transaction_id=tx_id, opened_by=opened_by, reason=scrub_text(reason, 500) or "",
                       status="OPEN", created_at=iso(rt.clock.now()))
        db.add(d)
        append_receipt(db, rt.signer, rt.clock, event_type="DISPUTE_OPENED", agent_id=tx.agent_id, delegation_id=tx.delegation_id,
                       delegation_version=tx.delegation_version, requested_action="dispute.open",
                       action_parameters={"dispute_id": d.dispute_id, "opened_by": opened_by, "reason": d.reason},
                       policy_decision="ALLOW", policy_reason={},
                       evidence_references=[evidence("SELF_REPORTED", "dispute_claim", f"Claim by {opened_by} (unverified)", d.reason)],
                       merchant_response=None, execution_status="DISPUTE_OPEN", transaction_id=tx_id)
        db.commit()
        return dispute_view(d)


def get_dispute(db: Session, dispute_id: str) -> DisputeRow:
    d = db.get(DisputeRow, dispute_id)
    if d is None:
        raise AppError(404, "DISPUTE_NOT_FOUND", "Dispute not found")
    return d


def close_dispute(rt: Runtime, dispute_id: str, note: str) -> dict:
    with rt.sessions() as db:
        d = get_dispute(db, dispute_id)
        if d.status != "OPEN":
            raise AppError(409, "DISPUTE_NOT_OPEN", "Dispute is already closed")
        tx = _get_tx(db, d.transaction_id)
        d.status, d.closed_at, d.resolution_note = "CLOSED", iso(rt.clock.now()), scrub_text(note, 500)
        append_receipt(db, rt.signer, rt.clock, event_type="DISPUTE_CLOSED", agent_id=tx.agent_id, delegation_id=tx.delegation_id,
                       delegation_version=tx.delegation_version, requested_action="dispute.close",
                       action_parameters={"dispute_id": dispute_id, "note": d.resolution_note}, policy_decision="ALLOW",
                       policy_reason={"note": "closure does not assign responsibility"},
                       evidence_references=[evidence("GATEWAY_VERIFIED", "dispute_closed", "Dispute closed on Demo Trusted Surface")],
                       merchant_response=None, execution_status="DISPUTE_CLOSED", transaction_id=tx.transaction_id)
        db.commit()
        return dispute_view(d)


def dashboard(rt: Runtime, db: Session) -> dict:
    def count(*conds):
        return db.execute(select(func.count()).select_from(TransactionRow).where(*conds)).scalar_one()
    from .receipts import load
    recent = [load(r) for r in db.execute(select(ReceiptRow).order_by(ReceiptRow.seq.desc()).limit(8)).scalars()]
    return {"total_actions": count(), "approved_actions": count(TransactionRow.decision == "ALLOW"),
            "blocked_actions": count(TransactionRow.status.in_(("DENIED", "REJECTED"))),
            "pending_approval": count(TransactionRow.status == "PENDING_APPROVAL"),
            "open_disputes": db.execute(select(func.count()).select_from(DisputeRow).where(DisputeRow.status == "OPEN")).scalar_one(),
            "recent_receipts": recent, "mode": "DEMO_MOCK_DATA"}
