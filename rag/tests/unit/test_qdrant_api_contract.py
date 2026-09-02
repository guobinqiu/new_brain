import re

import pytest
from datetime import timedelta


pytestmark = pytest.mark.unit


def test_index_object_indexes_presigned_object_synchronously(monkeypatch):
    from rag.api.runtime import runtime
    from rag.api.services import files as service
    from rag.api.schemas import ObjectIndexRequest
    from rag.auth import Principal

    calls = []

    class Context:
        def __enter__(self):
            calls.append(("enter", "imsdom"))

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit", "imsdom"))

    class Store:
        def ensure_app_collection(self, app_id):
            calls.append(("ensure", app_id))

        def app_collection_exists(self, app_id):
            calls.append(("exists", app_id))
            return True

        def app_context(self, app_id):
            calls.append(("context", app_id))
            return Context()

    class Database:
        def create_file(self, app_id, file_id, filename, s3_url, **kwargs):
            calls.append(("create", app_id, file_id, filename, s3_url, kwargs))

        def mark_file_indexing(self, app_id, file_id):
            calls.append(("indexing", app_id, file_id))

        def mark_file_failed(self, app_id, file_id, error):
            calls.append(("failed", app_id, file_id, error))

        def upsert_file(self, app_id, file_id, filename, s3_url, **kwargs):
            calls.append(("upsert", app_id, file_id, filename, s3_url, kwargs))

    monkeypatch.setattr(service, "require_ready", lambda: None)
    monkeypatch.setattr(service, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "sparse", None)
    monkeypatch.setattr(runtime.application, "database", Database())
    monkeypatch.setattr(
        service,
        "index_presigned_object",
        lambda application, file_id, presigned_url, s3_url, filename: calls.append(("index", file_id, s3_url, filename)) or (3, 10),
    )

    result = service.index_object(
        ObjectIndexRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag/docs/a.txt",
            filename="a.txt",
        ),
        Principal(type="app", app_id="imsdom"),
    )

    assert result == {"file_id": "abc123"}
    assert calls == [
        ("exists", "imsdom"),
        ("create", "imsdom", "abc123", "a.txt", "s3://rag/docs/a.txt", {}),
        ("indexing", "imsdom", "abc123"),
        ("context", "imsdom"),
        ("enter", "imsdom"),
        ("index", "abc123", "s3://rag/docs/a.txt", "a.txt"),
        ("upsert", "imsdom", "abc123", "a.txt", "s3://rag/docs/a.txt", {"size": 10, "chunk_count": 3}),
        ("exit", "imsdom"),
    ]


def test_create_index_job_enqueues_async_job(monkeypatch):
    from rag.api.runtime import runtime
    from rag.api.services import files as service
    from rag.api.schemas import AdminIndexJobRequest
    from rag.auth import Principal

    enqueued = []

    class Store:
        def app_collection_exists(self, app_id):
            return True

    class Database:
        def create_file(self, app_id, file_id, filename, s3_url, **kwargs):
            enqueued.append(("create", app_id, file_id, filename, s3_url, kwargs))

        def mark_file_failed(self, app_id, file_id, error):
            enqueued.append(("failed", app_id, file_id, error))

    monkeypatch.setattr(service, "require_ready", lambda: None)
    monkeypatch.setattr(service, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(runtime.application, "store", Store())
    monkeypatch.setattr(runtime.application, "sparse", None)
    monkeypatch.setattr(runtime.application, "database", Database())
    monkeypatch.setattr(
        service,
        "enqueue_index_job",
        lambda **kwargs: enqueued.append(kwargs) or {"file_id": kwargs["file_id"]},
    )

    result = service.create_index_job(
        AdminIndexJobRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag/docs/a.txt",
            filename="a.txt",
            file_id="550e8400-e29b-41d4-a716-446655440000",
        ),
        Principal(type="app", app_id="imsdom"),
    )

    assert result == {"file_id": "550e8400-e29b-41d4-a716-446655440000"}
    assert enqueued == [
        ("create", "imsdom", "550e8400-e29b-41d4-a716-446655440000", "a.txt", "s3://rag/docs/a.txt", {}),
        {
            "app_id": "imsdom",
            "file_id": "550e8400-e29b-41d4-a716-446655440000",
            "presigned_url": "https://example.com/presigned",
            "s3_url": "s3://rag/docs/a.txt",
            "filename": "a.txt",
        }
    ]
    assert all("job_id" not in kwargs for kwargs in enqueued)


