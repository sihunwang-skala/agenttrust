import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "verifier"))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/t.db", key_dir=str(tmp_path / "keys"), allow_demo_reset=True)
    return create_app(s)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def rt(app):
    return app.state.rt


BASE = dict(agent_id="agent_demo", total_budget_krw=300000, per_item_max_krw=200000, allowed_categories=["Electronics"],
            allowed_merchants=["m_techmart", "m_gadgethub"], require_free_returns=True, max_delivery_days=7,
            valid_for_minutes=60, auto_purchase_allowed=True)


def make_delegation(client, approve=True, **over):
    r = client.post("/api/v1/delegations", json={**BASE, **over})
    assert r.status_code == 201, r.text
    d = r.json()
    if approve:
        a = client.post(f"/api/v1/delegations/{d['delegation_id']}/approve")
        assert a.status_code == 200, a.text
        d = a.json()
    return d


def act(client, delegation_id, product="p_headphones", merchant="m_techmart", qty=1, key=None, claimed=None, agent="agent_demo"):
    body = {"agent_id": agent, "delegation_id": delegation_id, "idempotency_key": key or "k-" + uuid.uuid4().hex,
            "parameters": {"merchant_id": merchant, "product_id": product, "quantity": qty, "claimed": claimed or {}}}
    return client.post("/api/v1/agent/actions", json=body)


@pytest.fixture()
def deleg(client):
    return make_delegation(client)
