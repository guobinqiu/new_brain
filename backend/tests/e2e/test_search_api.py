import pytest


pytestmark = pytest.mark.e2e


class TestSearchAPI:
    def test_search_sparse_api(self, api_client, test_txt_path):
        """``POST /api/search`` with ``mode=sparse`` returns results with AGI content."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        resp = api_client.post("/api/search", json={"query": "agi", "mode": "sparse"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "sparse"
        assert len(data["results"]) > 0
        combined = " ".join(r["content"] for r in data["results"])
        assert "AGI" in combined, (
            "API sparse search for 'agi' should return content containing 'AGI' "
            "(case-insensitive BM25 regression test)"
        )

    def test_search_dense_api(self, api_client, test_txt_path):
        """``POST /api/search`` with ``mode=dense`` returns dense results."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        resp = api_client.post(
            "/api/search",
            json={"query": "人工智能", "mode": "dense", "top_k": 5},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "dense"
        assert len(data["results"]) > 0
        for r in data["results"]:
            assert r["collection_type"] in ("common", "scoped")
            assert "method" not in r

    def test_search_hybrid_api(self, api_client, test_txt_path):
        """``POST /api/search`` with ``mode=hybrid`` returns hybrid results."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        resp = api_client.post(
            "/api/search",
            json={"query": "人工智能", "mode": "hybrid", "top_k": 5},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "hybrid"
        assert len(data["results"]) > 0
        for r in data["results"]:
            assert r["collection_type"] in ("common", "scoped")
            assert "method" not in r

    def test_search_api_rerank_param(self, api_client, test_txt_path):
        """``POST /api/search`` with ``rerank=true`` accepts and applies reranking."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        resp = api_client.post(
            "/api/search",
            json={
                "query": "人工智能",
                "mode": "hybrid",
                "top_k": 5,
                "rerank": True,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["results"]) <= 5
        for r in data["results"]:
            assert r["collection_type"] in ("common", "scoped")
            for key in ("id", "content", "metadata", "collection_type"):
                assert key in r

    def test_search_returns_elapsed_ms(self, api_client, test_txt_path):
        """``POST /api/search`` response includes an ``elapsed_ms`` field."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        resp = api_client.post(
            "/api/search",
            json={"query": "人工智能", "mode": "hybrid", "top_k": 5},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "elapsed_ms" in data
        assert isinstance(data["elapsed_ms"], (int, float))
        assert data["elapsed_ms"] >= 0

    def test_search_elapsed_ms_reasonable(self, api_client, test_txt_path):
        """``elapsed_ms`` reflects actual query execution time (0 < t < 60000)."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        resp = api_client.post(
            "/api/search",
            json={"query": "人工智能", "mode": "hybrid", "top_k": 5},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["elapsed_ms"] > 0
        assert data["elapsed_ms"] < 60000

    def test_search_empty_query_returns_error(self, api_client):
        """``POST /api/search`` with an empty query returns 422."""
        resp = api_client.post("/api/search", json={"query": "", "mode": "hybrid"})
        assert resp.status_code == 422

    def test_search_invalid_mode(self, api_client):
        """``POST /api/search`` with an invalid mode returns 422."""
        resp = api_client.post(
            "/api/search", json={"query": "test", "mode": "invalid"}
        )
        assert resp.status_code == 422

    def test_api_fetch_k_positive_ok(self, api_client):
        """``POST /api/search`` body 中 ``fetch_k=20`` 合法正整数,返回 200。"""
        resp = api_client.post(
            "/api/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 20}
        )
        assert resp.status_code == 200, resp.text

    def test_api_fetch_k_zero_rejected(self, api_client):
        """``POST /api/search`` body 中 ``fetch_k=0`` 被 ge=1 拒绝(422)。

        旧 main.py 未声明 fetch_k,FastAPI 忽略未知参数 → 200;新实现 Field(ge=1)
        拒绝 0 → 422。故当前返回 200,断言 422 → RED。
        """
        resp = api_client.post(
            "/api/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 0}
        )
        assert resp.status_code == 422, f"fetch_k=0 应 422,got {resp.status_code}: {resp.text}"

    def test_api_fetch_k_negative_rejected(self, api_client):
        """``POST /api/search`` body 中 ``fetch_k=-5`` 被 ge=1 拒绝 → 422。"""
        resp = api_client.post(
            "/api/search", json={"query": "人工智能", "mode": "dense", "fetch_k": -5}
        )
        assert resp.status_code == 422, f"fetch_k=-5 应 422,got {resp.status_code}: {resp.text}"
