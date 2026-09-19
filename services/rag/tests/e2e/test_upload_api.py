import uuid

import httpx
import pytest

from services.rag.tests.e2e.helpers import index_uploaded_file, indexed_file_record, presign_file, upload_file


pytestmark = pytest.mark.e2e


class TestUploadAPI:
    def test_upload_txt_uploads_object(self, app_api_client, api_client, test_txt_path, rag_server):
        """``POST /api/rag/upload`` stores a .txt file in object storage and returns s3_url."""
        data = upload_file(api_client, app_api_client.app_id, test_txt_path, filename="test_ai.txt")

        uuid.UUID(data["file_id"])
        assert data["s3_url"] == f"s3://{rag_server.bucket}/uploads/{app_api_client.app_id}/{data['file_id']}/test_ai.txt"
        assert data["filename"] == "test_ai.txt"
        with httpx.Client(trust_env=False, timeout=30) as storage:
            downloaded = storage.get(presign_file(api_client, data["s3_url"]))
        assert downloaded.status_code == 200
        with open(test_txt_path, "rb") as source:
            assert downloaded.content == source.read()

    def test_upload_unsupported_type(self, app_api_client, api_client, tmp_path):
        """Uploading an unsupported file type returns 400."""
        bad = tmp_path / "data.xyz"
        bad.write_text("content")
        with open(bad, "rb") as f:
            resp = api_client.post(
                "/api/rag/upload", data={"app_id": app_api_client.app_id}, files={"file": ("data.xyz", f, "application/octet-stream")}
            )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.text

    def test_upload_image_png_is_rejected(self, app_api_client, api_client, test_img_path):
        """The upload API rejects images outside the document format contract."""
        with open(test_img_path, "rb") as image:
            response = api_client.post(
                "/api/rag/upload",
                data={"app_id": app_api_client.app_id},
                files={"file": ("test_image.png", image, "image/png")},
            )

        assert response.status_code == 400
        assert "Unsupported file type" in response.text

    def test_upload_xlsx_uploads_object(self, app_api_client, api_client, tmp_path, rag_server):
        """``POST /api/rag/upload`` stores a .xlsx file."""
        xlsx_file = tmp_path / "table.xlsx"
        xlsx_file.write_bytes(b"xlsx content")

        data = upload_file(
            api_client,
            app_api_client.app_id,
            xlsx_file,
            filename="table.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        uuid.UUID(data["file_id"])
        assert data["s3_url"] == f"s3://{rag_server.bucket}/uploads/{app_api_client.app_id}/{data['file_id']}/table.xlsx"
        assert data["filename"] == "table.xlsx"

    def test_upload_no_filename(self, app_api_client, api_client, tmp_path):
        """Uploading a file with no filename returns a client error."""
        bad = tmp_path / "test.txt"
        bad.write_text("content")
        with open(bad, "rb") as f:
            resp = api_client.post(
                "/api/rag/upload", data={"app_id": app_api_client.app_id}, files={"file": ("", f, "text/plain")}
            )
        assert resp.status_code in (400, 422), (
            f"Expected 400 or 422, got {resp.status_code}: {resp.text}"
        )

    def test_index_presigned_url_indexes_uploaded_file(self, app_api_client, api_client, test_txt_path):
        """``POST /api/v1/rag/files`` indexes an uploaded object through a real presigned URL."""
        file_id = index_uploaded_file(app_api_client, api_client, test_txt_path, filename="test_ai.txt")
        record = indexed_file_record(app_api_client, file_id)
        assert record["filename"] == "test_ai.txt"

        search = app_api_client.post("/api/v1/rag/search", json={"query": "人工智能", "file_ids": [file_id]})
        assert search.status_code == 200, search.text
        result = search.json()["results"][0]
        assert "人工智能" in result["content"]

    def test_index_presigned_url_generates_file_id_when_omitted(self, app_api_client, api_client, test_txt_path):
        """``POST /api/v1/rag/files`` generates a file_id when caller omits it."""
        uploaded = upload_file(api_client, app_api_client.app_id, test_txt_path, filename="test_ai.txt")
        presigned_url = presign_file(api_client, uploaded["s3_url"])

        resp = app_api_client.post(
            "/api/v1/rag/files",
            json={
                "presigned_url": presigned_url,
                "s3_url": uploaded["s3_url"],
                "filename": uploaded["filename"],
            },
        )

        assert resp.status_code == 200, resp.text
        uuid.UUID(resp.json()["file_id"])

    def test_index_presigned_url_accepts_caller_uuid_file_id(self, app_api_client, api_client, test_txt_path):
        """``POST /api/v1/rag/files`` accepts caller-provided UUID file_id."""
        uploaded = upload_file(api_client, app_api_client.app_id, test_txt_path, filename="test_ai.txt")
        presigned_url = presign_file(api_client, uploaded["s3_url"])

        resp = app_api_client.post(
            "/api/v1/rag/files",
            json={
                "file_id": "550e8400-e29b-41d4-a716-446655440000",
                "presigned_url": presigned_url,
                "s3_url": uploaded["s3_url"],
                "filename": uploaded["filename"],
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True, "error": None, "service": None, "retryable": False, "traceId": resp.json()["traceId"], "file_id": "550e8400-e29b-41d4-a716-446655440000"}
        assert len(resp.json()["traceId"]) == 32

    def test_index_presigned_url_accepts_custom_file_id(self, app_api_client, api_client, test_txt_path):
        uploaded = upload_file(api_client, app_api_client.app_id, test_txt_path, filename="test_ai.txt")
        presigned_url = presign_file(api_client, uploaded["s3_url"])
        file_id = "550e8400-e29b-41d4-a716-446655440012"

        resp = app_api_client.post(
            "/api/v1/rag/files",
            json={
                "file_id": file_id,
                "presigned_url": presigned_url,
                "s3_url": uploaded["s3_url"],
                "filename": uploaded["filename"],
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True, "error": None, "service": None, "retryable": False, "traceId": resp.json()["traceId"], "file_id": file_id}
        assert len(resp.json()["traceId"]) == 32

    def test_index_presigned_url_accepts_uuid_hex_file_id(self, app_api_client, api_client, test_txt_path):
        uploaded = upload_file(api_client, app_api_client.app_id, test_txt_path, filename="test_ai.txt")
        presigned_url = presign_file(api_client, uploaded["s3_url"])

        resp = app_api_client.post(
            "/api/v1/rag/files",
            json={
                "file_id": "550e8400e29b41d4a716446655440000",
                "presigned_url": presigned_url,
                "s3_url": uploaded["s3_url"],
                "filename": uploaded["filename"],
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json() == {"success": True, "error": None, "service": None, "retryable": False, "traceId": resp.json()["traceId"], "file_id": "550e8400e29b41d4a716446655440000"}
        assert len(resp.json()["traceId"]) == 32

    def test_index_presigned_url_can_infer_filename_from_s3_url(self, app_api_client, api_client, test_txt_path):
        """``POST /api/v1/rag/files`` uses the object name when filename is omitted."""
        uploaded = upload_file(api_client, app_api_client.app_id, test_txt_path, filename="test_ai.txt")
        presigned_url = presign_file(api_client, uploaded["s3_url"])

        resp = app_api_client.post(
            "/api/v1/rag/files",
            json={
                "presigned_url": presigned_url,
                "s3_url": uploaded["s3_url"],
            },
        )

        assert resp.status_code == 200, resp.text
        record = indexed_file_record(app_api_client, resp.json()["file_id"])
        assert record["filename"] == "test_ai.txt"
