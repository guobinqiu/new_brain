import asyncio
import json
from types import SimpleNamespace

import pytest

from services.inference.app.main import (
    EmbeddingsRequest, RerankRequest, app, dense_embeddings, sparse_embeddings,
    rerank, upstream_exception_handler,
)
from shared.upstream import UpstreamServiceError


@pytest.mark.parametrize("operation", ["dense", "sparse", "rerank"])
@pytest.mark.parametrize("failure", [RuntimeError, ValueError, TypeError, KeyError])
def test_model_failure_is_safe_upstream_error(monkeypatch, operation, failure):
    calls = []

    def fail(*args):
        calls.append(args)
        raise failure("private-document private-key")

    monkeypatch.setattr(app.state, operation, SimpleNamespace(ready=True, embed_query=fail, rerank=fail), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        _invoke(operation)
    error = caught.value
    assert error.service == "inference"
    assert error.status_code == 502
    assert error.retryable is False
    assert error.error == str(failure("private-document private-key"))
    assert len(calls) == 1
    response = asyncio.run(upstream_exception_handler(None, error))
    assert response.status_code == 502
    assert json.loads(response.body) == error.detail()


@pytest.mark.parametrize("operation, output", [
    ("dense", None), ("dense", ["private-document"]),
    ("dense", [float("nan")]),
    ("sparse", None), ("sparse", {"private-key": "private-document"}),
    ("sparse", {1: float("inf")}),
    ("rerank", None), ("rerank", [{}]),
    ("rerank", [{"content": "private-document", "_score": "private-key"}]),
    ("rerank", [{"content": "private-document", "_score": float("nan")}]),
])
def test_invalid_model_output_is_normalized(monkeypatch, operation, output):
    result = lambda *args: output
    monkeypatch.setattr(app.state, operation, SimpleNamespace(ready=True, embed_query=result, rerank=result), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        _invoke(operation)
    assert caught.value.status_code == 502
    assert caught.value.retryable is False
    assert caught.value.error


@pytest.mark.parametrize("operation", ["dense", "sparse", "rerank"])
def test_existing_upstream_error_is_preserved(monkeypatch, operation):
    error = UpstreamServiceError(service="inference", error="inference request timed out", retryable=True, status_code=504)

    def fail(*args):
        raise error

    monkeypatch.setattr(app.state, operation, SimpleNamespace(ready=True, embed_query=fail, rerank=fail), raising=False)
    with pytest.raises(UpstreamServiceError) as caught:
        _invoke(operation)
    assert caught.value is error


def _invoke(operation):
    if operation == "rerank":
        return rerank(RerankRequest(query="q", documents=["private-document"]))
    function = dense_embeddings if operation == "dense" else sparse_embeddings
    return function(EmbeddingsRequest(input="private-document"))
