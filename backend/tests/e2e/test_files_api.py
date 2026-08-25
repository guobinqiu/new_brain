import pytest
import uuid

from api.runtime import runtime
from api.services import files as service


pytestmark = pytest.mark.e2e


class TestFilesAPI:
    def test_list_chunks_api_uses_cursor_pagination(self, app_api_client, api_client, tmp_path, monkeypatch):
        """``POST /api/chunks`` returns vector chunks plus cursor pagination."""
        file_id = str(uuid.uuid4())
        with runtime.application.store.app_context(app_api_client.app_id):
            runtime.application.store.add_file_chunks(
                [
                    {"id": str(uuid.uuid4()), "content": "人工智能和向量检索第一段", "metadata": {"filename": "chunked.txt", "chunk_index": 0, "s3_url": "s3://rag/chunked.txt"}},
                    {"id": str(uuid.uuid4()), "content": "人工智能和向量检索第二段", "metadata": {"filename": "chunked.txt", "chunk_index": 1, "s3_url": "s3://rag/chunked.txt"}},
                ],
                file_id=file_id,
            )

        first_page = api_client.post("/api/chunks", json={"app_id": app_api_client.app_id, "limit": 1})

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

        second_page = api_client.post("/api/chunks", json={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200, second_page.text
        second_body = second_page.json()
        assert len(second_body["chunks"]) == 1

    def test_list_files_api_uses_cursor_pagination(self, app_api_client, api_client, monkeypatch):
        """``GET /api/files`` returns PG-backed file pages via single-direction cursors."""
        db = runtime.application.database
        for i, name in enumerate(["first.txt", "second.txt"]):
            db.upsert_file(app_api_client.app_id, f"file-{name}", name, f"s3://rag/uploads/{app_api_client.app_id}/f/{name}", size=i + 1)

        first_page = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True
        assert first_body["total"] == 2

        second_page = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == {"file-first.txt", "file-second.txt"}
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None
        assert second_body["total"] == 2

    def test_list_files_api(self, app_api_client, api_client, monkeypatch):
        """``GET /api/files`` lists indexed files from PG."""
        runtime.application.database.upsert_file(app_api_client.app_id, "file-a", "test_ai.txt", f"s3://rag/uploads/{app_api_client.app_id}/file-a/test_ai.txt", size=7)

        resp = api_client.get("/api/files", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == "file-a" and item["filename"] == "test_ai.txt" and item["status"] == "success" for item in files)

    def test_delete_file_api(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``DELETE /api/files/{file_id}`` removes indexed chunks and MinIO object."""
        calls = []
        monkeypatch.setattr(service, "delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
        monkeypatch.setattr(service, "delete_storage_file", lambda app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

        del_resp = api_client.delete("/api/files/file-a", params={"app_id": app_api_client.app_id})
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json() == {"deleted_chunks": 2}
        assert calls == [("index", "file-a", app_api_client.app_id), ("storage", app_api_client.app_id, "file-a")]

    def test_delete_file_api_uses_provided_file_id(self, app_api_client, api_client, monkeypatch):
        """``DELETE /api/files/{file_id}`` uses the provided file_id unchanged."""
        calls = []
        monkeypatch.setattr(service, "delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
        monkeypatch.setattr(service, "delete_storage_file", lambda app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

        del_resp = api_client.delete("/api/files/550e8400-e29b-41d4-a716-446655440000", params={"app_id": app_api_client.app_id})

        assert del_resp.status_code == 200, del_resp.text
        assert calls == [
            ("index", "550e8400-e29b-41d4-a716-446655440000", app_api_client.app_id),
            ("storage", app_api_client.app_id, "550e8400-e29b-41d4-a716-446655440000"),
        ]

    def test_delete_file_api_keeps_index_delete_when_storage_delete_fails(self, app_api_client, api_client, monkeypatch):
        """Object storage delete failure does not fail index deletion."""
        calls = []
        monkeypatch.setattr(service, "delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
        monkeypatch.setattr(service, "delete_storage_file", lambda app_id, file_id: (_ for _ in ()).throw(RuntimeError("minio down")))

        del_resp = api_client.delete("/api/files/file-a", params={"app_id": app_api_client.app_id})

        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json() == {"deleted_chunks": 2}
        assert calls == [("index", "file-a", app_api_client.app_id)]

    def test_delete_file_api_removes_indexed_chunks_and_file_record(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``DELETE /api/files/{file_id}`` removes vector chunks and hides the file record."""
        monkeypatch.setattr(service, "delete_storage_file", lambda app_id, file_id: 0)
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)
        with runtime.application.store.app_context(app_api_client.app_id):
            assert runtime.application.store.get_total_chunks([file_id]) > 0

        del_resp = api_client.delete(f"/api/files/{file_id}", params={"app_id": app_api_client.app_id})

        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["deleted_chunks"] > 0
        with runtime.application.store.app_context(app_api_client.app_id):
            assert runtime.application.store.get_total_chunks([file_id]) == 0
        files_resp = api_client.get("/api/files", params={"app_id": app_api_client.app_id})
        assert files_resp.status_code == 200
        assert all(item["id"] != file_id for item in files_resp.json()["files"])

    def test_delete_nonexistent(self, app_api_client, api_client, monkeypatch):
        """Deleting a file with no chunks and no object returns zero counts."""
        monkeypatch.setattr(service, "delete_index_file", lambda file_id, principal: {"deleted_chunks": 0})
        monkeypatch.setattr(service, "delete_storage_file", lambda app_id, file_id: 0)

        resp = api_client.delete("/api/files/ghost", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        assert resp.json() == {"deleted_chunks": 0}
