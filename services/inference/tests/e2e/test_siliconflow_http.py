import math

import httpx
import pytest

from services.inference.tests.e2e.helpers import cloud_inference_server


pytestmark = pytest.mark.e2e


def test_siliconflow_through_inference_service(tmp_path):
    with cloud_inference_server(tmp_path, "siliconflow-intl") as address, httpx.Client(
        base_url=address, timeout=120, trust_env=False,
        headers={"Authorization": "Bearer inference-e2e-key"},
    ) as client:
        assert client.get("/ready").json()["capabilities"] == {
            "dense": True, "sparse": False, "rerank": True,
        }
        response = client.post("/v1/embeddings", json={
            "input": ["Paris is the capital of France.", "Bread is baked in an oven."],
        })
        assert response.status_code == 200, response.text
        vectors = [row["embedding"] for row in response.json()["data"]]
        assert len(vectors) == 2
        assert len(vectors[0]) == len(vectors[1]) > 0
        assert vectors[0] != vectors[1]
        assert all(math.isfinite(value) for vector in vectors for value in vector)
        response = client.post("/v1/rerank", json={
            "query": "What is the capital of France?",
            "documents": ["Bread is baked in an oven.", "Paris is the capital of France."],
            "top_k": 1,
        })
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["index"] == 1
        assert client.post("/v1/sparse_embeddings", json={"input": "Paris"}).status_code == 404
