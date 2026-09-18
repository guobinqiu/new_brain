import json

import httpx
import pytest
import yaml


pytestmark = pytest.mark.unit


@pytest.fixture
def make_client():
    from services.inference.app.config import VllmConfig
    from services.inference.providers.vllm import VllmInferenceClient

    clients = []

    def make(handler, **kwargs):
        dense_url = kwargs.pop("dense_url", "http://vllm-dense:8000")
        dense_model = kwargs.pop("dense_model", "BAAI/bge-m3")
        rerank_url = kwargs.pop("rerank_url", "http://vllm-rerank:8000")
        rerank_model = kwargs.pop("rerank_model", "BAAI/bge-reranker-v2-m3")
        config = VllmConfig(
            dense_url=dense_url,
            dense_model=dense_model,
            rerank_url=rerank_url,
            rerank_model=rerank_model,
            dense_timeout=12.0,
            rerank_timeout=7.0,
            **kwargs,
        )
        client = VllmInferenceClient(config, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def test_vllm_config_selects_enabled_dense_and_optional_rerank(tmp_path, monkeypatch):
    from services.inference.app.config import load_inference_config

    monkeypatch.setenv("VLLM_TIMEOUT", "1")
    path = tmp_path / "inference.yaml"
    path.write_text(yaml.safe_dump({
        "vllm": {
            "enable": True,
            "retry": {"max_attempts": 3, "interval_seconds": 0.5},
            "dense": {
                "bge_m3": {
                    "enable": True,
                    "model_name": "BAAI/bge-m3",
                    "base_url": "http://vllm-dense:8000",
                    "dimensions": 1024,
                    "timeout": 95,
                },
            },
            "rerank": {
                "bge_m3": {
                    "enable": True,
                    "model_name": "BAAI/bge-reranker-v2-m3",
                    "base_url": "http://vllm-rerank:8000",
                    "timeout": 35,
                },
            },
        },
    }), encoding="utf-8")

    config = load_inference_config(path)

    assert config.vllm is not None
    assert config.vllm.dense_url == "http://vllm-dense:8000"
    assert config.vllm.dense_model == "BAAI/bge-m3"
    assert config.vllm.dimensions == 1024
    assert config.vllm.rerank_url == "http://vllm-rerank:8000"
    assert config.vllm.rerank_model == "BAAI/bge-reranker-v2-m3"
    assert config.vllm.dense_timeout == 95.0
    assert config.vllm.rerank_timeout == 35.0
    assert config.vllm.retry.max_attempts == 3
    assert config.vllm.retry.interval_seconds == 0.5


def test_dense_uses_vllm_openai_embeddings_endpoint(make_client):
    def handler(request):
        assert str(request.url) == "http://vllm-dense:8000/v1/embeddings"
        assert request.extensions["timeout"]["read"] == 12.0
        assert json.loads(request.content) == {"input": ["a", "b"], "model": "BAAI/bge-m3", "encoding_format": "float"}
        return httpx.Response(200, json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 1, "embedding": [0.3, 0.4]},
                {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]},
            ],
            "model": "BAAI/bge-m3",
        })

    client = make_client(handler, dimensions=2)

    assert client.dense.embed_documents(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert client.dense.vector_size == 2


def test_dense_query_uses_single_input_string(make_client):
    def handler(request):
        assert str(request.url) == "http://vllm-dense:8000/v1/embeddings"
        assert json.loads(request.content) == {"input": "q", "model": "BAAI/bge-m3", "encoding_format": "float"}
        return httpx.Response(200, json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 0, "embedding": [0.5, 0.6]},
            ],
            "model": "BAAI/bge-m3",
        })

    client = make_client(handler, dimensions=2)

    assert client.dense.embed_query("q") == [0.5, 0.6]


def test_rerank_uses_vllm_v1_rerank_endpoint(make_client):
    items = [{"content": "a", "id": "a"}, {"content": "b", "metadata": {"page": 2}}]

    def handler(request):
        assert str(request.url) == "http://vllm-rerank:8000/v1/rerank"
        assert json.loads(request.content) == {
            "query": "q",
            "documents": ["a", "b"],
            "model": "BAAI/bge-reranker-v2-m3",
        }
        return httpx.Response(200, json={
            "id": "score-test",
            "model": "BAAI/bge-reranker-v2-m3",
            "results": [
                {"index": 1, "document": {"text": "b"}, "relevance_score": 0.9},
            ],
        })

    client = make_client(handler)

    assert client.rerank.rerank("q", items, 1) == [
        {"content": "b", "metadata": {"page": 2}, "_score": 0.9},
    ]
    assert "_score" not in items[1]


def test_rerank_accepts_full_sorted_rows_and_applies_top_k(make_client):
    items = [{"content": "a"}, {"content": "b"}]

    def handler(request):
        return httpx.Response(200, json={
            "id": "score-test",
            "model": "BAAI/bge-reranker-v2-m3",
            "results": [
                {"index": 0, "document": {"text": "a"}, "relevance_score": 0.99},
                {"index": 1, "document": {"text": "b"}, "relevance_score": 0.01},
            ],
        })

    client = make_client(handler)

    assert client.rerank.rerank("q", items, 1) == [
        {"content": "a", "_score": 0.99},
    ]


def test_rerank_can_be_disabled(make_client):
    client = make_client(lambda request: httpx.Response(500), rerank_model=None, rerank_url=None)

    assert client.rerank is None
    assert client.ping()
