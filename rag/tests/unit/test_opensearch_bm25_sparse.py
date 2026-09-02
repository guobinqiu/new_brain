import json

import pytest


pytestmark = pytest.mark.unit


def test_opensearch_bm25_sparse_searches_with_auth(monkeypatch):
    from rag.sparse.opensearch_bm25 import OpenSearchBM25Sparse

    calls = []

    class Response:
        status_code = 200

        def __init__(self, body=None):
            self._body = body or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    def fake_post(url, *, json, timeout, auth):
        calls.append(("post", url, json, timeout, auth))
        return Response({
            "hits": {
                "hits": [{
                    "_id": "chunk-1",
                    "_score": 2.0,
                    "_source": {
                        "chunk_id": "chunk-1",
                        "content": "hello",
                        "metadata": {"file_id": "file-1"},
                    },
                }],
            },
        })

    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.post", fake_post)

    sparse = OpenSearchBM25Sparse("http://opensearch:9200", timeout=7, username="admin", password="Admin@123")
    sparse.start()
    results = sparse.search_index("hello", 3, app_id="imsdom", file_ids=["file-1"])

    assert sparse.ready is True
    assert calls[0][1] == "http://opensearch:9200/imsdom_chunks/_search"
    assert calls[0][2]["query"]["bool"]["filter"] == [{"terms": {"metadata.file_id": ["file-1"]}}]
    assert calls[0][4] == ("admin", "Admin@123")
    assert results == [{"id": "chunk-1", "content": "hello", "metadata": {"file_id": "file-1"}, "_score": 2.0}]


def test_opensearch_bm25_sparse_bulk_indexes_chunks(monkeypatch):
    from rag.scope import app_collection
    from rag.sparse.opensearch_bm25 import OpenSearchBM25Sparse

    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"errors": False}

    def fake_post(url, *, content, headers, timeout, auth):
        calls.append((url, content, headers, timeout, auth))
        return Response()

    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.post", fake_post)

    sparse = OpenSearchBM25Sparse("http://opensearch:9200", timeout=7)
    sparse.ready = True
    with app_collection("imsdom"):
        sparse.add_file_chunks(
            [{"id": "chunk-1", "content": "hello", "metadata": {"filename": "a.txt"}}],
            file_id="file-1",
        )

    url, content, headers, timeout, auth = calls[0]
    lines = [json.loads(line) for line in content.strip().splitlines()]
    assert url == "http://opensearch:9200/_bulk?refresh=wait_for"
    assert headers == {"Content-Type": "application/x-ndjson"}
    assert timeout == 7
    assert auth is None
    assert lines[0] == {"index": {"_index": "imsdom_chunks", "_id": "chunk-1"}}
    assert lines[1]["metadata"]["file_id"] == "file-1"


def test_opensearch_bm25_sparse_bulk_error_includes_item_reason(monkeypatch):
    from rag.scope import app_collection
    from rag.sparse.opensearch_bm25 import OpenSearchBM25Sparse

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "errors": True,
                "items": [
                    {
                        "index": {
                            "_id": "chunk-1",
                            "status": 429,
                            "error": {
                                "type": "cluster_block_exception",
                                "reason": "index blocked by read-only-allow-delete",
                            },
                        },
                    },
                ],
            }

    def fake_post(url, *, content, headers, timeout, auth):
        return Response()

    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.post", fake_post)

    sparse = OpenSearchBM25Sparse("http://opensearch:9200", timeout=7)
    sparse.ready = True
    with app_collection("imsdom"):
        with pytest.raises(RuntimeError, match="cluster_block_exception"):
            sparse.add_file_chunks(
                [{"id": "chunk-1", "content": "hello", "metadata": {"filename": "a.txt"}}],
                file_id="file-1",
            )


