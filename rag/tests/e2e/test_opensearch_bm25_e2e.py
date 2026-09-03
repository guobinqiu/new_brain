import pytest

from rag.api.runtime import runtime


pytestmark = pytest.mark.e2e


def test_list_sparse_chunks_api_returns_opensearch_documents(app_api_client, api_client):
    sparse = runtime.application.sparse
    if sparse is None or getattr(sparse, "name", None) != "opensearch_bm25":
        pytest.skip("current config does not enable OpenSearch BM25")

    with runtime.application.store.app_context(app_api_client.app_id):
        sparse.add_file_chunks(
            [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "content": "opensearch bm25 document",
                    "metadata": {"filename": "bm25.txt", "chunk_index": 0, "s3_url": "s3://rag-test/bm25.txt"},
                },
                {
                    "id": "550e8400-e29b-41d4-a716-446655440001",
                    "content": "another document",
                    "metadata": {"filename": "other.txt", "chunk_index": 1, "s3_url": "s3://rag-test/other.txt"},
                },
            ],
            file_id="file-a",
        )

    resp = api_client.post("/api/open/rag/sparse/chunks", json={"app_id": app_api_client.app_id, "file_ids": ["file-a"]})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [chunk["content"] for chunk in body["chunks"]] == ["opensearch bm25 document", "another document"]
    assert body["chunks"][0]["file_id"] == "file-a"
    assert body["chunks"][0]["filename"] == "bm25.txt"
    assert body["has_more"] is False
