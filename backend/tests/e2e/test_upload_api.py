import pytest


pytestmark = pytest.mark.e2e


class TestUploadAPI:
    def test_upload_txt_stores_object(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/upload`` stores a .txt file in object storage and returns s3_url."""
        import main

        uploaded = []
        monkeypatch.setattr(main, "_upload_file_to_storage", lambda filename, content, content_type: uploaded.append((filename, content, content_type)) or "s3://rag-dev/uploads/test_ai.txt", raising=False)

        with open(test_txt_path, "rb") as f:
            resp = api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data == {"s3_url": "s3://rag-dev/uploads/test_ai.txt", "filename": "test_ai.txt"}
        assert uploaded
        assert uploaded[0][0] == "test_ai.txt"

    def test_upload_unsupported_type(self, api_client, tmp_path):
        """Uploading an unsupported file type returns 400."""
        bad = tmp_path / "data.xyz"
        bad.write_text("content")
        with open(bad, "rb") as f:
            resp = api_client.post(
                "/api/upload", files={"file": ("data.xyz", f, "application/octet-stream")}
            )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.text

    def test_upload_image_png_stores_object(self, api_client, test_img_path, monkeypatch):
        """``POST /api/upload`` stores a .png image file in object storage."""
        import main

        monkeypatch.setattr(main, "_upload_file_to_storage", lambda filename, content, content_type: "s3://rag-dev/uploads/test_ocr.png", raising=False)

        with open(test_img_path, "rb") as f:
            resp = api_client.post(
                "/api/upload", files={"file": ("test_ocr.png", f, "image/png")}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data == {"s3_url": "s3://rag-dev/uploads/test_ocr.png", "filename": "test_ocr.png"}

    def test_upload_no_filename(self, api_client, tmp_path):
        """Uploading a file with no filename returns a client error."""
        bad = tmp_path / "test.txt"
        bad.write_text("content")
        with open(bad, "rb") as f:
            resp = api_client.post(
                "/api/upload", files={"file": ("", f, "text/plain")}
            )
        assert resp.status_code in (400, 422), (
            f"Expected 400 or 422, got {resp.status_code}: {resp.text}"
        )

    def test_index_presigned_url_accepts_file_id(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/index`` uses caller-provided file_id when present."""
        import main

        monkeypatch.setattr(main, "_download_presigned_file", lambda presigned_url, suffix: test_txt_path)

        s3_url = "s3://rag-dev/test_ai.txt"
        resp = api_client.post(
            "/api/index",
            json={
                "file_id": "upstream-file-001",
                "presigned_url": "https://example.com/presigned",
                "s3_url": s3_url,
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        file_id = resp.json()["file_id"]
        assert file_id == "upstream-file-001"
        record = _uploaded_file(api_client, file_id)
        assert record["filename"] == "test_ai.txt"
        search = api_client.post("/api/search", json={"query": "人工智能", "mode": "dense", "file_ids": [file_id]})
        assert search.status_code == 200, search.text
        result = search.json()["results"][0]
        assert result["metadata"]["file_id"] == file_id
        assert result["metadata"]["s3_url"] == s3_url

    def test_index_presigned_url_generates_file_id_when_omitted(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/index`` generates a file_id when caller omits it."""
        import main

        monkeypatch.setattr(main, "_download_presigned_file", lambda presigned_url, suffix: test_txt_path)
        monkeypatch.setattr(main, "create_file_id", lambda: "generatedfile001")

        resp = api_client.post(
            "/api/index",
            json={
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag-dev/generated.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["file_id"] == "generatedfile001"

    def test_index_presigned_url_can_infer_filename_from_s3_url(self, api_client, test_txt_path, monkeypatch):
        """``POST /api/index`` uses the object name when filename is omitted."""
        import main

        monkeypatch.setattr(main, "_download_presigned_file", lambda presigned_url, suffix: test_txt_path)

        resp = api_client.post(
            "/api/index",
            json={
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag-dev/uploads/test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        record = _uploaded_file(api_client, resp.json()["file_id"])
        assert record["filename"] == "test_ai.txt"


def _uploaded_file(api_client, file_id: str) -> dict:
    files = api_client.get("/api/files").json()["files"]
    record = next((item for item in files if item["id"] == file_id), None)
    assert record is not None
    return record
