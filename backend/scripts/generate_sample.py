"""Generate samples/ (synthetic receipts + PUBLIC keys). Uses throwaway keys that are deleted afterwards."""
import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "samples"

with tempfile.TemporaryDirectory() as tmp:
    app = create_app(Settings(database_url=f"sqlite:///{tmp}/s.db", key_dir=f"{tmp}/keys"))
    with TestClient(app) as c:
        d = c.post("/api/v1/delegations", json={"agent_id": "agent_demo", "total_budget_krw": 600000, "per_item_max_krw": 200000,
                                                "allowed_categories": ["Electronics"], "allowed_merchants": ["m_techmart", "m_gadgethub"]}).json()
        c.post(f"/api/v1/delegations/{d['delegation_id']}/approve")
        for s in ("normal_purchase", "free_returns_violation", "merchant_mismatch", "cancel_request"):
            c.post(f"/api/v1/simulator/scenarios/{s}/run", params={"delegation_id": d["delegation_id"]})
        ex = c.get("/api/v1/receipts/export").json()
    OUT.mkdir(exist_ok=True)
    (OUT / "sample_export.json").write_text(json.dumps(ex, indent=2, sort_keys=True))
    (OUT / "gateway_public_key.hex").write_text(ex["gateway_public_key_hex"] + "\n")
    (OUT / "mock_merchant_public_key.hex").write_text(ex["mock_merchant_public_key_hex"] + "\n")
print("wrote", OUT, len(ex["receipts"]), "receipts")
