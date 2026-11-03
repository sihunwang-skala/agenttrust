# Demo walkthrough (all data synthetic, merchant simulated)

Start backend + frontend (README), open http://localhost:5173. Use **Reset demo data** (header) between runs. Defaults: budget 300,000 KRW, per-item 200,000, Electronics, free returns required.

1. **Delegation** → *Create delegation*, then *Approve (demo surface)*. Note the notice that this is not a user signature. Select it for the simulator.
2. **Agent Simulator** (scenarios consume budget, so create a fresh delegation if later ones are denied for budget):
   - *Normal purchase* → ALLOW, EXECUTED (120,000 KRW).
   - *Over-budget attempt* → DENY `BUDGET_EXCEEDED`.
   - *Free-returns violation* → DENY `FREE_RETURNS_REQUIRED`; *Agent makes a false claim* → also `AGENT_CLAIM_MISMATCH`.
   - *Duplicate request* → second submit shows "idempotent replay", only one transaction.
   - *Merchant mismatch* → DISCREPANCY: quoted 80,000, merchant-signed confirmation charged 95,000.
   - *Merchant error* → FAILED, budget released. *Merchant timeout* → UNKNOWN, budget stays reserved.
   - *Purchase, then cancel* → CANCELLED; *Cancel rejected by merchant* → stays EXECUTED.
3. **Receipt Explorer**: pick a receipt, switch Timeline/JSON, see verifiable evidence vs unverified claims, press *Verify this receipt* and *Verify whole chain*, *Export JSON*.
4. Offline: `python verifier/agenttrust_verify.py agenttrust-export.json --public-key <gateway key from GET /api/v1/keys>`; edit any field in the file and re-run to see it fail.
5. **Dispute & Recovery**: choose the mismatch transaction → *Open dispute* → review violated conditions, discrepancies (with sources), evidence by party, unknowns and `Responsibility: NOT_DETERMINED` → *Request cancellation* → *Close dispute*. For the timeout transaction, cancellation is disabled because no merchant order exists.
6. **Delegation** → *Revoke*, then run any scenario: DENY `DELEGATION_REVOKED`.
