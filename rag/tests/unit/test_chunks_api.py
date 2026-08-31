from rag.api.runtime import runtime
from rag.api.services import files as service
from rag.api.schemas import ChunksQueryRequest


def test_chunks_filters_by_file_ids(monkeypatch):
    from rag.auth import Principal

    class Store:
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

    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "ready", True)

    page = service.chunks(ChunksQueryRequest(limit=10, file_ids=["file-a", "file-b"]), principal=Principal(type="app", app_id="tenant_filter"))

    assert page["chunks"][0]["file_id"] == "file-a"


def test_admin_chunks_can_select_app_collection(monkeypatch):
    from rag.auth import Principal

    calls = []

    class Context:
        def __enter__(self):
            calls.append(("enter", "tenant_a"))

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit", "tenant_a"))

    class Store:
        def ensure_app_collection(self, app_id):
            calls.append(("ensure", app_id))
            return app_id

        def app_collection_exists(self, app_id):
            calls.append(("exists", app_id))
            return True

        def app_context(self, app_id):
            calls.append(("context", app_id))
            return Context()

        def list_chunks(self, file_ids=None, limit=50, cursor=None):
            calls.append(("chunks", file_ids, limit, cursor))
            return {
                "documents": [{"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0}}],
                "next_cursor": None,
                "has_more": False,
            }

    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "ready", True)

    page = service.chunks(ChunksQueryRequest(limit=10, app_id="tenant_a"), principal=Principal(type="admin", app_id="imsdom"))

    assert page["chunks"][0]["file_id"] == "file-a"
    assert calls == [
        ("exists", "tenant_a"),
        ("context", "tenant_a"),
        ("enter", "tenant_a"),
        ("chunks", None, 10, None),
        ("exit", "tenant_a"),
    ]


def test_chunks_query_accepts_file_ids_in_body(monkeypatch):
    from rag.auth import Principal

    class Store:
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

    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "ready", True)

    page = service.chunks(ChunksQueryRequest(file_ids=["file-a", "file-b"]), principal=Principal(type="admin", app_id="imsdom"))

    assert page["chunks"][0]["file_id"] == "file-a"

def test_chunks_returns_file_id_without_transform(monkeypatch):
    from rag.auth import Principal

    class Store:
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

    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "ready", True)

    page = service.chunks(ChunksQueryRequest(), principal=Principal(type="admin", app_id="imsdom"))

    assert page["chunks"][0]["file_id"] == "file-a"
    assert page["chunks"][0]["created_at"] == "2026-08-17T10:00:00+08:00"
