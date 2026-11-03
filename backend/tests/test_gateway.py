import threading
from concurrent.futures import ThreadPoolExecutor

from .conftest import act, make_delegation

API = "/api/v1"


def test_normal_purchase_succeeds(client, deleg):
    r = act(client, deleg["delegation_id"])
    assert r.status_code == 201
    t = r.json()
    assert t["decision"] == "ALLOW" and t["status"] == "EXECUTED" and t["amount_krw"] == 120000
    assert len(t["receipt_ids"]) == 2
    d = client.get(f"{API}/delegations/{deleg['delegation_id']}").json()["current"]
    assert d["spent_krw"] == 120000 and d["remaining_krw"] == 180000


def test_over_budget_is_blocked(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_monitor", qty=2).json()
    assert t["decision"] == "DENY" and t["status"] == "DENIED"
    assert [v["code"] for v in t["policy_reason"]["violations"]] == ["BUDGET_EXCEEDED"]


def test_cumulative_budget_enforced(client, deleg):
    assert act(client, deleg["delegation_id"], product="p_monitor").json()["status"] == "EXECUTED"
    t = act(client, deleg["delegation_id"], product="p_headphones", qty=1).json()  # 190k + 120k > 300k
    assert t["status"] == "DENIED"


def test_free_returns_violation(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_webcam").json()
    assert t["status"] == "DENIED"
    assert "FREE_RETURNS_REQUIRED" in [v["code"] for v in t["policy_reason"]["violations"]]


def test_false_agent_claim_is_denied(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_webcam", claimed={"free_returns": True}).json()
    codes = [v["code"] for v in t["policy_reason"]["violations"]]
    assert "AGENT_CLAIM_MISMATCH" in codes and t["status"] == "DENIED"


def test_other_violations(client, deleg):
    did = deleg["delegation_id"]
    assert "MERCHANT_NOT_ALLOWED" in [v["code"] for v in act(client, did, product="p_shady", merchant="m_shadydeals").json()["policy_reason"]["violations"]]
    assert "CATEGORY_NOT_ALLOWED" in [v["code"] for v in act(client, did, product="p_sofa").json()["policy_reason"]["violations"]]
    assert "PER_ITEM_LIMIT_EXCEEDED" in [v["code"] for v in act(client, did, product="p_laptop", merchant="m_gadgethub").json()["policy_reason"]["violations"]]
    assert "DELIVERY_TOO_SLOW" in [v["code"] for v in act(client, did, product="p_slowdock", merchant="m_gadgethub").json()["policy_reason"]["violations"]]
    assert "PRODUCT_NOT_FOUND" in [v["code"] for v in act(client, did, product="p_nope").json()["policy_reason"]["violations"]]
    assert "AGENT_MISMATCH" in [v["code"] for v in act(client, did, agent="agent_evil").json()["policy_reason"]["violations"]]


def test_expired_delegation_denied(client, rt, deleg):
    rt.clock.advance(61 * 60)
    t = act(client, deleg["delegation_id"]).json()
    assert t["status"] == "DENIED"
    assert "DELEGATION_EXPIRED" in [v["code"] for v in t["policy_reason"]["violations"]]
    assert client.get(f"{API}/delegations/{deleg['delegation_id']}").json()["current"]["status"] == "EXPIRED"


def test_revoked_and_unapproved_delegation_denied(client, deleg):
    pending = make_delegation(client, approve=False)
    assert "DELEGATION_NOT_APPROVED" in [v["code"] for v in act(client, pending["delegation_id"]).json()["policy_reason"]["violations"]]
    assert client.post(f"{API}/delegations/{deleg['delegation_id']}/revoke").status_code == 200
    t = act(client, deleg["delegation_id"]).json()
    assert "DELEGATION_REVOKED" in [v["code"] for v in t["policy_reason"]["violations"]]
    assert client.post(f"{API}/delegations/{deleg['delegation_id']}/revisions", json={
        "agent_id": "agent_demo", "total_budget_krw": 1000, "per_item_max_krw": 500, "allowed_categories": ["Electronics"],
        "allowed_merchants": ["m_techmart"]}).status_code == 409
    assert "DELEGATION_NOT_FOUND" in [v["code"] for v in act(client, "dlg_missing").json()["policy_reason"]["violations"]]


def test_delegation_versioning(client, deleg):
    did = deleg["delegation_id"]
    body = {"agent_id": "agent_demo", "total_budget_krw": 500000, "per_item_max_krw": 250000, "allowed_categories": ["Electronics"],
            "allowed_merchants": ["m_techmart"], "valid_for_minutes": 30}
    v2 = client.post(f"{API}/delegations/{did}/revisions", json=body).json()
    assert v2["version"] == 2 and v2["status"] == "PENDING_APPROVAL"
    assert act(client, did).json()["delegation_version"] == 1  # old version still governs until v2 is approved
    assert client.post(f"{API}/delegations/{did}/approve").json()["version"] == 2
    vs = client.get(f"{API}/delegations/{did}").json()["versions"]
    assert [(v["version"], v["status"]) for v in vs] == [(2, "ACTIVE"), (1, "SUPERSEDED")]
    assert act(client, did, product="p_cable").json()["delegation_version"] == 2


def test_idempotent_duplicate_is_not_executed_twice(client, deleg):
    a = act(client, deleg["delegation_id"], key="same-key-123").json()
    b = act(client, deleg["delegation_id"], key="same-key-123").json()
    assert b["replayed"] is True and a["transaction_id"] == b["transaction_id"]
    assert len(client.get(f"{API}/transactions").json()) == 1
    assert client.get(f"{API}/delegations/{deleg['delegation_id']}").json()["current"]["spent_krw"] == 120000
    r = act(client, deleg["delegation_id"], key="same-key-123", product="p_cable")
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_semantic_duplicate_with_new_key_denied(client, deleg):
    assert act(client, deleg["delegation_id"], product="p_cable").json()["status"] == "EXECUTED"
    t = act(client, deleg["delegation_id"], product="p_cable").json()
    assert "DUPLICATE_SUSPECTED" in [v["code"] for v in t["policy_reason"]["violations"]]


def test_concurrent_same_key_executes_once(client, deleg):
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda _: act(client, deleg["delegation_id"], key="race-key-0001").json(), range(8)))
    assert len({r["transaction_id"] for r in res}) == 1
    assert len(client.get(f"{API}/transactions").json()) == 1


def test_concurrent_requests_cannot_exceed_budget(client):
    d = make_delegation(client, total_budget_krw=300000)
    products = ["p_monitor", "p_headphones", "p_cable", "p_tablet", "p_engraved", "p_slowdock", "p_flaky", "p_timeout"]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda p: act(client, d["delegation_id"], product=p, merchant=("m_gadgethub" if p in ("p_tablet", "p_engraved", "p_slowdock") else "m_techmart")).json(), products))
    view = client.get(f"{API}/delegations/{d['delegation_id']}").json()["current"]
    assert view["spent_krw"] <= 300000 and view["remaining_krw"] >= 0
    assert any(r["decision"] == "DENY" for r in res)
    chain = client.get(f"{API}/receipts/verify-chain").json()
    assert chain["valid"], chain


