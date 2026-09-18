import uuid

import httpx
import pytest


pytestmark = pytest.mark.e2e


def test_cloud_upload_index_search_rerank_delete(cloud_server):
    admin = cloud_server
    app_id = "cloud_e2e_" + uuid.uuid4().hex
    marker = "cloud_document_" + uuid.uuid4().hex
    created = admin.post("/api/rag/apps", json={"app_id": app_id})
    assert created.status_code == 201
    file_id = None
    try:
        initialized = admin.post(f"/api/rag/apps/{app_id}/database")
        assert initialized.status_code == 200, initialized.text
        document = f"# Cloud Test\n\n{marker} The project uses vector search for document retrieval.\n"
        uploaded = admin.post(
            "/api/rag/upload", data={"app_id": app_id},
            files={"file": ("cloud-test.md", document.encode(), "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        upload = uploaded.json()
        file_id = upload["file_id"]
        presigned = admin.post("/api/rag/presign", json={"s3_url": upload["s3_url"]})
        assert presigned.status_code == 200
        with httpx.Client(
            base_url=admin.base_url, timeout=180, trust_env=False,
            headers={"Authorization": f"Bearer {created.json()['api_key']}"},
        ) as client:
            indexed = client.post("/api/v1/rag/files", json={
                **upload, "presigned_url": presigned.json()["presigned_url"],
            })
            assert indexed.status_code == 200, indexed.text
            records = admin.get("/api/rag/files", params={"app_id": app_id}).json()["files"]
            assert len(records) == 1
            assert records[0]["status"] == "success"
            assert records[0]["chunk_count"] > 0
            config = admin.get("/api/rag/config").json()
            assert config["capabilities"]["sparse_vector"] is False
            assert config["rerank_available"] is True
            for mode, rerank in (("dense", False), ("hybrid", True)):
                result = client.post("/api/v1/rag/search", json={
                    "query": "document retrieval vector search", "file_ids": [file_id],
                    "mode": mode, "rerank": rerank, "top_k": 1,
                })
                assert result.status_code == 200, result.text
                payload = result.json()
                assert payload["mode"] == "dense"
                assert payload["rerank"] is rerank
                assert marker in payload["results"][0]["content"]
            sparse = client.post("/api/v1/rag/search", json={"query": "test", "mode": "sparse"})
            assert sparse.status_code == 400
            deleted = admin.delete(f"/api/rag/files/{file_id}", params={"app_id": app_id})
            assert deleted.status_code == 200, deleted.text
            assert deleted.json()["deleted_chunks"] > 0
            file_id = None
            empty = client.post("/api/v1/rag/search", json={"query": "vector search", "mode": "dense", "rerank": False})
            assert empty.status_code == 200
            assert empty.json()["results"] == []
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
                assert deleted_app.status_code == 200
