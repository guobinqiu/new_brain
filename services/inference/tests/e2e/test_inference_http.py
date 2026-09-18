import math
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from services.inference.app.config import load_inference_config
from shared.paths import PROJECT_ROOT


pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def inference_http(tmp_path_factory):
    env = dict(os.environ, SERVICE_API_KEY="inference-e2e-key")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        log_path = tmp_path_factory.mktemp("inference-http") / "server.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "services.inference.app.main:app", "--fd", str(listener.fileno())],
                cwd=PROJECT_ROOT, env=env, pass_fds=(listener.fileno(),), stdout=log, stderr=log,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60, trust_env=False) as client:
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            pytest.fail(f"Inference exited during startup: {log_path.read_text()}")
                        try:
                            if client.get("/ready", timeout=1).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.2)
                    else:
                        pytest.fail(f"Inference startup timed out: {log_path.read_text()}")
                    yield client
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def test_health_and_ready(inference_http):
    config = load_inference_config()

    health = inference_http.get("/health")
    ready = inference_http.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "capabilities": {
            "dense": True,
            "sparse": config.sparse is not None or bool(config.volcengine and config.volcengine.sparse_model),
            "rerank": config.rerank is not None or bool(config.siliconflow and config.siliconflow.rerank_model)
            or bool(config.volcengine and config.volcengine.rerank_model)
            or bool(config.tei and config.tei.rerank_model)
            or bool(config.vllm and config.vllm.rerank_model),
        },
    }


@pytest.mark.parametrize("input_value", ["hello", ["hello", "world"]])
def test_embeddings_returns_real_vectors(inference_http, input_value):
    response = inference_http.post(
        "/v1/embeddings", json={"input": input_value, "model": "local-dense"},
        headers={"Authorization": "Bearer inference-e2e-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["model"] == "local-dense"
    assert len(body["data"]) == (1 if isinstance(input_value, str) else len(input_value))
    dimensions = set()
    for index, item in enumerate(body["data"]):
        assert item["object"] == "embedding"
        assert item["index"] == index
        vector = item["embedding"]
        assert vector
        assert all(math.isfinite(value) for value in vector)
        assert any(value != 0 for value in vector)
        dimensions.add(len(vector))
    assert len(dimensions) == 1


@pytest.mark.parametrize("path, payload", [
    ("/v1/embeddings", {"input": "hello"}),
    ("/v1/sparse_embeddings", {"input": ["hello"]}),
    ("/v1/rerank", {"query": "hello", "documents": ["hello"]}),
])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong-key"}])
def test_inference_requires_service_api_key(inference_http, path, payload, headers):
    response = inference_http.post(path, json=payload, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"error": "invalid service api key", "retryable": False, "traceId": response.json()["traceId"]}


def test_sparse_embeddings(inference_http):
    response = inference_http.post(
        "/v1/sparse_embeddings", json={"input": ["hello world"], "model": "local-sparse"},
        headers={"Authorization": "Bearer inference-e2e-key"},
    )

    config = load_inference_config()
    if config.sparse is None and not (config.volcengine and config.volcengine.sparse_model):
        assert response.status_code == 404
        assert response.json() == {"error": "sparse embedding is not enabled", "retryable": False, "traceId": response.json()["traceId"]}
        return

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["model"] == "local-sparse"
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert item["object"] == "sparse_embedding"
    assert item["index"] == 0
    assert item["indices"]
    assert len(item["indices"]) == len(item["values"])
    assert all(isinstance(index, int) and index >= 0 for index in item["indices"])
    assert all(math.isfinite(value) and value > 0 for value in item["values"])


def test_rerank(inference_http):
    documents = ["hello world", "a recipe for soup"]
    response = inference_http.post(
        "/v1/rerank", json={"query": "hello world", "documents": documents, "top_k": 1},
        headers={"Authorization": "Bearer inference-e2e-key"},
    )

    config = load_inference_config()
    if (
        config.rerank is None
        and not (config.siliconflow and config.siliconflow.rerank_model)
        and not (config.volcengine and config.volcengine.rerank_model)
        and not (config.tei and config.tei.rerank_model)
        and not (config.vllm and config.vllm.rerank_model)
    ):
        assert response.status_code == 404
        assert response.json() == {"error": "rerank is not enabled", "retryable": False, "traceId": response.json()["traceId"]}
        return

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    result = results[0]
    assert 0 <= result["index"] < len(documents)
    assert result["document"] == {"text": documents[result["index"]]}
    assert math.isfinite(result["relevance_score"])
    assert result["relevance_score"] >= 0
