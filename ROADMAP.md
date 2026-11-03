# Roadmap

1. **User-signed mandates**: WebAuthn/passkey-signed delegations; study mapping to AP2 mandate concepts (no compatibility claim until implemented and verified).
2. **Tamper-evidence beyond one server**: external timestamping, independent witness co-signatures, signed checkpoints, key rotation registry.
3. **Authentication, authorization, tenant isolation, rate limiting** (prerequisites for any shared deployment).
4. **Reserve/execute with reconciliation** for crashed or ambiguous merchant calls; Postgres with row locks and migrations.
5. **Real adapters** behind the merchant interface (sandbox payment providers only, after legal review); `PAYMENT_CONFIRMED` evidence.
6. **Agent integrations**: LangGraph node and MCP tool that call the gateway; evidence of agent-side reasoning without disclosing prompts (selective disclosure / commitments).
7. **Richer policy**: time windows, velocity limits, per-merchant budgets, policy-as-data with versioned policy hashes in receipts.
8. **Dispute workflow**: multi-party evidence submission with signatures, SLA timers, exportable evidence bundles.
