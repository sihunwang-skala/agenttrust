import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import agenttrust_verify as av

from .conftest import act

API = "/api/v1"
CLI = Path(__file__).resolve().parents[2] / "verifier" / "agenttrust_verify.py"


def _populate(client, deleg):
    act(client, deleg["delegation_id"])
    act(client, deleg["delegation_id"], product="p_webcam")


def _export(client):
    return client.get(f"{API}/receipts/export").json()


def test_receipts_have_required_fields_and_chain(client, deleg):
    _populate(client, deleg)
    rs = client.get(f"{API}/receipts").json()
    required = {"receipt_id", "transaction_id", "timestamp", "agent_id", "delegation_id", "delegation_version", "requested_action",
                "action_parameters", "policy_decision", "policy_reason", "evidence_references", "merchant_response",
                "execution_status", "verification_level", "previous_hash", "current_hash", "signature", "schema_version"}
    assert all(required <= set(r) for r in rs)
    assert rs[0]["previous_hash"] == "0" * 64
    assert all(rs[i]["previous_hash"] == rs[i - 1]["current_hash"] for i in range(1, len(rs)))
    assert client.get(f"{API}/receipts/verify-chain").json()["valid"]
    v = client.get(f"{API}/receipts/{rs[1]['receipt_id']}/verify").json()
    assert v["valid"] and v["merchant_signature_valid"] is True


def test_payment_confirmed_never_issued(client, deleg):
    _populate(client, deleg)
    for r in client.get(f"{API}/receipts").json():
        assert r["verification_level"] != "PAYMENT_CONFIRMED"
        assert all(e["level"] != "PAYMENT_CONFIRMED" for e in r["evidence_references"])
    ex = [r for r in client.get(f"{API}/receipts").json() if r["event_type"] == "EXECUTION_RESULT"][0]
    assert ex["verification_level"] == "MERCHANT_CONFIRMED"
    denied = [r for r in client.get(f"{API}/receipts").json() if r["policy_decision"] == "DENY"][0]
    assert any(e["level"] == "SELF_REPORTED" for e in denied["evidence_references"])


def test_offline_verification_succeeds(client, deleg, tmp_path):
    _populate(client, deleg)
    ex = _export(client)
    f = tmp_path / "export.json"
    f.write_text(json.dumps(ex))
    out = subprocess.run([sys.executable, str(CLI), str(f), "--public-key", ex["gateway_public_key_hex"],
                          "--merchant-public-key", ex["mock_merchant_public_key_hex"]], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "OK" in out.stdout


def test_modified_receipt_fails_signature_check(client, deleg, tmp_path):
    _populate(client, deleg)
    ex = _export(client)
    ex["receipts"][1]["action_parameters"]["quantity"] = 99  # tamper
    assert any("HASH_MISMATCH" in p for p in av.verify(ex["receipts"], ex["gateway_public_key_hex"]))
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(ex))
    out = subprocess.run([sys.executable, str(CLI), str(f), "--public-key", ex["gateway_public_key_hex"]], capture_output=True, text=True)
    assert out.returncode == 1


def test_rehashed_tampering_fails_signature(client, deleg):
    """Attacker alters content AND recomputes the hash: signature (needs private key) must fail."""
    _populate(client, deleg)
    ex = _export(client)
    r = ex["receipts"][1]
    r["policy_decision"] = "DENY"
    core = {k: v for k, v in r.items() if k not in ("current_hash", "signature")}
    r["current_hash"] = av.sha(av.canonical(core))
    probs = av.verify(ex["receipts"], ex["gateway_public_key_hex"])
    assert any("BAD_SIGNATURE" in p for p in probs)


def test_hash_chain_break_detected(client, deleg):
    _populate(client, deleg)
    ex = _export(client)
    del ex["receipts"][1]  # delete a receipt from the middle
    probs = av.verify(ex["receipts"], ex["gateway_public_key_hex"])
    assert any("BROKEN_CHAIN_LINK" in p for p in probs) and any("SEQUENCE_GAP" in p for p in probs)


def test_wrong_public_key_rejected(client, deleg):
    _populate(client, deleg)
    ex = _export(client)
    other = client.get(f"{API}/keys").json()["mock_merchant"]["public_key_hex"]
    assert av.verify(ex["receipts"], other)


def test_server_side_tampering_detected_by_api(client, deleg, app):
    _populate(client, deleg)
    rid = client.get(f"{API}/receipts").json()[1]["receipt_id"]
    db_path = app.state.rt.settings.database_url.replace("sqlite:///", "")
    con = sqlite3.connect(db_path)
    body = json.loads(con.execute("select body_json from receipts where receipt_id=?", (rid,)).fetchone()[0])
    body["execution_status"] = "TAMPERED"
    con.execute("update receipts set body_json=? where receipt_id=?", (json.dumps(body), rid))
    con.commit()
    con.close()
    assert client.get(f"{API}/receipts/{rid}/verify").json()["valid"] is False
    chain = client.get(f"{API}/receipts/verify-chain").json()
    assert not chain["valid"] and chain["problems"][0]["problem"] == "HASH_MISMATCH"


def test_floats_rejected_and_masking():
    import pytest
    from app.crypto import canonical_json
    from app.masking import scrub_text
    with pytest.raises(ValueError):
        canonical_json({"a": 1.5})
    assert "4111" not in scrub_text("card 4111 1111 1111 1111 please")
    assert "hunter2" not in scrub_text("password: hunter2")
