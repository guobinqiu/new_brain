import pytest
import uuid

from rag.api.runtime import runtime
from rag.api.services.files import minio_client, parse_storage_url, storage_file_prefix
from tests.e2e.helpers import index_uploaded_file


pytestmark = pytest.mark.e2e


class TestFilesAPI:
    def test_list_chunks_api_uses_cursor_pagination(self, app_api_client, api_client):
        """``POST /api/open/rag/chunks`` returns vector chunks plus cursor pagination."""
        file_id = str(uuid.uuid4())
        with runtime.application.store.app_context(app_api_client.app_id):
            runtime.application.store.add_file_chunks(
                [
                    {"id": str(uuid.uuid4()), "content": "人工智能和向量检索第一段", "metadata": {"filename": "chunked.txt", "chunk_index": 0, "s3_url": "s3://rag-test/chunked.txt"}},
                    {
                        "id": str(uuid.uuid4()),
                        "content": "人工智能和向量检索第二段",
                        "metadata": {
                            "filename": "chunked.txt",
                            "chunk_index": 1,
                            "s3_url": "s3://rag-test/chunked.txt",
                        },
                    },
                ],
                file_id=file_id,
            )

        first_page = api_client.post("/api/open/rag/chunks", json={"app_id": app_api_client.app_id, "limit": 1})

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

        second_page = api_client.post("/api/open/rag/chunks", json={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200, second_page.text
        second_body = second_page.json()
        assert len(second_body["chunks"]) == 1
        assert second_body["chunks"][0]["content"] == "人工智能和向量检索第二段"

    def test_list_files_api_uses_cursor_pagination(self, app_api_client, api_client):
        """``GET /api/open/rag/files`` returns PG-backed file pages via single-direction cursors."""
        file_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        db = runtime.application.database
        for i, name in enumerate(["first.txt", "second.txt"]):
            db.upsert_file(app_api_client.app_id, file_ids[i], name, f"s3://rag-test/uploads/{app_api_client.app_id}/{file_ids[i]}/{name}", size=i + 1)

        first_page = api_client.get("/api/open/rag/files", params={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True
        assert first_body["total"] == 2

        second_page = api_client.get("/api/open/rag/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == set(file_ids)
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None
        assert second_body["total"] == 2

    def test_list_files_api(self, app_api_client, api_client):
        """``GET /api/open/rag/files`` lists indexed files from PG."""
        file_id = str(uuid.uuid4())
        runtime.application.database.upsert_file(app_api_client.app_id, file_id, "test_ai.txt", f"s3://rag-test/uploads/{app_api_client.app_id}/{file_id}/test_ai.txt", size=7)

        resp = api_client.get("/api/open/rag/files", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == file_id and item["filename"] == "test_ai.txt" and item["status"] == "success" for item in files)

    def test_delete_file_api_removes_indexed_chunks_storage_and_file_record(self, app_api_client, api_client, test_txt_path):
        """``DELETE /api/open/rag/files/{file_id}`` removes indexed chunks, DB record, and MinIO object."""
        file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt")
        assert _storage_object_count(app_api_client.app_id, file_id) > 0
        with runtime.application.store.app_context(app_api_client.app_id):
            assert runtime.application.store.get_total_chunks([file_id]) > 0

        del_resp = api_client.delete(f"/api/open/rag/files/{file_id}", params={"app_id": app_api_client.app_id})

        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["deleted_chunks"] > 0
        assert _storage_object_count(app_api_client.app_id, file_id) == 0
        with runtime.application.store.app_context(app_api_client.app_id):
            assert runtime.application.store.get_total_chunks([file_id]) == 0
        files_resp = api_client.get("/api/open/rag/files", params={"app_id": app_api_client.app_id})
        assert files_resp.status_code == 200
        assert all(item["id"] != file_id for item in files_resp.json()["files"])

    def test_delete_nonexistent(self, app_api_client, api_client):
        """Deleting a file with no chunks and no object returns zero counts."""
        resp = api_client.delete("/api/open/rag/files/550e8400-e29b-41d4-a716-446655440099", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        assert resp.json() == {"deleted_chunks": 0}


def _storage_object_count(app_id: str, file_id: str) -> int:
    bucket, _ = parse_storage_url(f"s3://rag-test/{storage_file_prefix(app_id, file_id)}placeholder")
    client = minio_client()
    return sum(1 for _ in client.list_objects(bucket, prefix=storage_file_prefix(app_id, file_id), recursive=True))
