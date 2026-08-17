import hashlib
import hmac
import json
import time

import pytest


pytestmark = pytest.mark.e2e


def test_password_grant_returns_token(api_client):
    resp = api_client.post(
        "/api/auth/token",
        json={
            "grant_type": "password",
            "username": "admin",
            "password": "admin123",
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token_type"] == "Bearer"
    assert data["access_token"]


def test_client_credentials_grant_returns_token(api_client):
    body = b'{"grant_type":"client_credentials"}'
    timestamp = str(int(time.time()))
    signature = _signature(
        secret_key="78ddbd0730125b050b607c81c8398c4fe96f707cfa66f222d42a8eeae3aa47e6",
        method="POST",
        path="/api/auth/token",
        timestamp=timestamp,
        body=body,
        app_id="imsdom",
    )

    resp = api_client.post(
        "/api/auth/token",
        content=body,
        headers={
            "content-type": "application/json",
            "x-app-id": "imsdom",
            "x-access-key": "0d01c6bc9577a6dae3095cb7972a9f8c",
            "x-timestamp": timestamp,
            "x-signature": signature,
        },
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token_type"] == "Bearer"
    assert data["access_token"]


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
