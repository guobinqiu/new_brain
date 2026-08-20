import pytest
from pathlib import Path


pytestmark = pytest.mark.e2e


class TestUploadAPI:
    def test_upload_txt_stores_object(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``POST /api/upload`` stores a .txt file in object storage and returns s3_url."""
        import main

        uploaded = []
        monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
        monkeypatch.setattr(main, "_upload_file_to_storage", lambda app_id, file_id, filename, content, content_type: uploaded.append((app_id, file_id, filename, content, content_type)) or f"s3://rag/uploads/{app_api_client.app_id}/abc123/test_ai.txt", raising=False)

        with open(test_txt_path, "rb") as f:
            resp = api_client.post(
                "/api/upload", data={"app_id": app_api_client.app_id}, files={"file": ("test_ai.txt", f, "text/plain")}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data == {"file_id": "abc123", "s3_url": f"s3://rag/uploads/{app_api_client.app_id}/abc123/test_ai.txt", "filename": "test_ai.txt"}
        assert uploaded
        assert uploaded[0][0] == app_api_client.app_id
        assert uploaded[0][1] == "abc123"
        assert uploaded[0][2] == "test_ai.txt"

    def test_upload_unsupported_type(self, app_api_client, api_client, tmp_path):
        """Uploading an unsupported file type returns 400."""
        bad = tmp_path / "data.xyz"
        bad.write_text("content")
        with open(bad, "rb") as f:
            resp = api_client.post(
                "/api/upload", data={"app_id": app_api_client.app_id}, files={"file": ("data.xyz", f, "application/octet-stream")}
            )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.text

    def test_upload_image_png_stores_object(self, app_api_client, api_client, test_img_path, monkeypatch):
        """``POST /api/upload`` stores a .png image file in object storage."""
        import main

        monkeypatch.setattr(main, "create_file_id", lambda: "img123")
        monkeypatch.setattr(main, "_upload_file_to_storage", lambda app_id, file_id, filename, content, content_type: f"s3://rag/uploads/{app_api_client.app_id}/img123/test_ocr.png", raising=False)

        with open(test_img_path, "rb") as f:
            resp = api_client.post(
                "/api/upload", data={"app_id": app_api_client.app_id}, files={"file": ("test_ocr.png", f, "image/png")}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data == {"file_id": "img123", "s3_url": f"s3://rag/uploads/{app_api_client.app_id}/img123/test_ocr.png", "filename": "test_ocr.png"}

    def test_upload_no_filename(self, app_api_client, api_client, tmp_path):
        """Uploading a file with no filename returns a client error."""
        bad = tmp_path / "test.txt"
        bad.write_text("content")
        with open(bad, "rb") as f:
            resp = api_client.post(
                "/api/upload", data={"app_id": app_api_client.app_id}, files={"file": ("", f, "text/plain")}
            )
        assert resp.status_code in (400, 422), (
            f"Expected 400 or 422, got {resp.status_code}: {resp.text}"
        )

    def test_index_presigned_url_generates_file_id_for_app(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/index`` generates the indexed file_id."""
        import main

        def index_object(application, file_id, presigned_url, s3_url, filename):
            main.index_file(main.application, file_id, Path(test_txt_path), filename, extra_metadata={"s3_url": s3_url})
            return 1, Path(test_txt_path).stat().st_size

        monkeypatch.setattr(main, "create_file_id", lambda: "generatedfile001")
        monkeypatch.setattr(main, "index_presigned_object", index_object)

        s3_url = "s3://rag/test_ai.txt"
        resp = app_api_client.post(
            "/api/open/index",
            json={
                "presigned_url": "https://example.com/presigned",
                "s3_url": s3_url,
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        file_id = resp.json()["file_id"]
        assert file_id == "generatedfile001"
        assert resp.json() == {"file_id": "generatedfile001"}
        record = _uploaded_file(app_api_client, file_id)
        assert record["filename"] == "test_ai.txt"
        search = app_api_client.post("/api/open/search", json={"query": "人工智能", "mode": "dense", "file_ids": [file_id]})
        assert search.status_code == 200, search.text
        result = search.json()["results"][0]
        assert result["metadata"]["file_id"] == file_id
        assert result["metadata"]["s3_url"] == s3_url

    def test_index_presigned_url_generates_file_id_when_omitted(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/index`` generates a file_id when caller omits it."""
        import main

        monkeypatch.setattr(main, "create_file_id", lambda: "generatedfile001")
        monkeypatch.setattr(main, "index_presigned_object", lambda application, file_id, presigned_url, s3_url, filename: (1, 1))

        resp = app_api_client.post(
            "/api/open/index",
            json={
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/generated.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"file_id": "generatedfile001"}

    def test_async_index_job_returns_file_id(self, app_api_client, monkeypatch):
        """``POST /api/open/index/jobs`` enqueues an async index job and returns file_id."""
        import main

        monkeypatch.setattr(main, "create_file_id", lambda: "550e8400-e29b-41d4-a716-446655440000")
        monkeypatch.setattr(main, "enqueue_index_job", lambda **kwargs: {"file_id": kwargs["file_id"]})

        resp = app_api_client.post(
            "/api/open/index/jobs",
            json={
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/generated.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 202, resp.text
        assert resp.json() == {"file_id": "550e8400-e29b-41d4-a716-446655440000"}

    def test_async_index_job_accepts_caller_uuid_file_id(self, app_api_client, monkeypatch):
        import main

        enqueued = []

        monkeypatch.setattr(main, "enqueue_index_job", lambda **kwargs: enqueued.append(kwargs) or {"file_id": kwargs["file_id"]})

        resp = app_api_client.post(
            "/api/open/index/jobs",
            json={
                "file_id": "550e8400-e29b-41d4-a716-446655440000",
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/generated.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 202, resp.text
        assert resp.json() == {"file_id": "550e8400-e29b-41d4-a716-446655440000"}
        assert enqueued[0]["file_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert "job_id" not in enqueued[0]

    def test_index_presigned_url_accepts_caller_uuid_file_id(self, app_api_client, monkeypatch):
        """``POST /api/open/index`` accepts caller-provided UUID file_id."""
        import main

        monkeypatch.setattr(main, "index_presigned_object", lambda application, file_id, presigned_url, s3_url, filename: (1, 1))

        resp = app_api_client.post(
            "/api/open/index",
            json={
                "file_id": "550e8400-e29b-41d4-a716-446655440000",
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/business.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"file_id": "550e8400-e29b-41d4-a716-446655440000"}

    def test_index_presigned_url_accepts_custom_file_id(self, app_api_client, monkeypatch):
        import main

        monkeypatch.setattr(main, "index_presigned_object", lambda application, file_id, presigned_url, s3_url, filename: (1, 1))

        resp = app_api_client.post(
            "/api/open/index",
            json={
                "file_id": "business-file-001",
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/business.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"file_id": "business-file-001"}

    def test_index_presigned_url_accepts_uuid_hex_file_id(self, app_api_client, monkeypatch):
        import main

        monkeypatch.setattr(main, "index_presigned_object", lambda application, file_id, presigned_url, s3_url, filename: (1, 1))

        resp = app_api_client.post(
            "/api/open/index",
            json={
                "file_id": "550e8400e29b41d4a716446655440000",
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/business.txt",
                "filename": "test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"file_id": "550e8400e29b41d4a716446655440000"}

    def test_index_presigned_url_can_infer_filename_from_s3_url(self, app_api_client, test_txt_path, monkeypatch):
        """``POST /api/open/index`` uses the object name when filename is omitted."""
        import main

        def index_object(application, file_id, presigned_url, s3_url, filename):
            main.index_file(main.application, file_id, Path(test_txt_path), filename, extra_metadata={"s3_url": s3_url})
            return 1, Path(test_txt_path).stat().st_size

        monkeypatch.setattr(main, "index_presigned_object", index_object)

        resp = app_api_client.post(
            "/api/open/index",
            json={
                "presigned_url": "https://example.com/presigned",
                "s3_url": "s3://rag/uploads/test_ai.txt",
            },
        )

        assert resp.status_code == 200, resp.text
        record = _uploaded_file(app_api_client, resp.json()["file_id"])
        assert record["filename"] == "test_ai.txt"


def _uploaded_file(api_client, file_id: str) -> dict:
    import main

    with main.application.store.app_context(api_client.app_id):
        documents = main.application.store.get_search_documents(main.application.store.build_file_filter([file_id]))
    document = next((item for item in documents if (item.get("metadata") or {}).get("file_id") == file_id), None)
    assert document is not None
    metadata = document.get("metadata") or {}
    return {
        "id": metadata["file_id"],
        "filename": metadata["filename"],
    }
