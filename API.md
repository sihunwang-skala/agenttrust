# API (base `/api/v1`, local demo, no authentication)

Interactive OpenAPI: `GET /docs` and `GET /openapi.json` on the running backend. Errors always look like
`{"error": {"code": "...", "message": "...", "details": ...}}` (422 validation, 404, 409 conflicts, 403, 500).

| Method & path | Purpose |
|---|---|
| `GET /health` | Status, demo notice |
| `GET /keys` | Public keys (gateway, mock merchant) |
| `POST /delegations` | Create (status `PENDING_APPROVAL`) |
| `GET /delegations`, `GET /delegations/{id}` | List latest / all versions |
| `POST /delegations/{id}/approve` | Approve latest pending version (supersedes previous) |
| `POST /delegations/{id}/revisions` | New pending version |
| `POST /delegations/{id}/revoke` | Revoke all live versions |
| `POST /policy/validate` | Dry-run decision; writes nothing |
| `POST /agent/actions` | Submit purchase action (`Idempotency-Key` header or `idempotency_key`); returns transaction (`replayed` flag) |
| `GET /transactions`, `GET /transactions/{id}` | Transactions |
| `POST /transactions/{id}/approve` / `reject` | Resolve `REQUIRE_APPROVAL` |
| `POST /transactions/{id}/cancel` | Mock cancellation (receipts: requested, approved/rejected, state change) |
| `GET /receipts?transaction_id=&delegation_id=` | Receipts in chain order |
| `GET /receipts/{id}`, `GET /receipts/{id}/verify` | One receipt / hash, signature, chain-link, merchant-signature checks |
| `GET /receipts/verify-chain`, `GET /receipts/export` | Whole-chain check / export for the offline verifier |
| `POST /disputes`, `GET /disputes`, `GET /disputes/{id}` | Open and read disputes |
| `GET /disputes/{id}/analysis` | Stages, violations, evidence by party, discrepancies, cancellation possibility, unknowns, `responsibility: NOT_DETERMINED` |
| `POST /disputes/{id}/cancellations`, `POST /disputes/{id}/close` | Recovery simulation / close |
| `GET /mock-merchant/catalog` | Synthetic catalog |
| `GET /simulator/scenarios`, `POST /simulator/scenarios/{name}/run?delegation_id=` | Mock-agent scenarios |
| `GET /dashboard/summary` | Counters and recent receipts |
| `POST /demo/reset` | Wipe data (only if `AGENTTRUST_ALLOW_DEMO_RESET=true`) |

Example action:
```json
{"agent_id":"agent_demo","delegation_id":"dlg_…","idempotency_key":"order-0001",
 "parameters":{"merchant_id":"m_techmart","product_id":"p_headphones","quantity":1,
               "claimed":{"free_returns":true},"rationale":"User asked for headphones"}}
```
Violation codes: `DELEGATION_NOT_FOUND|NOT_APPROVED|REVOKED|EXPIRED`, `AGENT_MISMATCH`, `MERCHANT_NOT_ALLOWED`, `CATEGORY_NOT_ALLOWED`, `PER_ITEM_LIMIT_EXCEEDED`, `BUDGET_EXCEEDED`, `FREE_RETURNS_REQUIRED`, `DELIVERY_TOO_SLOW`, `PRODUCT_NOT_FOUND`, `QUOTE_SIGNATURE_INVALID`, `AGENT_CLAIM_MISMATCH`, `DUPLICATE_SUSPECTED`.
