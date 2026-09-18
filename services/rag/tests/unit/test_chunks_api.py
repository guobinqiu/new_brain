import pytest
from fastapi import FastAPI

from services.rag.core.api.services import files as service
from services.rag.core.api.schemas import ChunksQueryRequest


def _state(**values):
    state = FastAPI().state
    for key, value in values.items():
        setattr(state, key, value)
    return state


def test_chunks_filters_by_file_ids(monkeypatch):
    from services.rag.core.auth import Principal

    class VectorClient:
        def ensure_app_collection(self, app_id):
            return app_id

        def app_collection_exists(self, app_id):
            return True

        def list_chunks(self, file_ids=None, limit=50, cursor=None):
            assert file_ids == ["file-a", "file-b"]
            assert limit == 10
            assert cursor is None
            return {
                "documents": [{"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0}}],
                "next_cursor": None,
                "has_more": False,
            }

    state = _state(vector_client=VectorClient(), ready=True)

    page = service.chunks(state, ChunksQueryRequest(limit=10, file_ids=["file-a", "file-b"]), principal=Principal(type="app", app_id="tenant_filter"))

    assert page["chunks"][0]["file_id"] == "file-a"


def test_admin_chunks_can_select_app_collection(monkeypatch):
    from services.rag.core.auth import Principal

    calls = []

    class AppScope:
        def __enter__(self):
            calls.append(("enter", "tenant_a"))

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit", "tenant_a"))

    class VectorClient:
        def ensure_app_collection(self, app_id):
            calls.append(("ensure", app_id))
            return app_id

        def app_collection_exists(self, app_id):
            calls.append(("exists", app_id))
            return True

        def app_scope(self, app_id):
            calls.append(("context", app_id))
            return AppScope()

        def list_chunks(self, file_ids=None, limit=50, cursor=None):
            calls.append(("chunks", file_ids, limit, cursor))
            return {
                "documents": [{"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0}}],
                "next_cursor": None,
                "has_more": False,
            }

    state = _state(vector_client=VectorClient(), ready=True)

    page = service.chunks(state, ChunksQueryRequest(limit=10, app_id="tenant_a"), principal=Principal(type="admin", app_id="imsdom"))

    assert page["chunks"][0]["file_id"] == "file-a"
    assert calls == [
        ("exists", "tenant_a"),
        ("context", "tenant_a"),
        ("enter", "tenant_a"),
        ("chunks", None, 10, None),
        ("exit", "tenant_a"),
    ]


def test_chunks_query_accepts_file_ids_in_body(monkeypatch):
    from services.rag.core.auth import Principal

    class VectorClient:
        def ensure_app_collection(self, app_id):
            return app_id

        def app_collection_exists(self, app_id):
            return True

        def list_chunks(self, file_ids=None, limit=50, cursor=None):
            assert file_ids == ["file-a", "file-b"]
            return {
                "documents": [{"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0}}],
                "next_cursor": None,
                "has_more": False,
            }

    state = _state(vector_client=VectorClient(), ready=True)

    page = service.chunks(state, ChunksQueryRequest(file_ids=["file-a", "file-b"]), principal=Principal(type="admin", app_id="imsdom"))

    assert page["chunks"][0]["file_id"] == "file-a"

def test_chunks_returns_file_id_without_transform(monkeypatch):
    from services.rag.core.auth import Principal

    class VectorClient:
        def ensure_app_collection(self, app_id):
            return app_id

        def app_collection_exists(self, app_id):
            return True

        def list_chunks(self, file_ids=None, limit=50, cursor=None):
            return {
                "documents": [{"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0, "created_at": "2026-08-17T10:00:00+08:00"}}],
                "next_cursor": None,
                "has_more": False,
            }

    state = _state(vector_client=VectorClient(), ready=True)

    page = service.chunks(state, ChunksQueryRequest(), principal=Principal(type="admin", app_id="imsdom"))

    assert page["chunks"][0]["file_id"] == "file-a"
    assert page["chunks"][0]["created_at"] == "2026-08-17T10:00:00+08:00"


def test_dense_vector_returns_current_vector_vector(monkeypatch):
    from services.rag.core.auth import Principal

    class AppScope:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return None

    class VectorClient:
        def app_collection_exists(self, app_id):
            return True

        def app_scope(self, app_id):
            return AppScope()

        def get_dense_vector(self, chunk_id):
            assert chunk_id == "chunk-a"
            return [0.1, 0.2]

    state = _state(vector_client=VectorClient(), ready=True)

    result = service.dense_vector(state, "tenant_a", "chunk-a", Principal(type="admin", app_id=""))

    assert result == {"chunk_id": "chunk-a", "type": "dense", "vector": [0.1, 0.2]}
