import pytest

from tests.e2e.test_search_api import _index_ready_file


pytestmark = pytest.mark.e2e


class TestFilesAPI:
    def test_list_chunks_api_uses_cursor_pagination(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``POST /api/chunks`` returns vector chunks plus cursor pagination."""
        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        first_page = api_client.post("/api/chunks", json={"app_id": "imsdom", "limit": 1})

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

        second_page = api_client.post("/api/chunks", json={"app_id": "imsdom", "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200, second_page.text
        second_body = second_page.json()
        assert len(second_body["chunks"]) == 1

    def test_list_files_api_uses_cursor_pagination(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``GET /api/files`` returns MinIO-backed file pages."""
        import main

        pages = {
            None: {
                "files": [{"id": "file-a", "filename": "first.txt", "s3_url": "s3://rag-dev/uploads/imsdom/file-a/first.txt", "size": 1, "created_at": None}],
                "next_cursor": "cursor-a",
                "has_more": True,
            },
            "cursor-a": {
                "files": [{"id": "file-b", "filename": "second.txt", "s3_url": "s3://rag-dev/uploads/imsdom/file-b/second.txt", "size": 1, "created_at": None}],
                "next_cursor": None,
                "has_more": False,
            },
        }
        monkeypatch.setattr(main, "_list_storage_files", lambda app_id, limit=50, cursor=None: pages[cursor])

        first_page = api_client.get("/api/files", params={"app_id": "imsdom", "limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True

        second_page = api_client.get("/api/files", params={"app_id": "imsdom", "limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == {"file-a", "file-b"}
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None

    def test_list_files_api(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``GET /api/files`` lists uploaded MinIO files."""
        import main

        monkeypatch.setattr(main, "_list_storage_files", lambda app_id, limit=50, cursor=None: {
            "files": [{"id": "file-a", "filename": "test_ai.txt", "s3_url": "s3://rag-dev/uploads/imsdom/file-a/test_ai.txt", "size": 1, "created_at": None}],
            "next_cursor": None,
            "has_more": False,
        })

        resp = api_client.get("/api/files", params={"app_id": "imsdom"})

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == "file-a" and item["filename"] == "test_ai.txt" for item in files)

    def test_delete_file_api(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``DELETE /api/files/{file_id}`` removes indexed chunks and MinIO object."""
        import main

        calls = []
        monkeypatch.setattr(main, "_delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
        monkeypatch.setattr(main, "_delete_storage_file", lambda app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

        del_resp = api_client.delete("/api/files/file-a", params={"app_id": "imsdom"})
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json() == {"deleted_chunks": 2}
        assert calls == [("index", "file-a", "imsdom"), ("storage", "imsdom", "file-a")]

    def test_delete_nonexistent(self, app_api_client, api_client, monkeypatch):
        """Deleting a file with no chunks and no object returns zero counts."""
        import main

        monkeypatch.setattr(main, "_delete_index_file", lambda file_id, principal: {"deleted_chunks": 0})
        monkeypatch.setattr(main, "_delete_storage_file", lambda app_id, file_id: 0)

        resp = api_client.delete("/api/files/ghost", params={"app_id": "imsdom"})

        assert resp.status_code == 200
        assert resp.json() == {"deleted_chunks": 0}
