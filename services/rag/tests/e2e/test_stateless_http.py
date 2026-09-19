import base64
import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from services.rag.tests.e2e.helpers_stateless import stateless_rag


pytestmark = pytest.mark.e2e


def test_ready_without_database_storage_or_admin(stateless_rag):
    health = stateless_rag.client.get("/health")
    ready = stateless_rag.client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-e2e-key"}])
@pytest.mark.parametrize("method, path, payload", [
    ("POST", "/api/v1/rag/search", {"query": "test"}),
    ("POST", "/api/v1/rag/files", {
        "presigned_url": "http://127.0.0.1/not-requested.txt",
        "s3_url": "s3://caller-owned/not-requested.txt",
    }),
    ("DELETE", "/api/v1/rag/files/not-indexed", None),
])
def test_business_api_rejects_missing_or_wrong_key(stateless_rag, headers, method, path, payload):
    response = stateless_rag.client.request(method, path, json=payload, headers=headers)

    assert response.status_code == 401


def _index(client, document, file_id=None):
    payload = dict(document)
    if file_id is not None:
        payload["file_id"] = file_id
    response = client.post("/api/v1/rag/files", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"success", "error", "service", "retryable", "traceId", "file_id"}
    assert body["error"] is None
    assert body["success"] is True
    assert body["retryable"] is False
    assert len(body["traceId"]) == 32
    assert body["file_id"]
    if file_id is not None:
        assert body["file_id"] == file_id
    return body["file_id"]


def _search(client, file_id=None):
    payload = {"query": "retrieval document", "top_k": 50, "mode": "dense", "rerank": False}
    if file_id is not None:
        payload["file_ids"] = [file_id]
    response = client.post("/api/v1/rag/search", json=payload)
    assert response.status_code == 200
    assert response.json()["mode"] == "dense"
    return response.json()["results"]


def test_first_index_search_isolation_update_and_delete_without_database(stateless_rag):
    app_a, app_b = stateless_rag.apps
    original_text = "original_alpha retrieval document. " * 30
    other_text = "isolated_beta retrieval document."
    updated_text = "replacement_gamma retrieval document."
    original = stateless_rag.document("original.txt", original_text)
    other = stateless_rag.document("other.txt", other_text)
    updated = stateless_rag.document("updated.txt", updated_text)

    # Neither app has an explicitly created collection; the first HTTP index must ensure it.
    file_id = _index(app_a, original)
    assert str(uuid.UUID(file_id)) == file_id
    initial = _search(app_a, file_id)
    assert len(initial) > 1
    assert all(item["content"] in original_text for item in initial)
    assert any("original_alpha" in item["content"] for item in initial)
    initial_chunks = {(item["id"], item["content"]) for item in initial}
    assert _search(app_b, file_id) == []

    # Reuse the same file ID across apps so isolation cannot pass on IDs alone.
    _index(app_b, other, file_id)
    own_a = _search(app_a)
    own_b = _search(app_b)
    assert {(item["id"], item["content"]) for item in own_a} == initial_chunks
    assert len(own_b) == 1
    assert own_b[0]["content"] == other_text

    _index(app_a, updated, file_id)
    replaced = _search(app_a, file_id)
    assert len(replaced) == 1
    assert replaced[0]["content"] == updated_text
    assert _search(app_b, file_id)[0]["content"] == other_text

    deleted = app_a.delete(f"/api/v1/rag/files/{file_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_chunks"] == 1
    assert _search(app_a, file_id) == []
    assert _search(app_b, file_id)[0]["content"] == other_text
    deleted_again = app_a.delete(f"/api/v1/rag/files/{file_id}")
    assert deleted_again.status_code == 200
    assert deleted_again.json() == {"deleted_chunks": 0}

    with httpx.Client(timeout=10, trust_env=False) as source:
        response = source.get(updated["presigned_url"])
    assert response.status_code == 200
    assert response.text == updated_text


def test_admin_login_unavailable_without_admin_secret(stateless_rag):
    response = stateless_rag.client.post(
        "/api/rag/login", json={"username": "unused-admin", "password": "unused-password"},
    )

    assert response.status_code == 503


def test_admin_api_rejects_jwt_signed_with_empty_admin_secret(stateless_rag):
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = encode(json.dumps({"type": "admin", "app_id": ""}).encode())
    signing_input = f"{header}.{payload}"
    signature = hmac.new(hashlib.sha256(b"").digest(), signing_input.encode(), hashlib.sha256).digest()
    token = f"{signing_input}.{encode(signature)}"

    response = stateless_rag.client.get(
        "/api/rag/config", headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "admin authentication is unavailable"}
