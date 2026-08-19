import pytest
from pathlib import Path


pytestmark = pytest.mark.e2e


def _index_ready_file(api_client, test_txt_path, monkeypatch, filename="test_ai.txt"):
    import main

    s3_url = f"s3://rag-dev/{filename}"

    def index_object(application, file_id, presigned_url, s3_url, filename):
        main.index_file(main.application, file_id, Path(test_txt_path), filename, extra_metadata={"s3_url": s3_url})
        return 1

    monkeypatch.setattr(main, "index_presigned_object", index_object)
    resp = api_client.post(
        "/api/open/index",
        json={
            "presigned_url": "https://example.com/presigned",
            "s3_url": s3_url,
            "filename": filename,
        },
    )
    assert resp.status_code == 200, resp.text
    file_id = resp.json()["file_id"]
    assert resp.json() == {"file_id": file_id}
    with main.application.store.app_context(api_client.app_id):
        documents = main.application.store.get_search_documents(main.application.store.build_file_filter([file_id]))
    assert documents
    return file_id


class TestSearchAPI:
    def test_search_sparse_api(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` with ``mode=sparse`` returns results with AGI content."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "agi", "mode": "sparse", "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "sparse"
        assert len(data["results"]) > 0
        combined = " ".join(r["content"] for r in data["results"])
        assert "AGI" in combined

    def test_search_dense_api(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` with ``mode=dense`` returns dense results."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "dense", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "dense"
        assert len(data["results"]) > 0
        for result in data["results"]:
            assert result["metadata"]["file_id"] == file_id

    def test_search_hybrid_api(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` with ``mode=hybrid`` returns hybrid results."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "hybrid"
        assert len(data["results"]) > 0
        for result in data["results"]:
            assert result["metadata"]["file_id"] == file_id

    def test_search_without_file_ids_searches_all_files(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` without file_ids searches the full index."""
        import main

        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)
        with main.application.store.app_context(app_api_client.app_id):
            main.application.store.add_file_chunks(
                [{"id": "other-file-chunk", "content": "人工智能 other file", "metadata": {"filename": "other.txt", "chunk_index": 0}}],
                file_id="other-file",
            )

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "sparse", "top_k": 10})

        assert resp.status_code == 200, resp.text
        assert {result["metadata"]["file_id"] for result in resp.json()["results"]} == {file_id, "other-file"}

    def test_search_accepts_per_request_hybrid_weights(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` accepts hybrid weights without changing global config."""
        before = api_client.get("/api/config").json()
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post(
            "/api/open/search",
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

    def test_search_rejects_empty_file_ids(self, app_api_client):
        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "dense", "file_ids": []})

        assert resp.status_code == 422

    def test_search_api_rerank_param(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` with ``rerank=true`` accepts and applies reranking."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "rerank": True, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["results"]) <= 5
        for result in data["results"]:
            for key in ("id", "content", "metadata"):
                assert key in result
            assert result["metadata"]["file_id"] == file_id

    def test_search_returns_elapsed_ms(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` response includes an ``elapsed_ms`` field."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "elapsed_ms" in data
        assert isinstance(data["elapsed_ms"], (int, float))
        assert data["elapsed_ms"] >= 0
        traces = api_client.get("/api/traces", params={"app_id": app_api_client.app_id}).json()
        assert data["elapsed_ms"] == traces["traces"][0]["elapsed_ms"]

    def test_search_response_does_not_include_trace(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/search`` is a public API and does not expose diagnostics."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        assert "trace" not in resp.json()

    def test_search_elapsed_ms_reasonable(self, app_api_client, test_txt_path, monkeypatch):
        """``elapsed_ms`` reflects actual query execution time (0 < t < 60000)."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["elapsed_ms"] > 0
        assert data["elapsed_ms"] < 60000

    def test_search_empty_query_returns_error(self, app_api_client):
        """``POST /api/open/search`` with an empty query returns 422."""
        resp = app_api_client.post("/api/open/search", json={"query": "", "mode": "hybrid"})
        assert resp.status_code == 422

    def test_search_invalid_mode(self, app_api_client):
        """``POST /api/open/search`` with an invalid mode returns 422."""
        resp = app_api_client.post("/api/open/search", json={"query": "test", "mode": "invalid"})
        assert resp.status_code == 422

    def test_api_fetch_k_positive_ok(self, app_api_client):
        """``POST /api/open/search`` body 中 ``fetch_k=20`` 合法正整数,返回 200。"""
        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 20})
        assert resp.status_code == 200, resp.text

    def test_api_fetch_k_zero_rejected(self, app_api_client):
        """``POST /api/open/search`` body 中 ``fetch_k=0`` 被 ge=1 拒绝。"""
        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 0})
        assert resp.status_code == 422, f"fetch_k=0 应 422,got {resp.status_code}: {resp.text}"

    def test_api_fetch_k_negative_rejected(self, app_api_client):
        """``POST /api/open/search`` body 中 ``fetch_k=-5`` 被 ge=1 拒绝。"""
        resp = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "dense", "fetch_k": -5})
        assert resp.status_code == 422, f"fetch_k=-5 应 422,got {resp.status_code}: {resp.text}"
