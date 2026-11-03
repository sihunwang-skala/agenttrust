# AgentTrust — an independent trust layer for AI agent actions (research prototype)

> **Local research prototype. All data is synthetic. The merchant is simulated. No real payments, cards, personal data or insurance. Not for production, not legal advice, and not a legal-responsibility decision-maker.**

When an AI agent buys or books something for you, three parties each hold only their own story:

| Party | Problem |
|---|---|
| **User** | Wants delegation without approving every step, plus a way to see *why* the agent acted and to undo mistakes. |
| **Agent provider** | Wants to show the agent stayed inside what the user allowed, without exposing prompts, models or workflows. |
| **Merchant** | Wants to tell legitimate purchases from unauthorized ones and have verifiable evidence in a dispute. |

AgentTrust sits between them: **User → Delegation → AI Agent → Independent Policy Gateway → (Mock) Merchant → Action Receipt → Verification & Recovery dashboard.**

## What it does

- **Delegation Manager**: explicit create → approve, versioned and immutable once approved; expiry and revocation enforced.
- **Independent Policy Gateway**: deterministic code (no LLM) returns `ALLOW` / `DENY` / `REQUIRE_APPROVAL`. It checks delegation validity, agent identity, merchant and category allow-lists, per-item limit, remaining budget, free returns, delivery deadline, duplicates, and agent claims against a **merchant-signed quote**. Budget reservation, idempotency and receipt-chain append are atomic (SQLite `BEGIN IMMEDIATE`).
- **Action Receipts**: structured, canonical-JSON, SHA-256 hash-chained, Ed25519-signed. Viewable as timeline or JSON.
- **Evidence levels**: `SELF_REPORTED`, `GATEWAY_VERIFIED`, `MERCHANT_CONFIRMED` (simulated merchant signature), `UNKNOWN`. `PAYMENT_CONFIRMED` is defined by the concept but **never issued** here.
- **Offline verifier** (`verifier/agenttrust_verify.py`): checks hashes, signatures and chain with only a public key.
- **Recovery & disputes**: compares evidence per party, locates the failing stage, lists violated conditions and *unknown* facts, simulates cancellation through the mock merchant. Responsibility is always `NOT_DETERMINED`. Cancel request/approval/rejection/state change are separate receipts. No refund, chargeback or payout exists.
- **Web UI** (React + TS + Tailwind): Dashboard, Delegation, Agent Simulator (11 scenarios), Receipt Explorer, Dispute & Recovery.

## Quick start

Requirements: Python 3.11+, Node 20+ (or Docker).

```bash
# backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
AGENTTRUST_ALLOW_DEMO_RESET=true .venv/bin/uvicorn app.main:default_app --factory --host 127.0.0.1 --port 8000
```
```bash
# frontend (second terminal)
cd frontend && npm ci && npm run dev    # http://localhost:5173
```
```bash
# or everything with Docker
docker compose up --build
```
Tests: `cd backend && .venv/bin/python -m pytest -q` and `cd frontend && npm test`. API docs at `http://127.0.0.1:8000/docs` (see also [API.md](API.md)). Walkthrough: [DEMO.md](DEMO.md).

Offline verification of the committed sample:
```bash
python verifier/agenttrust_verify.py samples/sample_export.json --public-key samples/gateway_public_key.hex --merchant-public-key samples/mock_merchant_public_key.hex
```

## Honest limits

- The delegation approval is a click on a **Demo Trusted Surface**. There is **no cryptographic proof that the user signed it**.
- A hash chain plus a single server signature detects *alteration* by anyone without the key, but **cannot** prove the record is complete (trailing receipts could be dropped), cannot prove the signer is honest, and is not third-party independent. Extension points for external timestamping and independent witnesses are described in [ARCHITECTURE.md](ARCHITECTURE.md).
- The Mock Merchant's signatures are **simulation evidence**, not real merchant attestations.
- No authentication, rate limiting or tenant isolation: bind to localhost only. See [SECURITY.md](SECURITY.md).

## Relationship to AP2 and other standards

Google's [Agent Payments Protocol (AP2)](https://github.com/google-agentic-commerce/AP2) describes user-approved *mandates* on a trusted surface and signed receipts for agent authorization. AgentTrust borrows that *concept* (delegate on a trusted surface → agent acts within constraints → signed receipt) but **implements none of the AP2 specification, is not AP2-compatible, certified, or affiliated with Google or the AP2 project**. Its focus differs: an independent gateway, evidence-level separation and dispute recovery. Mapping to AP2 mandates is future work ([ROADMAP.md](ROADMAP.md)).

## Layout

```
backend/   FastAPI app, SQLAlchemy models, tests, sample generator
frontend/  React + Vite + Tailwind UI, vitest tests
verifier/  standalone offline verifier (depends only on `cryptography`)
samples/   synthetic signed receipts + public keys
```
License: **not chosen yet** (see [LICENSE_NOTICES.md](LICENSE_NOTICES.md)).
