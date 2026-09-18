import pytest

from services.rag.tests.e2e.helpers import index_uploaded_file, indexed_file_record


pytestmark = pytest.mark.e2e


def _index_ready_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt"):
    file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename=filename, content_type="text/plain")
    record = indexed_file_record(app_api_client, file_id)
    assert record["status"] == "success"
    assert record["chunk_count"] > 0
    return file_id


class TestSearchAPI:
    def test_search_dense_api(self, app_api_client, api_client, test_txt_path):
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "top_k": 5, "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mode"] == "dense"
        assert len(data["results"]) > 0
        assert any("人工智能" in result["content"] for result in data["results"])

    def test_search_table_result_returns_table_content(self, app_api_client, api_client, tmp_path):
        document = tmp_path / "table.md"
        document.write_text(
            "| Product | Revenue |\n| --- | --- |\n"
            "| unique_table_marker | 12345 |\n",
            encoding="utf-8",
        )
        file_id = index_uploaded_file(app_api_client, api_client, document, content_type="text/markdown")

        resp = app_api_client.post("/api/v1/rag/search", json={"query": "unique_table_marker", "top_k": 1, "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        result = resp.json()["results"][0]
        assert "unique_table_marker" in result["content"]
        assert "12345" in result["content"]
        assert "Revenue" in result["content"]

    def test_search_without_file_ids_searches_all_files(self, app_api_client, api_client, test_txt_path, tmp_path):
        _index_ready_file(app_api_client, api_client, test_txt_path)
        other_file = tmp_path / "other.txt"
        other_file.write_text("人工智能 other file", encoding="utf-8")
        _index_ready_file(app_api_client, api_client, other_file, filename="other.txt")

        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "top_k": 10})

        assert resp.status_code == 200, resp.text
        combined = "\n".join(result["content"] for result in resp.json()["results"])
        assert "人工智能" in combined
        assert "other file" in combined

    def test_search_rejects_empty_file_ids(self, app_api_client):
        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "file_ids": []})

        assert resp.status_code == 422

    def test_search_returns_elapsed_ms(self, app_api_client, api_client, test_txt_path):
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "top_k": 5, "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "elapsed_ms" in data
        assert isinstance(data["elapsed_ms"], (int, float))
        assert data["elapsed_ms"] >= 0

    def test_search_response_does_not_include_trace(self, app_api_client, api_client, test_txt_path):
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "top_k": 5, "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        assert "trace" not in resp.json()

    def test_search_elapsed_ms_reasonable(self, app_api_client, api_client, test_txt_path):
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)

        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "top_k": 5, "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["elapsed_ms"] > 0
        assert data["elapsed_ms"] < 60000

    def test_search_empty_query_returns_error(self, app_api_client):
        resp = app_api_client.post("/api/v1/rag/search", json={"query": ""})

        assert resp.status_code == 422

    def test_search_accepts_dense_mode_param(self, app_api_client, api_client, test_txt_path):
        file_id = _index_ready_file(app_api_client, api_client, test_txt_path)
        resp = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "mode": "dense", "file_ids": [file_id]})

        assert resp.status_code == 200, resp.text
        assert resp.json()["mode"] == "dense"

    def test_search_rejects_invalid_mode_param(self, app_api_client):
        resp = app_api_client.post("/api/v1/rag/search", json={"query": "test", "mode": "legacy"})

        assert resp.status_code == 422
