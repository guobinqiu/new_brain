import uuid

import pytest

from rag.api.runtime import runtime
from tests.e2e.helpers import index_uploaded_file


pytestmark = pytest.mark.e2e


def _index_ready_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt"):
    file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename=filename, content_type="text/plain")
    with runtime.application.store.app_context(app_api_client.app_id):
        documents = runtime.application.store.get_search_documents(runtime.application.store.build_file_filter([file_id]))
    assert documents
    return file_id


class TestSearchAPI:
    def test_search_sparse_api(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` with ``mode=sparse`` returns results with AGI content."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "agi", "mode": "sparse", "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "sparse"
        assert len(data["results"]) > 0
        combined = " ".join(r["content"] for r in data["results"])
        assert "AGI" in combined

    def test_search_dense_api(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` with ``mode=dense`` returns dense results."""
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "dense", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "dense"
        assert len(data["results"]) > 0
        assert any("人工智能" in result["content"] for result in data["results"])

    def test_search_hybrid_api(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` with ``mode=hybrid`` returns hybrid results."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "hybrid"
        assert len(data["results"]) > 0
        assert any("人工智能" in result["content"] for result in data["results"])

    def test_search_table_result_returns_table_content(self, app_api_client):
        _require_sparse()
        file_id = str(uuid.uuid4())
        chunks = [
            {
                "id": str(uuid.uuid4()),
                "content": "unique_table_marker revenue table first part",
                "metadata": {
                    "filename": "table.pdf",
                    "chunk_index": 0,
                    "s3_url": "s3://rag-test/table.pdf",
                },
            },
            {
                "id": str(uuid.uuid4()),
                "content": "unique_table_marker revenue table second part",
                "metadata": {
                    "filename": "table.pdf",
                    "chunk_index": 1,
                    "s3_url": "s3://rag-test/table.pdf",
                },
            },
        ]
        with runtime.application.store.app_context(app_api_client.app_id):
            runtime.application.store.add_file_chunks(chunks, file_id=file_id)
            _add_sparse_chunks_if_needed(chunks, file_id)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "unique_table_marker", "mode": "sparse", "top_k": 1, "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        result = resp.json()["results"][0]
        assert "unique_table_marker" in result["content"]

    def test_search_without_file_ids_searches_all_files(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` without file_ids searches the full index."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)
        chunks = [{"id": "550e8400-e29b-41d4-a716-446655440000", "content": "人工智能 other file", "metadata": {"filename": "other.txt", "chunk_index": 0}}]
        with runtime.application.store.app_context(app_api_client.app_id):
            runtime.application.store.add_file_chunks(chunks, file_id="other-file")
            _add_sparse_chunks_if_needed(chunks, "other-file")

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "sparse", "top_k": 10})

        assert resp.status_code == 200, resp.text
        combined = "\n".join(result["content"] for result in resp.json()["results"])
        assert "人工智能" in combined
        assert "other file" in combined

    def test_search_accepts_per_request_hybrid_weights(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` accepts hybrid weights without changing shared config."""
        _require_sparse()
        before = api_client.get("/api/open/rag/config").json()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post(
            "/api/open/rag/search",
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
        after = api_client.get("/api/open/rag/config").json()
        assert after["dense_weight"] == before["dense_weight"]
        assert after["sparse_weight"] == before["sparse_weight"]
        assert after["rrf_k"] == before["rrf_k"]

    def test_search_rejects_empty_file_ids(self, app_api_client):
        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "dense", "file_ids": []})

        assert resp.status_code == 422

    def test_search_api_rerank_param(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` with ``rerank=true`` accepts and applies reranking."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "rerank": True, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["results"]) <= 5
        for result in data["results"]:
            for key in ("id", "content", "score"):
                assert key in result

    def test_search_returns_elapsed_ms(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` response includes an ``elapsed_ms`` field."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "elapsed_ms" in data
        assert isinstance(data["elapsed_ms"], (int, float))
        assert data["elapsed_ms"] >= 0

    def test_search_response_does_not_include_trace(self, app_api_client, api_client, test_txt_path):
        """``POST /api/open/rag/search`` is a public API and does not expose diagnostics."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        assert "trace" not in resp.json()

    def test_search_elapsed_ms_reasonable(self, app_api_client, api_client, test_txt_path):
        """``elapsed_ms`` reflects actual query execution time (0 < t < 60000)."""
        _require_sparse()
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["elapsed_ms"] > 0
        assert data["elapsed_ms"] < 60000

    def test_search_empty_query_returns_error(self, app_api_client):
        """``POST /api/open/rag/search`` with an empty query returns 422."""
        resp = app_api_client.post("/api/open/rag/search", json={"query": "", "mode": "dense"})
        assert resp.status_code == 422

    def test_search_invalid_mode(self, app_api_client):
        """``POST /api/open/rag/search`` with an invalid mode returns 422."""
        resp = app_api_client.post("/api/open/rag/search", json={"query": "test", "mode": "invalid"})
        assert resp.status_code == 422

    def test_api_fetch_k_positive_ok(self, app_api_client):
        """``POST /api/open/rag/search`` body 中 ``fetch_k=20`` 合法正整数,返回 200。"""
        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 20})
        assert resp.status_code == 200, resp.text

    def test_api_fetch_k_zero_rejected(self, app_api_client):
        """``POST /api/open/rag/search`` body 中 ``fetch_k=0`` 被 ge=1 拒绝。"""
        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "dense", "fetch_k": 0})
        assert resp.status_code == 422, f"fetch_k=0 应 422,got {resp.status_code}: {resp.text}"

    def test_api_fetch_k_negative_rejected(self, app_api_client):
        """``POST /api/open/rag/search`` body 中 ``fetch_k=-5`` 被 ge=1 拒绝。"""
        resp = app_api_client.post("/api/open/rag/search", json={"query": "人工智能", "mode": "dense", "fetch_k": -5})
        assert resp.status_code == 422, f"fetch_k=-5 应 422,got {resp.status_code}: {resp.text}"


def _require_sparse():
    if runtime.application.sparse is None:
        pytest.skip("current config does not enable sparse search")


def _add_sparse_chunks_if_needed(chunks, file_id):
    sparse = runtime.application.sparse
    if sparse is None:
        return
    if runtime.application.store.sparse_uses_store(sparse):
        return
    add_file_chunks = getattr(sparse, "add_file_chunks", None)
    if callable(add_file_chunks):
        add_file_chunks(chunks, file_id=file_id)
