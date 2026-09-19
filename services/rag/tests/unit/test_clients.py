import json

import httpx
import pytest

from shared.tracing import set_traceparent, reset_traceparent
from shared.upstream import UpstreamServiceError
from services.rag.clients.inference import HttpDenseClient, HttpRerankClient, HttpSparseClient
from services.rag.clients.parser import HttpParserClient


@pytest.mark.parametrize("status,retryable", [(401, False), (403, False), (429, False)])
def test_cloud_http_errors_are_actionable(status, retryable):
    from shared.upstream import upstream_error

    response = httpx.Response(status, request=httpx.Request("POST", "https://cloud.example/v1/embeddings"))
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()
    error = upstream_error("inference", caught.value)
    assert error.status_code == 502
    assert error.retryable is retryable


def test_http_parser_client_parses_file(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("hello parser", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/parse/file"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {"presigned_url": "https://source/a.txt", "filename": "a.txt"}
        return httpx.Response(200, json={"blocks": [{"type": "text", "text": "hello"}], "file_size": 5})

    client = HttpParserClient("http://parser:7000", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    result = client.parse_file("https://source/a.txt", filename="a.txt")

    assert result == {"blocks": [{"type": "text", "text": "hello", "kind": "text"}], "file_size": 5}


def test_http_parser_client_forwards_service_auth_and_traceparent(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("hello parser", encoding="utf-8")
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer service-key"
        assert request.headers["traceparent"] == traceparent
        return httpx.Response(200, json={"blocks": []})

    token = set_traceparent(traceparent)
    try:
        client = HttpParserClient(
            "http://parser:7000",
            api_key="service-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        assert client.parse_file("https://source/a.txt", filename="a.txt") == {"blocks": []}
    finally:
        reset_traceparent(token)


def test_http_parser_client_maps_network_error_to_upstream_error(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("hello parser", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = HttpParserClient("http://parser:7000", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        client.parse_file("https://source/a.txt", filename="a.txt")
    except UpstreamServiceError as exc:
        assert exc.status_code == 503
        assert exc.retryable is True
    else:
        raise AssertionError("expected UpstreamServiceError")


def test_http_dense_client_uses_openai_embeddings_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content)["input"] == ["hello"]
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}]})

    dense = HttpDenseClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert dense.embed_documents(["hello"]) == [[0.1, 0.2]]


def test_http_dense_client_sends_query_as_single_input_string():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content)["input"] == "hello"
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2], "index": 0}]})

    dense = HttpDenseClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert dense.embed_query("hello") == [0.1, 0.2]


def test_http_sparse_client_uses_sparse_embeddings_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/sparse_embeddings"
        assert json.loads(request.content)["input"] == ["hello"]
        return httpx.Response(200, json={"data": [{"indices": [1, 8], "values": [0.5, 1.0], "index": 0}]})

    sparse = HttpSparseClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert sparse.embed_documents(["hello"]) == [{1: 0.5, 8: 1.0}]


def test_http_dense_client_forwards_service_auth_and_traceparent():
    traceparent = "00-11111111111111111111111111111111-2222222222222222-01"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer service-key"
        assert request.headers["traceparent"] == traceparent
        return httpx.Response(200, json={"data": [{"embedding": [0.1], "index": 0}]})

    token = set_traceparent(traceparent)
    try:
        dense = HttpDenseClient(
            "http://inference:7001",
            api_key="service-key",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        assert dense.embed_documents(["hello"]) == [[0.1]]
    finally:
        reset_traceparent(token)


def test_http_dense_client_maps_timeout_to_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    dense = HttpDenseClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        dense.embed_documents(["hello"])
    except UpstreamServiceError as exc:
        assert exc.status_code == 504
        assert exc.retryable is True
    else:
        raise AssertionError("expected UpstreamServiceError")


def test_http_dense_client_start_does_not_probe_inference_service():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    dense = HttpDenseClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    dense.start()

    assert dense.ready is True
    assert requests == []


def test_http_dense_dimension_uses_models_endpoint_and_caches():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"dense": {"model_name": "test", "dimensions": 1024}})

    dense = HttpDenseClient("http://inference", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        assert dense.vector_size == 1024
        assert dense.vector_size == 1024
        assert len(requests) == 1
    finally:
        dense.close()


def test_http_rerank_client_maps_documents_to_items():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/rerank"
        assert json.loads(request.content)["documents"] == ["a", "b"]
        return httpx.Response(200, json={"results": [{"index": 1, "document": {"text": "b"}, "relevance_score": 0.9}]})

    rerank = HttpRerankClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert rerank.rerank("q", [{"content": "a"}, {"content": "b"}], 1) == [{"content": "b", "_score": 0.9}]


def test_http_rerank_client_maps_http_error_to_upstream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom", "retryable": False, "traceId": "a" * 32})

    rerank = HttpRerankClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        rerank.rerank("q", [{"content": "a"}], 1)
    except UpstreamServiceError as exc:
        assert exc.status_code == 500
        assert exc.retryable is False
    else:
        raise AssertionError("expected UpstreamServiceError")


def test_http_rerank_client_maps_disabled_rerank_to_actionable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "rerank is not enabled"})

    rerank = HttpRerankClient("http://inference:7001", http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    try:
        rerank.rerank("q", [{"content": "a"}], 1)
    except UpstreamServiceError as exc:
        assert exc.error == "rerank is not enabled in inference service"
        assert exc.status_code == 400
        assert exc.retryable is False
    else:
        raise AssertionError("expected UpstreamServiceError")
