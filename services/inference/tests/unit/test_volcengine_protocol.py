import hashlib
import json

import httpx
import pytest

from services.inference.app.config import VolcengineConfig
from shared.config import RetryConfig
from shared.upstream import UpstreamServiceError


@pytest.fixture
def make_client():
    from services.inference.providers.volcengine import VolcengineInferenceClient

    clients = []

    def make(handler, rerank_model="m3-v2-rerank", sparse_model=None):
        config = VolcengineConfig(
            base_url="https://ark.cn-beijing.volces.com/api/v3", api_key="test-ark",
            dense_model="doubao-embedding-vision-251215", dimensions=1024, rerank_model=rerank_model,
            rerank_base_url="https://api-knowledgebase.mlp.cn-beijing.volces.com",
            region="cn-beijing", access_key="test-ak", secret_key="test-sk",
            dense_timeout=12, sparse_timeout=13, rerank_timeout=15,
            sparse_model=sparse_model,
            retry=RetryConfig(max_attempts=1),
        )
        client = VolcengineInferenceClient(config, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def test_dense_uses_ark_and_preserves_input_order(make_client):
    inputs = iter(["中文", "English", "query"])
    vectors = {"中文": [0.1] * 1024, "English": [0.3] * 1024, "query": [0.5] * 1024}

    def handler(request):
        assert str(request.url) == "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
        assert request.headers["authorization"] == "Bearer test-ark"
        assert "traceparent" not in request.headers
        assert request.extensions["timeout"]["read"] == 12
        body = json.loads(request.content)
        assert body["model"] == "doubao-embedding-vision-251215"
        assert body["encoding_format"] == "float"
        assert body["dimensions"] == 1024
        assert "sparse_embedding" not in body
        text = next(inputs)
        assert body["input"] == [{"type": "text", "text": text}]
        return httpx.Response(200, json={"data": {"embedding": vectors[text]}})

    client = make_client(handler)
    assert client.dense.embed_documents(["中文", "English"]) == [vectors["中文"], vectors["English"]]
    assert client.dense.embed_query("query") == vectors["query"]


def test_sparse_converts_provider_entries_for_documents_and_queries(make_client):
    texts = iter(["中文", "English", "query"])

    def handler(request):
        assert request.url.path == "/api/v3/embeddings/multimodal"
        assert request.headers["authorization"] == "Bearer test-ark"
        assert "traceparent" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "doubao-embedding-vision-251215"
        assert body["input"] == [{"type": "text", "text": next(texts)}]
        assert body["sparse_embedding"] == {"type": "enabled"}
        return httpx.Response(200, json={"data": {
            "embedding": [0.1] * 2048,
            "sparse_embedding": [{"index": 2684, "value": 0.2}, {"index": 1296, "value": 0.4}],
        }})

    client = make_client(handler, sparse_model="doubao-embedding-vision-251215")
    assert client.sparse.embed_documents(["中文", "English"]) == [{2684: 0.2, 1296: 0.4}] * 2
    assert client.sparse.embed_query("query") == {2684: 0.2, 1296: 0.4}
    client.close()
    assert not client.sparse.ready and client.sparse._client.is_closed


def test_embedding_helpers_accept_single_text_and_text_lists(make_client):
    texts = iter(["query", "doc-1", "doc-2", "keyword", "term-1", "term-2"])

    def handler(request):
        body = json.loads(request.content)
        text = next(texts)
        assert body["input"] == [{"type": "text", "text": text}]
        if "sparse_embedding" in body:
            return httpx.Response(200, json={"data": {
                "sparse_embedding": [{"index": len(text), "value": 1.0}],
            }})
        return httpx.Response(200, json={"data": {"embedding": [float(len(text))] * 1024}})

    client = make_client(handler, sparse_model="doubao-embedding-vision-251215")
    assert client.dense._create_dense_embeddings("query") == [[5.0] * 1024]
    assert client.dense._create_dense_embeddings(["doc-1", "doc-2"]) == [[5.0] * 1024, [5.0] * 1024]
    assert client.sparse._create_sparse_embeddings("keyword") == [{7: 1.0}]
    assert client.sparse._create_sparse_embeddings(["term-1", "term-2"]) == [{6: 1.0}, {6: 1.0}]


def test_volcengine_clients_are_exported_from_provider_modules():
    from services.inference.providers.volcengine.client import VolcengineInferenceClient
    from services.inference.providers.volcengine.dense import VolcengineDenseClient
    from services.inference.providers.volcengine.rerank import VikingRerankClient
    from services.inference.providers.volcengine.sparse import VolcengineSparseClient

    assert VolcengineInferenceClient.__name__ == "VolcengineInferenceClient"
    assert VolcengineDenseClient.__name__ == "VolcengineDenseClient"
    assert VolcengineSparseClient.__name__ == "VolcengineSparseClient"
    assert VikingRerankClient.__name__ == "VikingRerankClient"


def test_sparse_batch_stops_at_provider_failure(make_client):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content)["input"][0]["text"])
        if len(calls) == 1:
            return httpx.Response(200, json={"data": {"sparse_embedding": []}})
        return httpx.Response(429, json={"error": {
            "code": "RateLimitExceeded.EndpointRPMExceeded", "message": "limited",
        }})

    client = make_client(handler, sparse_model="doubao-embedding-vision-251215")
    with pytest.raises(UpstreamServiceError) as caught:
        client.sparse.embed_documents(["a", "b", "c"])
    assert caught.value.retryable is False
    assert calls == ["a", "b"]


