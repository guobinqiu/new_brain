import pytest


pytestmark = pytest.mark.e2e


def _index_ready_file(api_client, test_txt_path, monkeypatch, filename="test_ai.txt"):
    import main

    s3_url = f"s3://rag-dev/{filename}"
    monkeypatch.setattr(main, "_download_presigned_file", lambda presigned_url, suffix: test_txt_path)
    resp = api_client.post(
        "/api/index",
        json={
            "presigned_url": "https://example.com/presigned",
            "s3_url": s3_url,
            "filename": filename,
        },
    )
    assert resp.status_code == 200, resp.text
    file_id = resp.json()["file_id"]
    files = api_client.get("/api/files").json()["files"]
    assert any(item["id"] == file_id for item in files)
    return file_id


class TestSearchAPI:
    def test_search_sparse_api(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` with ``mode=sparse`` returns results with AGI content."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "agi", "mode": "sparse", "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "sparse"
        assert len(data["results"]) > 0
        combined = " ".join(r["content"] for r in data["results"])
        assert "AGI" in combined

    def test_search_dense_api(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` with ``mode=dense`` returns dense results."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "dense", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "dense"
        assert len(data["results"]) > 0
        for result in data["results"]:
            assert result["metadata"]["file_id"] == file_id

    def test_search_hybrid_api(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` with ``mode=hybrid`` returns hybrid results."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "hybrid"
        assert len(data["results"]) > 0
        for result in data["results"]:
            assert result["metadata"]["file_id"] == file_id

    def test_search_accepts_per_request_hybrid_weights(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` accepts hybrid weights without changing global config."""
        before = api_client.get("/api/config").json()
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post(
            "/api/search",
            json={
                "query": "人工智能",
                "mode": "hybrid",
                "top_k": 5,
                "dense_weight": 0.4,
                "sparse_weight": 0.6,
                "rrf_k": 30,
                "file_ids": [file_id],
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["dense_weight"] == 0.4
        assert data["sparse_weight"] == 0.6
        assert data["rrf_k"] == 30
        after = api_client.get("/api/config").json()
        assert after["dense_weight"] == before["dense_weight"]
        assert after["sparse_weight"] == before["sparse_weight"]
        assert after["rrf_k"] == before["rrf_k"]

    def test_search_rejects_unavailable_sparse_mode(self, api_client):
        """``sparse_mode=vector`` is rejected when current profile only exposes app sparse."""
        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "sparse", "sparse_mode": "vector"})

        assert resp.status_code == 400
        assert "sparse_mode=vector" in resp.text

    def test_search_rejects_empty_file_ids(self, api_client):
        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "dense", "file_ids": []})

        assert resp.status_code == 422

    def test_search_api_rerank_param(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` with ``rerank=true`` accepts and applies reranking."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "rerank": True, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["results"]) <= 5
        for result in data["results"]:
            for key in ("id", "content", "metadata"):
                assert key in result
            assert result["metadata"]["file_id"] == file_id

    def test_search_returns_elapsed_ms(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` response includes an ``elapsed_ms`` field."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "elapsed_ms" in data
        assert isinstance(data["elapsed_ms"], (int, float))
        assert data["elapsed_ms"] >= 0
        monitor = api_client.get("/api/monitor").json()
        assert data["elapsed_ms"] == monitor["search_traces"][0]["elapsed_ms"]

    def test_search_response_does_not_include_trace(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/search`` is a public API and does not expose diagnostics."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        assert "trace" not in resp.json()

    def test_search_elapsed_ms_reasonable(self, api_client, test_txt_path, monkeypatch):
        """``elapsed_ms`` reflects actual query execution time (0 < t < 60000)."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
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
        resp = api_client.post("/api/search", json={"query": "test", "mode": "invalid"})
        assert resp.status_code == 422

    def test_api_fetch_k_positive_ok(self, api_client):
        """``POST /api/search`` body 中 ``fetch_k=20`` 合法正整数,返回 200。"""
        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 20})
        assert resp.status_code == 200, resp.text

    def test_api_fetch_k_zero_rejected(self, api_client):
        """``POST /api/search`` body 中 ``fetch_k=0`` 被 ge=1 拒绝。"""
        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 0})
        assert resp.status_code == 422, f"fetch_k=0 应 422,got {resp.status_code}: {resp.text}"

    def test_api_fetch_k_negative_rejected(self, api_client):
        """``POST /api/search`` body 中 ``fetch_k=-5`` 被 ge=1 拒绝。"""
        resp = api_client.post("/api/search", json={"query": "人工智能", "mode": "dense", "fetch_k": -5})
        assert resp.status_code == 422, f"fetch_k=-5 应 422,got {resp.status_code}: {resp.text}"
