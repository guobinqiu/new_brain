import pytest
import httpx

from services.rag.tests.e2e.helpers import index_uploaded_file, indexed_file_record, presign_file


pytestmark = pytest.mark.e2e


class TestFilesAPI:
    def test_list_chunks_api_uses_cursor_pagination(self, app_api_client, api_client, tmp_path):
        """``POST /api/rag/chunks`` returns vector chunks plus cursor pagination."""
        document = tmp_path / "chunked.txt"
        content = "人工智能和向量检索第一段。" * 40 + "人工智能和向量检索第二段。" * 40
        document.write_text(content, encoding="utf-8")
        file_id = index_uploaded_file(app_api_client, api_client, document)
        assert indexed_file_record(app_api_client, file_id)["chunk_count"] > 1

        first_page = api_client.post("/api/rag/chunks", json={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200, first_page.text
        first_body = first_page.json()
        assert len(first_body["chunks"]) == 1
        chunk = first_body["chunks"][0]
        assert chunk["id"]
        assert chunk["file_id"] == file_id
        assert chunk["filename"] == "chunked.txt"
        assert isinstance(chunk["chunk_index"], int)
        assert chunk["s3_url"]
        assert chunk["content"]
        assert first_body["has_more"] is True
        assert first_body["next_cursor"]

        second_page = api_client.post("/api/rag/chunks", json={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200, second_page.text
        second_body = second_page.json()
        assert len(second_body["chunks"]) == 1
        assert second_body["chunks"][0]["id"] != chunk["id"]
        assert chunk["content"] in content
        assert second_body["chunks"][0]["content"] in content
        assert second_body["chunks"][0]["file_id"] == file_id

    def test_list_files_api_uses_cursor_pagination(self, app_api_client, api_client, test_txt_path):
        """``GET /api/rag/files`` returns indexed file pages via single-direction cursors."""
        file_ids = [
            index_uploaded_file(app_api_client, api_client, test_txt_path, filename=name)
            for name in ("first.txt", "second.txt")
        ]

        first_page = api_client.get("/api/rag/files", params={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True
        assert first_body["total"] == 2

        second_page = api_client.get("/api/rag/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == set(file_ids)
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None
        assert second_body["total"] == 2

    def test_list_files_api(self, app_api_client, api_client, test_txt_path):
        """``GET /api/rag/files`` lists indexed files from chunk metadata."""
        file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt")

        resp = api_client.get("/api/rag/files", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == file_id and item["filename"] == "test_ai.txt" and item["status"] == "success" for item in files)

    def test_admin_delete_file_api_removes_indexed_chunks_and_storage(self, app_api_client, api_client, test_txt_path):
        """``DELETE /api/rag/files/{file_id}`` removes indexed chunks and MinIO object."""
        file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt")
        record = indexed_file_record(app_api_client, file_id)
        assert record["chunk_count"] > 0
        object_url = presign_file(api_client, record["s3_url"])
        with httpx.Client(trust_env=False, timeout=30) as storage:
            assert storage.get(object_url).status_code == 200
        assert _file_chunks(api_client, app_api_client.app_id, file_id)

        del_resp = api_client.delete(f"/api/rag/files/{file_id}", params={"app_id": app_api_client.app_id})

        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["deleted_chunks"] > 0
        with httpx.Client(trust_env=False, timeout=30) as storage:
            assert storage.get(object_url).status_code == 404
        assert _file_chunks(api_client, app_api_client.app_id, file_id) == []
        files_resp = api_client.get("/api/rag/files", params={"app_id": app_api_client.app_id})
        assert files_resp.status_code == 200
        assert all(item["id"] != file_id for item in files_resp.json()["files"])

    def test_open_delete_file_api_removes_index_only(self, app_api_client, api_client, test_txt_path):
        """``DELETE /api/v1/rag/files/{file_id}`` removes indexed chunks and leaves caller storage untouched."""
        file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt")
        record = indexed_file_record(app_api_client, file_id)
        assert record["chunk_count"] > 0
        object_url = presign_file(api_client, record["s3_url"])
        with httpx.Client(trust_env=False, timeout=30) as storage:
            assert storage.get(object_url).status_code == 200
        assert _file_chunks(api_client, app_api_client.app_id, file_id)

        del_resp = app_api_client.delete(f"/api/v1/rag/files/{file_id}")

        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["deleted_chunks"] > 0
        with httpx.Client(trust_env=False, timeout=30) as storage:
            assert storage.get(object_url).status_code == 200
        assert _file_chunks(api_client, app_api_client.app_id, file_id) == []

    def test_delete_nonexistent(self, app_api_client, api_client):
        """Deleting a file with no chunks and no object returns zero counts."""
        resp = app_api_client.delete("/api/v1/rag/files/550e8400-e29b-41d4-a716-446655440099", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        assert resp.json() == {"deleted_chunks": 0}


def _file_chunks(api_client, app_id: str, file_id: str) -> list[dict]:
    response = api_client.post("/api/rag/chunks", json={"app_id": app_id, "file_ids": [file_id]})
    assert response.status_code == 200, response.text
    return response.json()["chunks"]
