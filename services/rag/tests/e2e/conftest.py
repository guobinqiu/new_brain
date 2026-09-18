import uuid

import httpx
import pytest

from services.inference.tests.e2e.helpers import cloud_inference_server
from services.rag.tests.e2e.helpers import AppApiClient, authenticated_client, isolated_rag_server


@pytest.fixture(scope="session")
def rag_server(tmp_path_factory):
    with isolated_rag_server(tmp_path_factory.mktemp("rag-e2e")) as server:
        yield server


@pytest.fixture
def api_client(rag_server):
    with authenticated_client(rag_server) as client:
        yield client


@pytest.fixture
def anonymous_api_client(rag_server):
    with httpx.Client(base_url=rag_server.base_url, timeout=180, trust_env=False) as client:
        yield client


@pytest.fixture
def app_api_client(api_client):
    app_id = "e2e_" + uuid.uuid4().hex
    created = api_client.post("/api/rag/apps", json={"app_id": app_id})
    assert created.status_code == 201
    try:
        initialized = api_client.post(f"/api/rag/apps/{app_id}/database")
        assert initialized.status_code == 200, initialized.text
        yield AppApiClient(api_client, app_id, created.json()["api_key"])
    finally:
        try:
            dropped = api_client.delete(f"/api/rag/apps/{app_id}/database")
            assert dropped.status_code in (200, 404), dropped.text
        finally:
            deleted = api_client.delete(f"/api/rag/apps/{app_id}")
            assert deleted.status_code == 200


@pytest.fixture(params=["qdrant_cloud", "milvus_cloud"])
def cloud_server(request, tmp_path):
    with cloud_inference_server(tmp_path, "siliconflow-intl") as inference_url, isolated_rag_server(
        tmp_path, vector_backend=request.param, rerank=True, inference_url=inference_url,
    ) as server:
        with authenticated_client(server) as client:
            yield client
