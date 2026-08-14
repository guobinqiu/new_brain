import pytest

from tests.e2e.test_search_api import _index_ready_file


pytestmark = pytest.mark.e2e


class TestFilesAPI:
    def test_list_chunks_api_uses_cursor_pagination(self, api_client, test_txt_path, monkeypatch):
        """``GET /api/chunks`` returns vector chunks plus cursor pagination."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        first_page = api_client.get("/api/chunks", params={"limit": 1})

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

        second_page = api_client.get("/api/chunks", params={"limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200, second_page.text
        second_body = second_page.json()
        assert len(second_body["chunks"]) == 1

    def test_list_files_api_uses_cursor_pagination(self, api_client, test_txt_path, monkeypatch):
        """``GET /api/files`` returns one page plus an opaque cursor."""
        first_id = _index_ready_file(api_client, test_txt_path, monkeypatch, filename="first.txt")
        second_id = _index_ready_file(api_client, test_txt_path, monkeypatch, filename="second.txt")

        first_page = api_client.get("/api/files", params={"limit": 1})

        assert first_page.status_code == 200
        first_body = first_page.json()
        assert len(first_body["files"]) == 1
        assert first_body["next_cursor"]
        assert first_body["has_more"] is True

        second_page = api_client.get("/api/files", params={"limit": 1, "cursor": first_body["next_cursor"]})

        assert second_page.status_code == 200
        second_body = second_page.json()
        assert len(second_body["files"]) == 1
        assert {first_body["files"][0]["id"], second_body["files"][0]["id"]} == {first_id, second_id}
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None

    def test_list_files_api(self, api_client, test_txt_path, monkeypatch):
        """``GET /api/files`` lists previously uploaded files."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        resp = api_client.get("/api/files")

        assert resp.status_code == 200
        files = resp.json()["files"]
        assert any(item["id"] == file_id and item["filename"] == "test_ai.txt" for item in files)

    def test_delete_file_api(self, api_client, test_txt_path, monkeypatch):
        """``DELETE /api/files/{file_id}`` removes the file from search."""
        file_id = _index_ready_file(api_client, test_txt_path, monkeypatch)

        del_resp = api_client.delete(f"/api/files/{file_id}")
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["deleted_chunks"] > 0

        files = api_client.get("/api/files").json()["files"]
        assert not any(item["id"] == file_id for item in files)

    def test_delete_nonexistent(self, api_client):
        """Deleting a file that does not exist returns 0 chunks."""
        resp = api_client.delete("/api/files/ghost")

        assert resp.status_code == 200
        assert resp.json()["deleted_chunks"] == 0
