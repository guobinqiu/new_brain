import hashlib
import hmac
import json
import time

import pytest


pytestmark = pytest.mark.e2e


def test_login_returns_token(api_client):
    resp = api_client.post(
        "/api/login",
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
    credential = api_client.post("/api/apps", json={"app_id": "signed_search"}).json()
    db_resp = api_client.post("/api/apps/signed_search/database")
    assert db_resp.status_code == 200, db_resp.text
    body = json.dumps({"query": "人工智能", "mode": "sparse"}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = _signature(
        secret_key=credential["secret_key"],
        method="POST",
        path="/api/open/search",
        timestamp=timestamp,
        body=body,
        app_id="signed_search",
    )

    resp = api_client.post(
        "/api/open/search",
        content=body,
        headers={
            "Authorization": "",
            "content-type": "application/json",
            "x-app-id": "signed_search",
            "x-access-key": credential["access_key"],
            "x-timestamp": timestamp,
            "x-signature": signature,
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "sparse"


def test_config_requires_bearer_token(anonymous_api_client):
    resp = anonymous_api_client.get("/api/config")

    assert resp.status_code == 401


def test_monitor_reports_sparse_as_one_runtime_component(api_client):
    resp = api_client.get("/api/monitor")

    assert resp.status_code == 200, resp.text
    components = {item["name"]: item for item in resp.json()["components"]}
    assert components["Sparse"]["model"] == "bm25"


def _signature(*, secret_key: str, method: str, path: str, timestamp: str, body: bytes, app_id: str) -> str:
    body_sha256 = hashlib.sha256(body).hexdigest()
    string_to_sign = "\n".join([method, path, timestamp, body_sha256, app_id])
    return hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