def test_index_file_uses_application_parser(tmp_path):
    from rag.index.service import index_file

    calls = []

    class Parser:
        def parse_file(self, path, *, original_filename, ocr):
            calls.append((path, original_filename, ocr))
            return [{"id": "550e8400-e29b-41d4-a716-446655440000", "content": "hello", "metadata": {"filename": original_filename, "chunk_index": 0}}]

    class Store:
        def add_file_chunks(self, chunks, file_id):
            calls.append(("store", chunks, file_id))
            return len(chunks)

    class Application:
        parser = Parser()
        store = Store()
        ocr = object()

    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")

    count = index_file(Application(), "file-1", path, "a.txt")

    assert count == 1
    assert calls[0] == (str(path), "a.txt", Application.ocr)
    assert calls[1][0] == "store"


def test_index_file_writes_configured_indexed_sparse_backend(tmp_path):
    from rag.index.service import index_file

    calls = []

    class Parser:
        def parse_file(self, path, *, original_filename, ocr):
            return [{"id": "chunk-1", "content": "hello", "metadata": {"filename": original_filename, "chunk_index": 0}}]

    class Store:
        def add_file_chunks(self, chunks, file_id):
            calls.append(("store", file_id, chunks))
            return len(chunks)

    class Sparse:
        def delete_file_chunks(self, file_id):
            calls.append(("sparse_delete", file_id))

        def add_file_chunks(self, chunks, file_id):
            calls.append(("sparse_add", file_id, chunks))

    class Application:
        parser = Parser()
        store = Store()
        sparse = Sparse()
        ocr = object()

    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")

    count = index_file(Application(), "file-1", path, "a.txt")

    assert count == 1
    assert [call[0] for call in calls] == ["store", "sparse_delete", "sparse_add"]
    assert calls[1] == ("sparse_delete", "file-1")
    assert calls[2][1] == "file-1"


