from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import services as svc
from .agent import SCENARIOS, MockAgent
from .analysis import analyze
from .clock import Clock
from .config import Settings
from .crypto import Signer
from .db import Base, make_engine, make_session_factory
from .errors import AppError
from .merchant import CATALOG, MERCHANTS, MockMerchant
from .models import DisputeRow, ReceiptRow, TransactionRow
from .receipts import SCHEMA_VERSION, check_chain, check_receipt, load
from .runtime import Runtime
from .schemas import ActionRequest, CancelRequest, DelegationCreate, DisputeClose, DisputeCreate, RejectRequest

NOTICE = "AgentTrust is a local research prototype. All data is synthetic/mock. No real payments. Not legal advice."


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_dirs()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    clock = Clock()
    key_dir = Path(settings.key_dir)
    rt = Runtime(settings=settings, sessions=make_session_factory(engine),
                 signer=Signer.load_or_create(key_dir / "gateway_ed25519.pem"),
                 merchant=MockMerchant(Signer.load_or_create(key_dir / "mock_merchant_ed25519.pem"), clock), clock=clock)

    app = FastAPI(title="AgentTrust (research prototype)", version="0.1.0", description=NOTICE)
    app.state.rt = rt
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def err(status: int, code: str, message: str, details=None) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})

    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return err(e.status, e.code, e.message, e.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        return err(422, "VALIDATION_ERROR", "Request validation failed",
                   [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        return err(e.status_code, "HTTP_ERROR", str(e.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        return err(500, "INTERNAL_ERROR", "Unexpected server error")

    def get_db() -> Iterator[Session]:
        with rt.sessions() as s:
            yield s

    api = APIRouter(prefix="/api/v1")

    @api.get("/health")
    def health():
        return {"status": "ok", "mode": "DEMO", "notice": NOTICE, "demo_reset_enabled": settings.allow_demo_reset,
                "receipt_schema": SCHEMA_VERSION}

    @api.get("/keys")
    def keys():
        return {"gateway": {"key_id": rt.signer.key_id, "algorithm": "Ed25519", "public_key_hex": rt.signer.public_hex},
                "mock_merchant": {"key_id": rt.merchant.signer.key_id, "algorithm": "Ed25519",
                                  "public_key_hex": rt.merchant.signer.public_hex, "simulation": True}}

    # ---- delegations
    @api.post("/delegations", status_code=201)
    def create_delegation(body: DelegationCreate, db: Session = Depends(get_db)):
        return svc.create_delegation(rt, db, body)

    @api.get("/delegations")
    def list_delegations(db: Session = Depends(get_db)):
        from .models import DelegationRow
        latest: dict[str, DelegationRow] = {}
        for r in db.execute(select(DelegationRow).order_by(DelegationRow.id)).scalars():
            latest[r.delegation_id] = r
        return [svc.delegation_view(rt, db, r) for r in reversed(list(latest.values()))]

    @api.get("/delegations/{delegation_id}")
    def get_delegation(delegation_id: str, db: Session = Depends(get_db)):
        rows = svc._versions(db, delegation_id)
        if not rows:
            raise AppError(404, "DELEGATION_NOT_FOUND", "Delegation not found")
        return {"current": svc.delegation_view(rt, db, rows[0]), "versions": [svc.delegation_view(rt, db, r) for r in rows]}

    @api.post("/delegations/{delegation_id}/approve")
    def approve_delegation(delegation_id: str, db: Session = Depends(get_db)):
        return svc.approve_delegation(rt, db, delegation_id)

    @api.post("/delegations/{delegation_id}/revisions", status_code=201)
    def revise_delegation(delegation_id: str, body: DelegationCreate, db: Session = Depends(get_db)):
        return svc.revise_delegation(rt, db, delegation_id, body)

    @api.post("/delegations/{delegation_id}/revoke")
    def revoke_delegation(delegation_id: str, db: Session = Depends(get_db)):
        return svc.revoke_delegation(rt, db, delegation_id)

    # ---- policy validation (dry run, writes nothing)
    @api.post("/policy/validate")
    def validate(body: ActionRequest, db: Session = Depends(get_db)):
        p = body.parameters
        res, _q, _d, ver = svc._evaluate(rt, db, agent_id=body.agent_id, delegation_id=body.delegation_id,
                                         merchant_id=p.merchant_id, product_id=p.product_id, quantity=p.quantity,
                                         claims=p.claimed.model_dump(), user_approved=False, exclude_tx=None)
        db.rollback()
        return {"decision": res.decision, "amount_krw": res.amount_krw, "delegation_version": ver, **res.reason(), "dry_run": True}

    # ---- agent actions & transactions
    @api.post("/agent/actions", status_code=201)
    def submit_action(body: ActionRequest, idempotency_key: str | None = Header(default=None)):
        key = idempotency_key or body.idempotency_key
        if not key or len(key) < 8:
            raise AppError(422, "IDEMPOTENCY_KEY_REQUIRED", "Provide Idempotency-Key header or idempotency_key (8+ chars)")
        if idempotency_key and body.idempotency_key and idempotency_key != body.idempotency_key:
            raise AppError(422, "IDEMPOTENCY_KEY_CONFLICT", "Header and body idempotency keys differ")
        return svc.submit_action(rt, body, key)

    @api.get("/transactions")
    def list_transactions(db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500)):
        rows = db.execute(select(TransactionRow).order_by(TransactionRow.created_at.desc()).limit(limit)).scalars()
        return [svc.tx_view(db, t) for t in rows]

    @api.get("/transactions/{tx_id}")
    def get_transaction(tx_id: str, db: Session = Depends(get_db)):
        return svc.tx_view(db, svc._get_tx(db, tx_id))

    @api.post("/transactions/{tx_id}/approve")
    def approve_tx(tx_id: str):
        return svc.approve_transaction(rt, tx_id)

    @api.post("/transactions/{tx_id}/reject")
    def reject_tx(tx_id: str, body: RejectRequest = RejectRequest()):
        return svc.reject_transaction(rt, tx_id, body.reason)

    @api.post("/transactions/{tx_id}/cancel")
    def cancel_tx(tx_id: str, body: CancelRequest):
        return svc.cancel_transaction(rt, tx_id, body.reason)

    # ---- receipts
    def _receipts(db: Session, transaction_id=None, delegation_id=None, limit=500):
        q = select(ReceiptRow).order_by(ReceiptRow.seq)
        if transaction_id:
            q = q.where(ReceiptRow.transaction_id == transaction_id)
        if delegation_id:
            q = q.where(ReceiptRow.delegation_id == delegation_id)
        return [load(r) for r in db.execute(q.limit(limit)).scalars()]

    @api.get("/receipts")
    def list_receipts(db: Session = Depends(get_db), transaction_id: str | None = None, delegation_id: str | None = None,
                      limit: int = Query(200, ge=1, le=1000)):
        return _receipts(db, transaction_id, delegation_id, limit)

    @api.get("/receipts/export")
    def export_receipts(db: Session = Depends(get_db)):
        return {"schema": "agenttrust.export/1", "notice": NOTICE, "gateway_public_key_hex": rt.signer.public_hex,
                "gateway_key_id": rt.signer.key_id, "mock_merchant_public_key_hex": rt.merchant.signer.public_hex,
                "receipts": _receipts(db, limit=100000)}

    @api.get("/receipts/verify-chain")
    def verify_chain(db: Session = Depends(get_db)):
        return check_chain(_receipts(db, limit=100000), rt.signer.public_hex)

    @api.get("/receipts/{receipt_id}")
    def get_receipt(receipt_id: str, db: Session = Depends(get_db)):
        row = db.execute(select(ReceiptRow).where(ReceiptRow.receipt_id == receipt_id)).scalar_one_or_none()
        if row is None:
            raise AppError(404, "RECEIPT_NOT_FOUND", "Receipt not found")
        return load(row)

    @api.get("/receipts/{receipt_id}/verify")
    def verify_receipt(receipt_id: str, db: Session = Depends(get_db)):
        row = db.execute(select(ReceiptRow).where(ReceiptRow.receipt_id == receipt_id)).scalar_one_or_none()
        if row is None:
            raise AppError(404, "RECEIPT_NOT_FOUND", "Receipt not found")
        r = load(row)
        prev = db.execute(select(ReceiptRow).where(ReceiptRow.seq == row.seq - 1)).scalar_one_or_none()
        expected_prev = load(prev)["current_hash"] if prev else "0" * 64
        c = check_receipt(r, rt.signer.public_hex)
        link = r["previous_hash"] == expected_prev
        merchant_ok = None
        if r.get("merchant_response"):
            merchant_ok = rt.merchant.verify(r["merchant_response"])
        return {"receipt_id": receipt_id, **c, "chain_link_valid": link, "merchant_signature_valid": merchant_ok,
                "valid": c["signature_valid"] and link, "note": "Single-server signature; see SECURITY.md for limits"}

    # ---- disputes
    @api.post("/disputes", status_code=201)
    def create_dispute(body: DisputeCreate):
        return svc.open_dispute(rt, body.transaction_id, body.opened_by, body.reason)

    @api.get("/disputes")
    def list_disputes(db: Session = Depends(get_db)):
        return [svc.dispute_view(d) for d in db.execute(select(DisputeRow).order_by(DisputeRow.created_at.desc())).scalars()]

    @api.get("/disputes/{dispute_id}")
    def get_dispute(dispute_id: str, db: Session = Depends(get_db)):
        return svc.dispute_view(svc.get_dispute(db, dispute_id))

    @api.get("/disputes/{dispute_id}/analysis")
    def dispute_analysis(dispute_id: str, db: Session = Depends(get_db)):
        return analyze(db, svc.get_dispute(db, dispute_id))

    @api.post("/disputes/{dispute_id}/cancellations")
    def dispute_cancel(dispute_id: str, body: CancelRequest, db: Session = Depends(get_db)):
        d = svc.get_dispute(db, dispute_id)
        if d.status != "OPEN":
            raise AppError(409, "DISPUTE_NOT_OPEN", "Dispute is closed")
        tx_id = d.transaction_id
        db.rollback()
        return svc.cancel_transaction(rt, tx_id, body.reason)

    @api.post("/disputes/{dispute_id}/close")
    def dispute_close(dispute_id: str, body: DisputeClose = DisputeClose()):
        return svc.close_dispute(rt, dispute_id, body.resolution_note)

    # ---- mock merchant, simulator, dashboard, demo reset
    @api.get("/mock-merchant/catalog")
    def catalog():
        return {"simulation": True, "merchants": MERCHANTS, "products": rt.merchant.public_catalog()}

    @api.get("/simulator/scenarios")
    def scenarios():
        return [{"name": k, "title": v["title"], "description": v["description"]} for k, v in SCENARIOS.items()]

    @api.post("/simulator/scenarios/{name}/run")
    def run_scenario(name: str, delegation_id: str = Query(...)):
        sc = SCENARIOS.get(name)
        if sc is None:
            raise AppError(404, "SCENARIO_NOT_FOUND", "Unknown scenario")
        with rt.sessions() as db:
            rows = svc._versions(db, delegation_id)
            if not rows:
                raise AppError(404, "DELEGATION_NOT_FOUND", "Delegation not found")
            agent = MockAgent(rows[0].agent_id)
        action = agent.build_action(sc["task"], delegation_id)
        steps = [{"step": "agent_submit", "result": svc.submit_action(rt, action, action.idempotency_key)}]
        if name == "duplicate_request":
            steps.append({"step": "agent_resubmit_same_key", "result": svc.submit_action(rt, action, action.idempotency_key)})
        if sc.get("then_cancel"):
            tx = steps[0]["result"]
            if tx["status"] in ("EXECUTED", "DISCREPANCY"):
                steps.append({"step": "user_cancel", "result": svc.cancel_transaction(rt, tx["transaction_id"], "Simulated user cancellation")})
        return {"scenario": name, "steps": steps, "final": steps[-1]["result"]}

    @api.get("/dashboard/summary")
    def summary(db: Session = Depends(get_db)):
        return svc.dashboard(rt, db)

    @api.post("/demo/reset")
    def reset():
        if not settings.allow_demo_reset:
            raise AppError(403, "DEMO_RESET_DISABLED", "Set AGENTTRUST_ALLOW_DEMO_RESET=true to enable (local demo only)")
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        return {"status": "reset"}

    app.include_router(api)
    return app


def default_app() -> FastAPI:
    return create_app()
