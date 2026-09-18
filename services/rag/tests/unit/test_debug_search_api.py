import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from services.rag.core.api.schemas import DebugEncodeRequest, DebugSearchRequest
from services.rag.core.api.services import search as service
from services.rag.core.auth import Principal


pytestmark = pytest.mark.unit


class DebugDense:
    ready = True

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class DebugVector:
    ready = True

    def __init__(self):
        self.calls = []

    def app_collection_exists(self, app_id):
        return True

    def app_scope(self, app_id):
        from contextlib import nullcontext

        self.calls.append(("app_scope", app_id))
        return nullcontext()

    def build_file_filter(self, file_ids=None):
        self.calls.append(("build_file_filter", tuple(file_ids or [])))
        return ("file-filter", tuple(file_ids or []))

    def search_dense(self, query, limit, metadata_filter):
        self.calls.append(("search_dense", query, limit, metadata_filter))
        return [
            {
                "id": "dense-1",
                "content": "dense content",
                "metadata": {"file_id": "file-a", "chunk_index": 1},
                "_score": 0.8,
            }
        ]

    def query_dense_vector(self, query_vector, limit, metadata_filter):
        self.calls.append(("query_dense_vector", query_vector, limit, metadata_filter))
        return [
            {
                "id": "dense-1",
                "content": "dense content",
                "metadata": {"file_id": "file-a", "chunk_index": 1},
                "_score": 0.8,
            }
        ]

def _state(*, vector=None):
    from shared.config import AdminAuthConfig, AppConfig, AuthConfig, SearchConfig, ServiceClientConfig, ServiceClientsConfig, VectorServiceConfig

    config = AppConfig(
        search=SearchConfig(),
        auth=AuthConfig(admin=AdminAuthConfig(username="admin", password="admin123")),
        services=ServiceClientsConfig(
            parser=ServiceClientConfig(base_url="http://parser:7000"),
            inference=ServiceClientConfig(base_url="http://inference:7001"),
            vector=VectorServiceConfig(provider="qdrant", base_url="http://qdrant:6333"),
        ),
    )

    state = FastAPI().state
    state.config = config
    state.ready = True
    state.inference_client = type("Inference", (), {"dense": DebugDense()})()
    state.vector_client = vector or DebugVector()
    return state


def test_debug_dense_search_encodes_query_and_searches_dense(monkeypatch):
    vector = DebugVector()
    state = _state(vector=vector)

    body = service.debug_dense_search(
        state,
        "tenant_a",
        DebugSearchRequest(query="表见代理", top_k=3, file_ids=["file-a"]),
        Principal(type="admin", app_id=""),
    )

    assert body["type"] == "dense"
    assert body["query_vector"] == [0.1, 0.2, 0.3]
    assert body["results"][0]["id"] == "dense-1"
    assert vector.calls == [
        ("build_file_filter", ("file-a",)),
        ("app_scope", "tenant_a"),
        ("query_dense_vector", [0.1, 0.2, 0.3], 3, ("file-filter", ("file-a",))),
    ]


def test_debug_dense_encode_only_encodes_query(monkeypatch):
    state = _state()

    body = service.debug_dense_encode(
        state,
        "tenant_a",
        DebugEncodeRequest(query="表见代理"),
        Principal(type="admin", app_id=""),
    )

    assert body == {
        "type": "dense",
        "query": "表见代理",
        "query_vector": [0.1, 0.2, 0.3],
    }
    assert state.vector_client.calls == []


def test_debug_search_accepts_top_k_up_to_100(monkeypatch):
    vector = DebugVector()
    state = _state(vector=vector)

    service.debug_dense_search(
        state,
        "tenant_a",
        DebugSearchRequest(query="表见代理", top_k=100),
        Principal(type="admin", app_id=""),
    )

    assert vector.calls[-1] == ("query_dense_vector", [0.1, 0.2, 0.3], 100, ("file-filter", ()))


def test_debug_search_rejects_top_k_over_100():
    with pytest.raises(ValidationError):
        DebugSearchRequest(query="表见代理", top_k=101)
