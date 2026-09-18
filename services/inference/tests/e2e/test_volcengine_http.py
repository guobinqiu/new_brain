import math

import httpx
import pytest

from services.inference.tests.e2e.helpers import cloud_inference_server


pytestmark = pytest.mark.e2e


def test_volcengine_embeddings_through_inference_service(tmp_path):
    with cloud_inference_server(tmp_path, "volcengine", rerank=False, sparse=False) as address, httpx.Client(
        base_url=address, timeout=120, trust_env=False,
        headers={"Authorization": "Bearer inference-e2e-key"},
    ) as client:
        assert client.get("/ready").json()["capabilities"] == {
            "dense": True, "sparse": False, "rerank": False,
        }
        specs = client.get("/v1/models")
        assert specs.status_code == 200, specs.text
        assert specs.json()["dense"]["dimensions"] == 1024
        assert specs.json()["sparse"] is None
        response = client.post("/v1/embeddings", json={"input": ["北京是中国的首都", "Paris is the capital of France"]})
        assert response.status_code == 200, response.text
        vectors = [row["embedding"] for row in response.json()["data"]]
        assert len(vectors) == 2
        assert len(vectors[0]) == len(vectors[1]) == 1024
        assert vectors[0] != vectors[1]
        assert all(math.isfinite(value) for vector in vectors for value in vector)
        query = client.post("/v1/embeddings", json={"input": "中国首都"})
        assert query.status_code == 200, query.text
        assert len(query.json()["data"][0]["embedding"]) == len(vectors[0])
        disabled = client.post("/v1/sparse_embeddings", json={"input": "中国首都"})
        assert disabled.status_code == 404


def test_volcengine_sparse_through_inference_service(tmp_path):
    with cloud_inference_server(tmp_path, "volcengine", rerank=False) as address, httpx.Client(
        base_url=address, timeout=120, trust_env=False,
        headers={"Authorization": "Bearer inference-e2e-key"},
    ) as client:
        assert client.get("/ready").json()["capabilities"]["sparse"] is True
        for input_value, count in [(["北京是中国的首都", "Paris is the capital of France"], 2), ("中国首都", 1)]:
            response = client.post("/v1/sparse_embeddings", json={"input": input_value})
            assert response.status_code == 200, response.text
            rows = response.json()["data"]
            assert len(rows) == count
            for index, row in enumerate(rows):
                assert row["index"] == index
                assert len(row["indices"]) == len(row["values"]) > 0
                assert all(isinstance(value, int) and value >= 0 for value in row["indices"])
                assert all(math.isfinite(value) for value in row["values"])


def test_volcengine_rerank_through_inference_service(tmp_path):
    with cloud_inference_server(tmp_path, "volcengine") as address, httpx.Client(
        base_url=address, timeout=120, trust_env=False,
        headers={"Authorization": "Bearer inference-e2e-key"},
    ) as client:
        assert client.get("/ready").json()["capabilities"]["rerank"] is True
        response = client.post("/v1/rerank", json={
            "query": "中国的首都是哪里",
            "documents": ["Bread is baked in an oven.", "北京是中国的首都"],
            "top_k": 1,
        })
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["index"] == 1