def test_opensearch_bm25_sparse_app_collection_lifecycle(monkeypatch):
    from rag.sparse.opensearch_bm25 import OpenSearchBM25Sparse

    calls = []

    class Response:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

    def fake_put(url, *, json, timeout, auth):
        calls.append(("put", url, json, timeout, auth))
        return Response()

    def fake_head(url, *, timeout, auth):
        calls.append(("head", url, timeout, auth))
        return Response()

    def fake_delete(url, *, timeout, auth):
        calls.append(("delete", url, timeout, auth))
        return Response()

    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.put", fake_put)
    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.head", fake_head)
    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.delete", fake_delete)

    sparse = OpenSearchBM25Sparse("http://opensearch:9200", timeout=7)

    assert sparse.ensure_app_collection("imsdom") == "imsdom_chunks"
    assert sparse.app_collection_exists("imsdom") is True
    assert sparse.drop_app_collection("imsdom") is True
    assert calls[0][0] == "put"
    assert calls[0][1] == "http://opensearch:9200/imsdom_chunks"
    assert calls[0][2]["mappings"]["properties"]["content"] == {"type": "text", "analyzer": "standard"}
    assert calls[1] == ("head", "http://opensearch:9200/imsdom_chunks", 7, None)
    assert calls[2] == ("delete", "http://opensearch:9200/imsdom_chunks", 7, None)


def test_opensearch_bm25_sparse_ensure_index_error_includes_body(monkeypatch):
    import httpx

    from rag.sparse.opensearch_bm25 import OpenSearchBM25Sparse

    class Response:
        status_code = 403
        text = '{"error":{"reason":"cluster create-index blocked"}}'

        def raise_for_status(self):
            request = httpx.Request("PUT", "http://opensearch:9200/imsdom_chunks")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    def fake_put(url, *, json, timeout, auth):
        return Response()

    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.put", fake_put)

    sparse = OpenSearchBM25Sparse("http://opensearch:9200", timeout=7)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        sparse.ensure_app_collection("imsdom")

    assert "cluster create-index blocked" in exc.value.response.text


def test_opensearch_bm25_sparse_lists_chunks_with_cursor(monkeypatch):
    from rag.scope import app_collection
    from rag.sparse.opensearch_bm25 import OpenSearchBM25Sparse

    calls = []

    class Response:
        status_code = 200

        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    def fake_post(url, *, json, timeout, auth):
        calls.append((url, json, timeout, auth))
        hits = [{
            "_id": "chunk-1",
            "_score": None,
            "_source": {
                "chunk_id": "chunk-1",
                "content": "hello",
                "metadata": {"file_id": "file-1", "chunk_index": 0},
            },
            "sort": [0, "chunk-1"],
        }]
        if "search_after" not in json:
            hits.append({
                "_id": "chunk-2",
                "_score": None,
                "_source": {
                    "chunk_id": "chunk-2",
                    "content": "next",
                    "metadata": {"file_id": "file-1", "chunk_index": 1},
                },
                "sort": [1, "chunk-2"],
            })
        return Response({
            "hits": {
                "hits": hits,
            },
        })

    monkeypatch.setattr("rag.sparse.opensearch_bm25.httpx.post", fake_post)

    sparse = OpenSearchBM25Sparse("http://opensearch:9200", timeout=7, username="admin", password="Admin@123")
    sparse.ready = True
    with app_collection("imsdom"):
        first = sparse.list_chunks(file_ids=["file-1"], limit=1)
        second = sparse.list_chunks(file_ids=["file-1"], limit=1, cursor=first["next_cursor"])

    assert first["documents"] == [{"id": "chunk-1", "content": "hello", "metadata": {"file_id": "file-1", "chunk_index": 0}, "_score": 0.0}]
    assert first["has_more"] is True
    assert first["next_cursor"]
    assert calls[0][0] == "http://opensearch:9200/imsdom_chunks/_search"
    assert calls[0][1]["query"]["bool"]["filter"] == [{"terms": {"metadata.file_id": ["file-1"]}}]
    assert calls[0][1]["sort"] == [{"metadata.chunk_index": "asc"}, {"chunk_id": "asc"}]
    assert "search_after" not in calls[0][1]
    assert calls[0][3] == ("admin", "Admin@123")
    assert second["documents"][0]["id"] == "chunk-1"
    assert calls[1][1]["search_after"] == [0, "chunk-1"]
