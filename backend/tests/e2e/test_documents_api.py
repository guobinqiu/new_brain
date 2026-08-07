import pytest


pytestmark = pytest.mark.e2e


class TestDocumentsAPI:
    def test_list_documents_api(self, api_client, test_txt_path):
        """``GET /api/documents`` lists previously uploaded files."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )
        resp = api_client.get("/api/documents")
        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert any(d["filename"] == "test_ai.txt" for d in docs)

    def test_delete_document_api(self, api_client, test_txt_path):
        """``DELETE /api/documents/{filename}`` removes the file from search."""
        with open(test_txt_path, "rb") as f:
            api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )

        docs_resp = api_client.get("/api/documents")
        assert any(d["filename"] == "test_ai.txt" for d in docs_resp.json()["documents"])

        del_resp = api_client.delete("/api/documents/test_ai.txt?collection_type=common")
        assert del_resp.status_code == 200, del_resp.text
        assert del_resp.json()["deleted_chunks"] > 0

        docs_resp2 = api_client.get("/api/documents")
        assert not any(
            d["filename"] == "test_ai.txt" for d in docs_resp2.json()["documents"]
        )

    def test_delete_nonexistent(self, api_client):
        """Deleting a document that does not exist returns 0 chunks."""
        resp = api_client.delete("/api/documents/ghost.txt?collection_type=common")
        assert resp.status_code == 200
        assert resp.json()["deleted_chunks"] == 0