@pytest.mark.parametrize("model", ["m3-v2-rerank", "base-multilingual-rerank"])
def test_rerank_signs_actual_body_and_sorts_scores(make_client, model):
    def handler(request):
        assert str(request.url) == "https://api-knowledgebase.mlp.cn-beijing.volces.com/api/knowledge/service/rerank"
        assert request.headers["authorization"].startswith("HMAC-SHA256 Credential=test-ak/")
        assert "/cn-beijing/air/request" in request.headers["authorization"]
        assert request.headers["x-content-sha256"] == hashlib.sha256(request.content).hexdigest()
        assert "traceparent" not in request.headers
        assert request.extensions["timeout"]["read"] == 15
        assert json.loads(request.content) == {
            "rerank_model": model,
            "datas": [{"query": "查询", "content": "a"}, {"query": "查询", "content": "b"}],
        }
        return httpx.Response(200, json={"code": 0, "data": {"scores": [0.1, 0.9]}})

    items = [{"content": "a", "id": "a"}, {"content": "b", "id": "b"}]
    assert make_client(handler, model).rerank.rerank("查询", items, 1) == [
        {"content": "b", "id": "b", "_score": 0.9},
    ]
    assert "_score" not in items[1]


@pytest.mark.parametrize("operation,status,body,retryable", [
    ("dense", 429, {"error": {"code": "RateLimitExceeded.EndpointRPMExceeded", "message": "limited"}}, False),
    ("dense", 429, {"error": {"code": "QuotaExceeded", "message": "quota"}}, False),
    ("dense", 404, {"error": {"code": "ModelNotOpen", "message": "not open"}}, False),
    ("rerank", 500, {"code": 1000028, "message": "overloaded"}, True),
    ("rerank", 429, {"code": 300004, "message": "quota"}, False),
    ("rerank", 200, {"code": 1000003, "message": "invalid"}, False),
])
def test_provider_errors_are_normalized_without_retry(make_client, operation, status, body, retryable, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers={"x-request-id": "provider-id"})

    client = make_client(handler)
    with caplog.at_level("ERROR"), pytest.raises(UpstreamServiceError) as caught:
        if operation == "dense":
            client.dense.embed_query("q")
        else:
            client.rerank.rerank("q", [{"content": "a"}], 1)
    assert caught.value.error == body.get("error", body)["message"]
    assert caught.value.retryable is retryable
    assert len(calls) == 1
    record = next(row for row in caplog.records if row.name == "services.inference.providers.volcengine")
    assert record.provider_request_id == "provider-id"
    assert record.error == caught.value.error
    assert record.elapsed_ms >= 0


@pytest.mark.parametrize("operation,body", [
    ("dense", {"data": []}),
    ("dense", {"data": {"embedding": []}}),
    ("dense", {"data": {"embedding": [0.1] * 2048}}),
    ("rerank", {"code": 0, "data": {"scores": [0.2]}}),
    ("rerank", {"code": 0, "data": {"scores": ["bad", 0.2]}}),
])
def test_incomplete_provider_results_fail(make_client, operation, body):
    client = make_client(lambda request: httpx.Response(200, json=body))
    with pytest.raises(UpstreamServiceError) as caught:
        if operation == "dense":
            client.dense.embed_documents(["a", "b"])
        else:
            client.rerank.rerank("q", [{"content": "a"}, {"content": "b"}], 2)
    assert caught.value.retryable is False


@pytest.mark.parametrize("operation", ["dense", "rerank"])
def test_timeout_is_retryable_without_internal_retry(make_client, operation):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    client = make_client(handler)
    with pytest.raises(UpstreamServiceError) as caught:
        if operation == "dense":
            client.dense.embed_query("q")
        else:
            client.rerank.rerank("q", [{"content": "a"}], 1)
    assert caught.value.retryable is True
    assert caught.value.status_code == 504
    assert len(calls) == 1


def test_readiness_does_not_call_provider_and_close_releases_http_client(make_client):
    def handler(request):
        pytest.fail("readiness must not call provider")

    client = make_client(handler, rerank_model=None)
    assert client.ping() and client.dense.ready
    assert client.rerank is None and client.sparse is None
    client.close()
    assert not client.ping()
    assert client.dense._client.is_closed
