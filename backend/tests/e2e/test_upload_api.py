import pytest


pytestmark = pytest.mark.e2e


class TestUploadAPI:
    def test_upload_txt(self, api_client, test_txt_path):
        """``POST /api/upload`` accepts a .txt file and returns status=ok."""
        with open(test_txt_path, "rb") as f:
            resp = api_client.post(
                "/api/upload", files={"file": ("test_ai.txt", f, "text/plain")}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        assert data["filename"] == "test_ai.txt"
        assert data["chunks"] > 0

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

    def test_upload_image_png(self, api_client, test_img_path):
        """POST /api/upload accepts a .png image file and returns status=ok."""
        with open(test_img_path, "rb") as f:
            resp = api_client.post(
                "/api/upload", files={"file": ("test_ocr.png", f, "image/png")}
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "ok"
        assert data["filename"] == "test_ocr.png"
        assert data["chunks"] > 0

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
