import uuid

import pytest

from services.rag.tests.e2e.helpers import AppApiClient, index_uploaded_file


pytestmark = pytest.mark.e2e


def test_txt_paragraphs_remain_separate_in_cloud_index(cloud_server, tmp_path):
    admin = cloud_server
    app_id = "paragraph_e2e_" + uuid.uuid4().hex
    created = admin.post("/api/rag/apps", json={"app_id": app_id})
    assert created.status_code == 201
    app = AppApiClient(admin, app_id, created.json()["api_key"])
    file_id = None
    try:
        initialized = admin.post(f"/api/rag/apps/{app_id}/database")
        assert initialized.status_code == 200, initialized.text
        paragraphs = ["第一段介绍专有名词。", "第二段介绍索引策略。", "第三段介绍解析流程。"]
        path = tmp_path / "paragraphs.txt"
        path.write_text("\n\n".join(paragraphs), encoding="utf-8")
        file_id = index_uploaded_file(app, admin, path)
        response = admin.post("/api/rag/chunks", json={"app_id": app_id, "file_ids": [file_id], "limit": 10})
        assert response.status_code == 200, response.text
        chunks = sorted(response.json()["chunks"], key=lambda chunk: chunk["chunk_index"])
        assert [chunk["content"] for chunk in chunks] == paragraphs
    finally:
        try:
            if file_id is not None:
                deleted = admin.delete(f"/api/rag/files/{file_id}", params={"app_id": app_id})
                assert deleted.status_code == 200, deleted.text
        finally:
            try:
                dropped = admin.delete(f"/api/rag/apps/{app_id}/database")
                assert dropped.status_code in (200, 404), dropped.text
            finally:
                deleted_app = admin.delete(f"/api/rag/apps/{app_id}")
                assert deleted_app.status_code == 200, deleted_app.text
