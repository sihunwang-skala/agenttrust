from .conftest import act

API = "/api/v1"


def _dispute(client, tx_id, reason="Wrong purchase"):
    r = client.post(f"{API}/disputes", json={"transaction_id": tx_id, "reason": reason})
    assert r.status_code == 201, r.text
    return r.json()


def test_cancellation_creates_separate_receipts(client, deleg):
    t = act(client, deleg["delegation_id"]).json()
    c = client.post(f"{API}/transactions/{t['transaction_id']}/cancel", json={"reason": "Ordered by mistake"})
    assert c.status_code == 200 and c.json()["status"] == "CANCELLED"
    evs = [r["event_type"] for r in client.get(f"{API}/receipts", params={"transaction_id": t["transaction_id"]}).json()]
    assert evs == ["POLICY_DECISION", "EXECUTION_RESULT", "CANCEL_REQUESTED", "CANCEL_APPROVED", "TRANSACTION_STATE_CHANGED"]
    assert client.get(f"{API}/delegations/{deleg['delegation_id']}").json()["current"]["spent_krw"] == 0  # budget released
    assert client.get(f"{API}/receipts/verify-chain").json()["valid"]


def test_cancellation_rejected_by_merchant(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_engraved", merchant="m_gadgethub").json()
    c = client.post(f"{API}/transactions/{t['transaction_id']}/cancel", json={"reason": "changed mind"}).json()
    assert c["status"] == "EXECUTED" and c["cancellation_outcome"] == "CANCEL_REJECTED"
    evs = [r["event_type"] for r in client.get(f"{API}/receipts", params={"transaction_id": t["transaction_id"]}).json()]
    assert evs[-2:] == ["CANCEL_REQUESTED", "CANCEL_REJECTED"] and "TRANSACTION_STATE_CHANGED" not in evs


def test_cannot_cancel_denied_failed_or_unknown(client, deleg):
    for p in ("p_webcam", "p_flaky", "p_timeout"):
        t = act(client, deleg["delegation_id"], product=p).json()
        r = client.post(f"{API}/transactions/{t['transaction_id']}/cancel", json={"reason": "x"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_CANCELLABLE"


def test_dispute_flow_with_cancellation(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_tablet", merchant="m_gadgethub").json()
    d = _dispute(client, t["transaction_id"], "Charged more than quoted")
    assert client.post(f"{API}/disputes", json={"transaction_id": t["transaction_id"], "reason": "again"}).status_code == 409
    a = client.get(f"{API}/disputes/{d['dispute_id']}/analysis").json()
    assert a["failed_stage"] == "MERCHANT_EXECUTION"
    assert a["discrepancies"][0]["expected"] == 80000 and a["discrepancies"][0]["observed"] == 95000
    assert a["cancellation"]["possible"] is True
    assert set(a["evidence_by_party"]) == {"user", "agent", "gateway", "merchant"}
    c = client.post(f"{API}/disputes/{d['dispute_id']}/cancellations", json={"reason": "overcharged"}).json()
    assert c["status"] == "CANCELLED"
    assert client.post(f"{API}/disputes/{d['dispute_id']}/close", json={"resolution_note": "recovered"}).json()["status"] == "CLOSED"
    assert client.get(f"{API}/dashboard/summary").json()["open_disputes"] == 0


def test_insufficient_evidence_never_assigns_responsibility(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_timeout").json()
    d = _dispute(client, t["transaction_id"], "Not sure what happened")
    a = client.get(f"{API}/disputes/{d['dispute_id']}/analysis").json()
    assert a["responsibility"]["determination"] == "NOT_DETERMINED"
    assert a["transaction_status"] == "UNKNOWN" and a["cancellation"]["possible"] is False
    assert any("unknown" in u.lower() for u in a["unknown_facts"])
    blob = str(a).lower()
    assert "at_fault" not in blob and "liable" not in blob.replace("legal responsibility", "")


def test_agent_false_claim_unknown_intent(client, deleg):
    t = act(client, deleg["delegation_id"], product="p_webcam", claimed={"free_returns": True}).json()
    d = _dispute(client, t["transaction_id"], "agent lied?")
    a = client.get(f"{API}/disputes/{d['dispute_id']}/analysis").json()
    assert a["failed_stage"] == "POLICY_CHECK" and a["responsibility"]["determination"] == "NOT_DETERMINED"
    assert any("intentional" in u for u in a["unknown_facts"])
    assert any(e["level"] == "SELF_REPORTED" for e in a["evidence_by_party"]["agent"])


def test_simulator_and_dashboard(client, deleg):
    did = deleg["delegation_id"]
    names = [s["name"] for s in client.get(f"{API}/simulator/scenarios").json()]
    assert "normal_purchase" in names and "cancel_request" in names
    r = client.post(f"{API}/simulator/scenarios/cancel_request/run", params={"delegation_id": did}).json()
    assert r["final"]["status"] == "CANCELLED"
    r = client.post(f"{API}/simulator/scenarios/duplicate_request/run", params={"delegation_id": did}).json()
    assert r["steps"][1]["result"]["replayed"] is True
    s = client.get(f"{API}/dashboard/summary").json()
    assert s["total_actions"] == 2 and s["mode"] == "DEMO_MOCK_DATA"
    assert client.post(f"{API}/simulator/scenarios/nope/run", params={"delegation_id": did}).status_code == 404
