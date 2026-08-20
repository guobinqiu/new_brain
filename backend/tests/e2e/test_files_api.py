import pytest

from tests.e2e.test_search_api import _index_ready_file


pytestmark = pytest.mark.e2e


class TestFilesAPI:
    def test_list_chunks_api_uses_cursor_pagination(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``POST /api/chunks`` returns vector chunks plus cursor pagination."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        first_page = api_client.post("/api/chunks", json={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200, first_page.text
        first_body = first_page.json()
        assert len(first_body["chunks"]) == 1
        chunk = first_body["chunks"][0]
        assert chunk["id"]
        assert chunk["file_id"] == file_id
        assert chunk["filename"] == "test_ai.txt"
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
        """``GET /api/files`` returns PG-backed file pages via keyset cursors."""
        import main

        db = main.application.database
        for i, name in enumerate(["first.txt", "second.txt"]):
            db.upsert_file(app_api_client.app_id, f"file-{name}", name, f"s3://rag-dev/uploads/{app_api_client.app_id}/f/{name}", size=i + 1)

        first_page = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["prev_cursor"] is None
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True

        second_page = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": first_body["next_cursor"], "direction": "next"})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == {"file-first.txt", "file-second.txt"}
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None

        back = api_client.get("/api/files", params={"app_id": app_api_client.app_id, "limit": 1, "cursor": second_body["prev_cursor"], "direction": "prev"})

        assert back.status_code == 200
        assert back.json()["files"][0]["id"] == first_body["files"][0]["id"]
        assert back.json()["prev_cursor"] is None

    def test_list_files_api(self, app_api_client, api_client, monkeypatch):
        """``GET /api/files`` lists indexed files from PG."""
        import main

        main.application.database.upsert_file(app_api_client.app_id, "file-a", "test_ai.txt", f"s3://rag-dev/uploads/{app_api_client.app_id}/file-a/test_ai.txt", size=7)

        resp = api_client.get("/api/files", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == "file-a" and item["filename"] == "test_ai.txt" for item in files)

    def test_delete_file_api(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``DELETE /api/files/{file_id}`` removes indexed chunks and MinIO object."""
        import main

        calls = []
        monkeypatch.setattr(main, "_delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
        monkeypatch.setattr(main, "_delete_storage_file", lambda app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

        del_resp = api_client.delete("/api/files/file-a", params={"app_id": app_api_client.app_id})
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json() == {"deleted_chunks": 2}
        assert calls == [("index", "file-a", app_api_client.app_id), ("storage", app_api_client.app_id, "file-a")]

    def test_delete_nonexistent(self, app_api_client, api_client, monkeypatch):
        """Deleting a file with no chunks and no object returns zero counts."""
        import main

        monkeypatch.setattr(main, "_delete_index_file", lambda file_id, principal: {"deleted_chunks": 0})
        monkeypatch.setattr(main, "_delete_storage_file", lambda app_id, file_id: 0)

        resp = api_client.delete("/api/files/ghost", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        assert resp.json() == {"deleted_chunks": 0}