def test_create_index_job_returns_429_when_queue_rejects(monkeypatch):
    from fastapi import HTTPException
    from rag.api.runtime import runtime
    from rag.api.services import files as service
    from rag.api.schemas import AdminIndexJobRequest
    from rag.auth import Principal
    from rag.index.queue import IndexQueueRejected

    calls = []

    class Database:
        def create_file(self, app_id, file_id, filename, s3_url, **kwargs):
            calls.append(("create", app_id, file_id, filename, s3_url, kwargs))

        def mark_file_failed(self, app_id, file_id, error):
            calls.append(("failed", app_id, file_id, error))

    monkeypatch.setattr(service, "require_ready", lambda: None)
    monkeypatch.setattr(service, "require_app_database", lambda principal: None)
    monkeypatch.setattr(service, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(runtime.application, "database", Database())
    monkeypatch.setattr(service, "enqueue_index_job", lambda **kwargs: (_ for _ in ()).throw(IndexQueueRejected("queue full")))

    with pytest.raises(HTTPException) as exc:
        service.create_index_job(
            AdminIndexJobRequest(
                presigned_url="https://example.com/presigned",
                s3_url="s3://rag/docs/a.txt",
                filename="a.txt",
                file_id="550e8400-e29b-41d4-a716-446655440000",
            ),
            Principal(type="app", app_id="imsdom"),
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "queue full"
    assert calls == [
        ("create", "imsdom", "550e8400-e29b-41d4-a716-446655440000", "a.txt", "s3://rag/docs/a.txt", {}),
        ("failed", "imsdom", "550e8400-e29b-41d4-a716-446655440000", "queue full"),
    ]


def test_admin_index_job_requires_file_id():
    from rag.api.schemas import AdminIndexJobRequest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdminIndexJobRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag/docs/a.txt",
            filename="a.txt",
        )


def test_generated_file_id_is_standard_uuid():
    from rag.index.service import create_file_id

    file_id = create_file_id()

    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", file_id)


def test_storage_presign_uses_minio_and_public_endpoint(monkeypatch):
    from rag.api.services import files as service
    from rag.api.schemas import PresignRequest

    class FakeMinio:
        def presigned_get_object(self, bucket, object_name, expires):
            assert bucket == "rag"
            assert object_name == "docs/a.pdf"
            assert expires == timedelta(seconds=120)
            return "http://minio:9000/rag/docs/a.pdf?token=abc"

    monkeypatch.setattr(service, "minio_client", lambda: FakeMinio())
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.delenv("S3_PUBLIC_ENDPOINT_URL", raising=False)

    result = service.presign_object(PresignRequest(s3_url="s3://rag/docs/a.pdf", expires_in=120))

    assert result == {"presigned_url": "http://minio:9000/rag/docs/a.pdf?token=abc"}


def test_presign_route_is_admin_api_endpoint():
    import main

    paths = {route.path for route in main.app.routes}

    assert "/api/open/rag/presign" in paths


def test_sync_and_async_index_routes_are_registered():
    import main

    routes = [(route.path, route.methods) for route in main.app.routes if hasattr(route, "methods")]

    assert any(path == "/api/open/rag/files" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/open/rag/files/jobs" and "POST" in methods for path, methods in routes)


def testupload_file_to_storage_puts_object_in_bucket(monkeypatch):
    from rag.api.services import files as service

    calls = []

    class FakeMinio:
        def bucket_exists(self, bucket):
            calls.append(("bucket_exists", bucket))
            return False

        def make_bucket(self, bucket):
            calls.append(("make_bucket", bucket))

        def put_object(self, bucket, object_name, data, length, content_type):
            calls.append(("put_object", bucket, object_name, data.read(), length, content_type))

    monkeypatch.setattr(service, "minio_client", lambda: FakeMinio())
    monkeypatch.setattr(service, "create_file_id", lambda: "abc123")
    monkeypatch.setenv("S3_BUCKET", "rag")

    result = service.upload_file_to_storage("imsdom", "abc123", "docs/a.txt", b"hello", "text/plain")

    assert result == "s3://rag/uploads/imsdom/abc123/a.txt"
    assert calls == [
        ("bucket_exists", "rag"),
        ("make_bucket", "rag"),
        ("put_object", "rag", "uploads/imsdom/abc123/a.txt", b"hello", 5, "text/plain"),
    ]


def test_client_delete_file_removes_index_only(monkeypatch):
    from rag.api.services import files as service
    from rag.auth import Principal

    calls = []

    monkeypatch.setattr(service, "delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
    monkeypatch.setattr(service, "delete_storage_file", lambda app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

    result = service.client_delete_file("file-a", Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
    assert calls == [("index", "file-a", "imsdom")]


def test_delete_index_file_deletes_configured_indexed_sparse_backend(monkeypatch):
    from rag.api.runtime import runtime
    from rag.api.services import files as service
    from rag.auth import Principal

    calls = []

    class Store:
        def delete_file_chunks(self, file_id):
            calls.append(("store_delete", file_id))
            return 2

    class Database:
        def soft_delete_file(self, app_id, file_id):
            calls.append(("soft_delete", app_id, file_id))

    class Sparse:
        def delete_file_chunks(self, file_id):
            calls.append(("sparse_delete", file_id))

    class Context:
        def __enter__(self):
            calls.append(("enter",))

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit",))

    monkeypatch.setattr(service, "require_ready", lambda: None)
    monkeypatch.setattr(service, "scoped_store", lambda principal: Store())
    monkeypatch.setattr(service, "store_context", lambda principal: Context())
    monkeypatch.setattr(runtime.application, "database", Database())
    monkeypatch.setattr(runtime.application, "sparse", Sparse())

    result = service.delete_index_file("file-a", Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
    assert calls == [
        ("store_delete", "file-a"),
        ("enter",),
        ("sparse_delete", "file-a"),
        ("exit",),
        ("soft_delete", "imsdom", "file-a"),
    ]
