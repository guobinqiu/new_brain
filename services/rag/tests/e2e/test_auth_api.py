import pytest


pytestmark = pytest.mark.e2e


def test_login_returns_token(anonymous_api_client, rag_server):
    resp = anonymous_api_client.post("/api/rag/login", json=rag_server.admin_credentials)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["token_type"] == "Bearer"
    assert data["access_token"]


def test_business_api_accepts_bearer_api_key(app_api_client):
    resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "dense"


def test_admin_api_accepts_jwt_for_business_actions(api_client, app_api_client):
    resp = api_client.post("/api/rag/search", json={"app_id": app_api_client.app_id, "query": "人工智能"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "dense"


def test_config_requires_bearer_token(anonymous_api_client):
    resp = anonymous_api_client.get("/api/rag/config")

    assert resp.status_code == 401
