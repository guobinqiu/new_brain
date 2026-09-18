import pytest
from fastapi import HTTPException
from starlette.datastructures import State

from services.inference.app.main import (
    EmbeddingsRequest,
    RerankRequest,
    app,
    dense_embeddings,
    sparse_embeddings,
    health,
    ready,
    rerank,
)
from shared.service_auth import require_service_api_key


pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def inference_state(monkeypatch):
    monkeypatch.setattr(app, "state", State())


def test_inference_health_returns_ok():
    assert health() == {"status": "ok"}


def test_inference_ready_returns_503_until_dense_is_ready():
    with pytest.raises(HTTPException) as exc:
        ready()

    assert exc.value.status_code == 503
    assert exc.value.detail == "inference is not ready"


def test_inference_ready_returns_200_when_dense_is_ready():
    app.state.dense = StaticDense()
    app.state.rerank = StaticRerank()

    assert ready() == {
        "status": "ready",
        "capabilities": {
            "dense": True,
            "sparse": False,
            "rerank": True,
        },
    }


class StaticDense:
    ready = True

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 2.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


class StaticSparse:
    ready = True

    def embed_query(self, text: str) -> dict[int, float]:
        return {1: float(len(text)), 8: 2.0}

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        return [{1: float(len(text)), 8: 1.0} for text in texts]


class StaticRerank:
    ready = True

    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        return [{"content": item["content"], "_score": 1.0 / (index + 1)} for index, item in enumerate(items[:top_k])]


def test_create_dense_embeddings_returns_vectors():
    app.state.dense = StaticDense()

    response = dense_embeddings(
        EmbeddingsRequest(input=["hello", "world"], model="local-dense"),
    )

    body = response.model_dump()
    assert body["object"] == "list"
    assert body["data"][0]["object"] == "embedding"
    assert body["data"][0]["embedding"] == [5.0, 1.0]
    assert body["data"][0]["index"] == 0
    assert body["data"][1] == {"object": "embedding", "embedding": [5.0, 1.0], "index": 1}
    assert body["model"] == "local-dense"


def test_create_dense_embeddings_uses_query_path_for_single_string():
    app.state.dense = StaticDense()

    response = dense_embeddings(
        EmbeddingsRequest(input="hello", model="local-dense"),
    )

    assert response.data[0].embedding == [5.0, 2.0]


@pytest.mark.parametrize("input_value, values", [(["hello"], [5.0, 1.0]), ("hello", [5.0, 2.0])])
def test_create_sparse_embeddings_returns_indices_and_values(input_value, values):
    app.state.sparse = StaticSparse()

    response = sparse_embeddings(EmbeddingsRequest(input=input_value, model="local-sparse"))

    assert response.model_dump() == {
        "object": "list",
        "data": [{"object": "sparse_embedding", "indices": [1, 8], "values": values, "index": 0}],
        "model": "local-sparse",
    }


def test_create_dense_embeddings_does_not_load_model_inside_request(monkeypatch):
    calls = []
    monkeypatch.setattr("services.inference.app.main._load_components", lambda: calls.append("load"))

    with pytest.raises(HTTPException) as exc:
        dense_embeddings(EmbeddingsRequest(input="hello"))

    assert exc.value.status_code == 503
    assert calls == []


@pytest.mark.parametrize("authorization", [None, "Bearer wrong-key", "Basic service-key"])
def test_service_api_key_rejects_missing_or_invalid_key(monkeypatch, authorization):
    monkeypatch.setenv("SERVICE_API_KEY", "service-key")

    with pytest.raises(HTTPException) as exc:
        require_service_api_key(authorization)

    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid service api key"


def test_service_api_key_accepts_configured_key(monkeypatch):
    monkeypatch.setenv("SERVICE_API_KEY", "service-key")

    assert require_service_api_key("Bearer service-key") is None


def test_rerank_returns_ranked_documents():
    app.state.rerank = StaticRerank()

    response = rerank(
        RerankRequest(query="q", documents=["a", "b"], top_k=1),
    )

    assert response.model_dump()["results"] == [{"index": 0, "document": {"text": "a"}, "relevance_score": 1.0}]
