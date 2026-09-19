import httpx
import pytest

from services.rag.clients.inference.http import HttpInferenceClient


pytestmark = pytest.mark.unit


@pytest.mark.parametrize("sparse,rerank", [(False, False), (True, False), (False, True), (True, True)])
def test_clients_follow_inference_capabilities(sparse, rerank):
    client = HttpInferenceClient("http://inference:7001")
    client.dense._client.close()
    client.dense._client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"status": "ready", "capabilities": {"dense": True, "sparse": sparse, "rerank": rerank}},
    )))
    try:
        client.start()
        assert (client.sparse is not None) == sparse
        assert (client.rerank is not None) == rerank
    finally:
        client.close()


def test_upstream_error_survives_inference_hop():
    from shared.upstream import UpstreamServiceError

    detail = {
        "traceId": "a" * 32,
        "error": "upstream billing authorization is insufficient", "retryable": False,
        "service": "inference",
    }
    client = HttpInferenceClient("http://inference:7001")
    client.dense._client.close()
    client.dense._client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(502, json=detail),
    ))
    try:
        with pytest.raises(UpstreamServiceError) as caught:
            client.dense.embed_query("dimension probe")
        assert caught.value.detail() == detail
        assert caught.value.status_code == 502
    finally:
        client.close()