def test_same_price_concurrent_requests_budget(client):
    d = make_delegation(client, total_budget_krw=200000, per_item_max_krw=200000)
    keys = [f"conc-{i:04d}" for i in range(6)]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda k: act(client, d["delegation_id"], product="p_monitor", key=k).json(), keys))
    ok = [r for r in res if r["status"] == "EXECUTED"]
    assert len(ok) == 1


def test_merchant_error_leaves_consistent_state(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_flaky").json()
    assert t["status"] == "FAILED" and t["charged_krw"] is None
    assert client.get(f"{API}/delegations/{deleg['delegation_id']}").json()["current"]["spent_krw"] == 0
    r = client.get(f"{API}/receipts", params={"transaction_id": t["transaction_id"]}).json()
    assert [x["event_type"] for x in r] == ["POLICY_DECISION", "EXECUTION_RESULT"]
    assert r[-1]["execution_status"] == "MERCHANT_ERROR"


def test_merchant_timeout_keeps_budget_reserved_and_unknown(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_timeout").json()
    assert t["status"] == "UNKNOWN"
    assert client.get(f"{API}/delegations/{deleg['delegation_id']}").json()["current"]["spent_krw"] == 40000
    last = client.get(f"{API}/receipts", params={"transaction_id": t["transaction_id"]}).json()[-1]
    assert last["verification_level"] == "UNKNOWN"


def test_merchant_mismatch_flagged(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_tablet", merchant="m_gadgethub").json()
    assert t["status"] == "DISCREPANCY" and t["charged_krw"] == 95000 and t["amount_krw"] == 80000
    assert t["discrepancies"][0]["field"] == "charged_krw"


def test_require_approval_flow(client):
    d = make_delegation(client, auto_purchase_allowed=False)
    t = act(client, d["delegation_id"]).json()
    assert t["decision"] == "REQUIRE_APPROVAL" and t["status"] == "PENDING_APPROVAL"
    assert client.get(f"{API}/delegations/{d['delegation_id']}").json()["current"]["spent_krw"] == 0
    a = client.post(f"{API}/transactions/{t['transaction_id']}/approve").json()
    assert a["status"] == "EXECUTED"
    t2 = act(client, d["delegation_id"], product="p_cable").json()
    r = client.post(f"{API}/transactions/{t2['transaction_id']}/reject", json={"reason": "no"}).json()
    assert r["status"] == "REJECTED"


def test_policy_validate_is_dry_run(client, deleg):
    body = {"agent_id": "agent_demo", "delegation_id": deleg["delegation_id"], "idempotency_key": "dry-run-0001",
            "parameters": {"merchant_id": "m_techmart", "product_id": "p_headphones"}}
    r = client.post(f"{API}/policy/validate", json=body).json()
    assert r["decision"] == "ALLOW" and r["dry_run"]
    assert client.get(f"{API}/transactions").json() == []


def test_validation_and_error_format(client):
    r = client.post(f"{API}/agent/actions", json={"agent_id": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get(f"{API}/receipts/nope").json()["error"]["code"] == "RECEIPT_NOT_FOUND"
    assert client.post(f"{API}/delegations", json={"agent_id": "a", "total_budget_krw": -5}).status_code == 422
    assert client.get(f"{API}/health").json()["status"] == "ok"
