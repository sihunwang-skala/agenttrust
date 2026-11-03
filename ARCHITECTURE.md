# Architecture

```
User ──approve──▶ Delegation Manager ──▶ (versioned delegation store)
                                              │
AI Agent (Mock; adapter interface) ──POST /agent/actions──▶ Independent Policy Gateway
                                              │  1. fetch + verify merchant-signed quote
                                              │  2. deterministic policy (policy.py)
                                              │  3. reserve budget + POLICY_DECISION receipt   (one DB transaction)
                                              ▼
                                  Mock Merchant (own Ed25519 key) ──signed order / error / timeout
                                              │  4. EXECUTION_RESULT receipt + status      (second DB transaction)
                                              ▼
              Receipt chain (hash-chained, Ed25519) ──▶ Dashboard · Receipt Explorer · Dispute analysis · offline verifier
```

## Components (backend/app)
| Module | Role |
|---|---|
| `policy.py` | Pure deterministic evaluation. All violations are collected, not just the first. |
| `services.py` | Delegations, two-phase action execution, approval, cancellation, disputes. |
| `receipts.py`, `crypto.py` | Canonical JSON, SHA-256 chain, Ed25519 signing, in-app verification. |
| `merchant.py` | Simulated merchant: signed quotes/orders/cancellations, fault injection (price mismatch, error, timeout, non-cancellable). |
| `analysis.py` | Dispute analysis; `responsibility` is always `NOT_DETERMINED`. |
| `agent.py` | `AgentAdapter` interface, `MockAgent`, scenario catalog. LangGraph/MCP wrappers implement the adapter and call the same HTTP API. |
| `db.py` | SQLite engine with `BEGIN IMMEDIATE` per transaction (serializes writers, also across processes). |

## Execution model
Phase 1 (atomic): idempotency lookup → policy → budget reserved (status `AUTHORIZED`) → receipt. Phase 2: merchant call outside phase 1's lock → outcome recorded: `EXECUTED`, `DISCREPANCY` (signed confirmation differs from signed quote), `FAILED` (merchant error; budget released), `UNKNOWN` (timeout/invalid signature; budget stays reserved). Cancellation: `CANCEL_REQUESTED` → `CANCEL_APPROVED|CANCEL_REJECTED` → `TRANSACTION_STATE_CHANGED`, each a receipt.
Idempotency is scoped per `(agent_id, idempotency_key)`; same key + different payload → `409`. A semantic-duplicate guard (same agent/delegation/product/quantity within `AGENTTRUST_DUPLICATE_WINDOW_SECONDS`) denies accidental re-submission under a new key.

## Receipt format (`agenttrust.receipt/1`)
Required fields per spec plus `seq`, `event_type`, `signer_key_id`. `current_hash = SHA-256(canonical JSON of all fields except current_hash and signature)`; `signature = Ed25519(private_key, raw hash bytes)`; `previous_hash` of seq 1 is 64 zeros. Canonical JSON: UTF-8, sorted keys, no whitespace, integers only (resembles RFC 8785 but is not a complete implementation). The stored `body_json` is the exact signed text. Free text is scrubbed of card-like numbers and secret patterns; the system never requests personal data.

## Evidence levels
`SELF_REPORTED` (agent/user claims) < `GATEWAY_VERIFIED` (checked by the gateway) < `MERCHANT_CONFIRMED` (merchant-signed, **simulated**). `UNKNOWN` when nothing supports a statement. A receipt's level is the best level among its evidence. `PAYMENT_CONFIRMED` is reserved for a future payment-provider integration.

## Extension points (not implemented)
- External timestamping: anchor the latest `current_hash` periodically (RFC 3161 TSA / transparency log) and store the token in a new receipt.
- Independent witnesses: co-sign checkpoints (`seq`, `current_hash`) so a single operator cannot silently truncate the chain.
- User-signed mandates: replace Demo Trusted Surface approval with a user-key-signed mandate (AP2-style concepts).
- Real merchant/payment adapters behind the `MockMerchant` interface (`quote`, `execute`, `cancel`, `verify`).
