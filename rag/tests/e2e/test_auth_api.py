import hashlib
import hmac
import json
import time
import pytest


pytestmark = pytest.mark.e2e


def test_login_returns_token(api_client):
    resp = api_client.post(
        "/api/open/rag/login",
        json={
            "username": "admin",
            "password": "admin123",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token_type"] == "Bearer"
    assert data["access_token"]


def test_business_api_accepts_client_signature(api_client):
    app_id = "myapp"
    api_client.delete(f"/api/open/rag/apps/{app_id}/database")
    api_client.delete(f"/api/open/rag/apps/{app_id}")
    app_resp = api_client.post("/api/open/rag/apps", json={"app_id": app_id})
    assert app_resp.status_code == 201, app_resp.text
    try:
        credential = app_resp.json()
        db_resp = api_client.post(f"/api/open/rag/apps/{app_id}/database")
        assert db_resp.status_code == 200, db_resp.text
        body = json.dumps({"query": "人工智能", "mode": "dense"}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = _signature(
            secret_key=credential["secret_key"],
            method="POST",
            path="/api/open/rag/search",
            timestamp=timestamp,
            body=body,
            app_id=app_id,
        )
        resp = api_client.post(
            "/api/open/rag/search",
            content=body,
            headers={
                "Authorization": "",
                "content-type": "application/json",
                "x-app-id": app_id,
                "x-access-key": credential["access_key"],
                "x-timestamp": timestamp,
                "x-signature": signature,
            },
        )
    finally:
        api_client.delete(f"/api/open/rag/apps/{app_id}/database")
        api_client.delete(f"/api/open/rag/apps/{app_id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "dense"


def test_config_requires_bearer_token(anonymous_api_client):
    resp = anonymous_api_client.get("/api/open/rag/config")

    assert resp.status_code == 401


def test_monitor_reports_sparse_component(api_client):
    resp = api_client.get("/api/open/rag/monitor")

    assert resp.status_code == 200, resp.text
    sparse_config = resp.json()["profile"]["sparse"]
    components = {item["name"]: item for item in resp.json()["components"]}
    if sparse_config is None:
        assert components["Sparse"]["status"] == "disabled"
        assert components["Sparse"]["model"] is None
    else:
        assert components["Sparse"]["status"] == "ready"
        assert components["Sparse"]["model"] == sparse_config["name"]


def _signature(*, secret_key: str, method: str, path: str, timestamp: str, body: bytes, app_id: str) -> str:
    body_sha256 = hashlib.sha256(body).hexdigest()
    string_to_sign = "\n".join([method, path, timestamp, body_sha256, app_id])
    return hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
