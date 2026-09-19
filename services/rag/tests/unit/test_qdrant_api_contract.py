import re
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from datetime import timedelta
from shared.config import StorageConfig


pytestmark = pytest.mark.unit


def test_index_file_indexes_presigned_file_synchronously(monkeypatch):
    from services.rag.core.api.services import files as service
    from services.rag.core.api.schemas import FileIndexRequest
    from services.rag.core.auth import Principal

    calls = []

    class AppScope:
        def __enter__(self):
            calls.append(("enter", "imsdom"))

        def __exit__(self, exc_type, exc, tb):
            calls.append(("exit", "imsdom"))

    class VectorClient:
        def ensure_app_collection(self, app_id):
            calls.append(("ensure", app_id))

        def app_collection_exists(self, app_id):
            calls.append(("exists", app_id))
            return True

        def app_scope(self, app_id):
            calls.append(("context", app_id))
            return AppScope()

    state = FastAPI().state
    state.vector_client = VectorClient()
    state.db_client = type(
        "Database",
        (),
        {
            "create_file": lambda self, app_id, file_id, filename, s3_url: calls.append(("db_create", file_id)),
            "mark_file_indexing": lambda self, app_id, file_id: calls.append(("db_indexing", file_id)),
            "upsert_file": lambda self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0: calls.append(("db_success", file_id, size, chunk_count)),
            "mark_file_failed": lambda self, app_id, file_id, error: calls.append(("db_failed", file_id)),
        },
    )()
    monkeypatch.setattr(service, "require_ready", lambda state: None)
    monkeypatch.setattr(service, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(
        service,
        "index_presigned_file",
        lambda application, file_id, presigned_url, s3_url, filename: calls.append(("index", file_id, s3_url, filename)) or (3, 10),
    )

    result = service.index_file(
        state,
        FileIndexRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag/docs/a.txt",
            filename="a.txt",
        ),
        Principal(type="app", app_id="imsdom"),
    )

    assert result == {"success": True, "error": None, "service": None, "retryable": False, "traceId": result["traceId"], "file_id": "abc123"}
    assert len(result["traceId"]) == 32
    assert calls == [
        ("exists", "imsdom"),
        ("db_create", "abc123"),
        ("db_indexing", "abc123"),
        ("context", "imsdom"),
        ("enter", "imsdom"),
        ("index", "abc123", "s3://rag/docs/a.txt", "a.txt"),
        ("exit", "imsdom"),
        ("db_success", "abc123", 10, 3),
    ]


def test_index_file_uses_application_parser(tmp_path):
    from services.rag.core.index import service as index_service
    from services.rag.core.scope import app_collection

    calls = []

    class Parser:
        def parse_file(self, presigned_url, *, filename):
            calls.append((presigned_url, filename))
            return {"blocks": [
                {"type": "text", "text": "hello"},
                {"type": "text", "text": "world"},
            ], "file_size": 5}

    class VectorClient:
        def add_file_chunks(self, chunks, file_id):
            calls.append(("vector", chunks, file_id))
            return len(chunks)

    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")

    state = FastAPI().state
    state.parser_client = Parser()
    state.vector_client = VectorClient()

    with app_collection("imsdom"):
        count, size = index_service.index_file(state, "file-1", "https://source/a.txt", "a.txt")

    assert count == 2
    assert size == 5
    assert calls[0] == ("https://source/a.txt", "a.txt")
    assert calls[1][0] == "vector"
    chunks = calls[1][1]
    assert [chunk["content"] for chunk in chunks] == ["hello", "world"]
    assert chunks[0]["id"] == index_service.stable_chunk_id("imsdom", "file-1", 0)
    assert chunks[0]["metadata"]["chunk_index"] == 0
    assert chunks[0]["metadata"]["filename"] == "a.txt"


def test_generated_file_id_is_standard_uuid():
    from services.rag.core.index.service import create_file_id

    file_id = create_file_id()

    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", file_id)


def test_storage_presign_uses_minio_endpoint(monkeypatch):
    from services.rag.core.api.services import files as service
    from services.rag.core.api.schemas import PresignRequest

    class FakeMinio:
        def __init__(self, endpoint, *, access_key, secret_key, secure):
            assert endpoint == "minio:9000"
            assert access_key == "dummy-access-key"
            assert secret_key == "dummy-secret-key"
            assert secure is False

        def presigned_get_object(self, bucket, object_name, expires):
            assert bucket == "rag"
            assert object_name == "docs/a.pdf"
            assert expires == timedelta(seconds=120)
            return "http://minio:9000/rag/docs/a.pdf?token=abc"

    monkeypatch.setattr(service, "Minio", FakeMinio)
    monkeypatch.setenv("S3_ACCESS_KEY", "dummy-access-key")
    monkeypatch.setenv("S3_SECRET_KEY", "dummy-secret-key")
    state = SimpleNamespace(config=SimpleNamespace(storage=StorageConfig(endpoint_url="http://minio:9000")))

    result = service.presign_object(state, PresignRequest(s3_url="s3://rag/docs/a.pdf", expires_in=120))

    assert result == {"presigned_url": "http://minio:9000/rag/docs/a.pdf?token=abc"}


def test_presign_route_is_admin_api_endpoint():
    from services.rag.app import main

    paths = {route.path for route in main.app.routes}

    assert "/api/rag/presign" in paths


def test_sync_index_route_is_registered():
    from services.rag.app import main

    routes = [(route.path, route.methods) for route in main.app.routes if hasattr(route, "methods")]

    assert any(path == "/api/rag/files" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/v1/rag/files" and "POST" in methods for path, methods in routes)


def testupload_file_to_storage_puts_object_in_bucket(monkeypatch):
    from services.rag.core.api.services import files as service

    calls = []

    class FakeMinio:
        def bucket_exists(self, bucket):
            calls.append(("bucket_exists", bucket))
            return False

        def make_bucket(self, bucket):
            calls.append(("make_bucket", bucket))

        def put_object(self, bucket, object_name, data, length, content_type):
            calls.append(("put_object", bucket, object_name, data.read(), length, content_type))

    monkeypatch.setattr(service, "minio_client", lambda config: FakeMinio())
    monkeypatch.setattr(service, "create_file_id", lambda: "abc123")
    config = StorageConfig(bucket="documents")

    result = service.upload_file_to_storage(config, "imsdom", "abc123", "docs/a.txt", BytesIO(b"hello"), 5, "text/plain")

    assert result == "s3://documents/uploads/imsdom/abc123/a.txt"
    assert calls == [
        ("bucket_exists", "documents"),
        ("make_bucket", "documents"),
        ("put_object", "documents", "uploads/imsdom/abc123/a.txt", b"hello", 5, "text/plain"),
    ]


def test_client_delete_file_removes_index_only(monkeypatch):
    from services.rag.core.api.services import files as service
    from services.rag.core.auth import Principal

    calls = []

    monkeypatch.setattr(service, "delete_index_file", lambda state, file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
    monkeypatch.setattr(service, "delete_storage_file", lambda config, app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

    result = service.client_delete_file(object(), "file-a", Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
    assert calls == [("index", "file-a", "imsdom")]


def test_delete_file_removes_index_and_storage_for_app_principal(monkeypatch):
    from services.rag.core.api.services import files as service
    from services.rag.core.auth import Principal

    calls = []

    monkeypatch.setattr(service, "delete_index_file", lambda state, file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
    monkeypatch.setattr(service, "delete_storage_file", lambda config, app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

    state = SimpleNamespace(config=SimpleNamespace(storage=StorageConfig(endpoint_url="http://minio:9000")))
    result = service.delete_file(state, "file-a", None, Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
    assert calls == [("index", "file-a", "imsdom"), ("storage", "imsdom", "file-a")]


def test_delete_index_file_deletes_vector_chunks(monkeypatch):
    from services.rag.core.api.services import files as service
    from services.rag.core.auth import Principal

    calls = []

    class VectorClient:
        def delete_file_chunks(self, file_id):
            calls.append(("vector_delete", file_id))
            return 2

    state = FastAPI().state
    state.db_client = type("Database", (), {"soft_delete_file": lambda self, app_id, file_id: 1})()
    monkeypatch.setattr(service, "require_ready", lambda state: None)
    monkeypatch.setattr(service, "scoped_vector", lambda state, principal: VectorClient())

    result = service.delete_index_file(state, "file-a", Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
    assert calls == [("vector_delete", "file-a")]


def test_files_list_uses_database_pagination_not_vector_scan(monkeypatch):
    from services.rag.core.api.services import files as service
    from services.rag.core.auth import Principal
    from services.rag.clients.db.base import FilePage, FileRecord

    calls = []

    class Database:
        def list_files(self, app_id, limit, cursor):
            calls.append(("database", app_id, limit, cursor))
            return FilePage(
                files=[
                    FileRecord(
                        id="file-a",
                        filename="a.txt",
                        chunk_count=2,
                        s3_url="s3://rag/uploads/imsdom/file-a/a.txt",
                    )
                ],
                next_cursor="11",
                has_more=True,
                total=3,
            )

    class VectorClient:
        def app_collection_exists(self, app_id):
            return True

    state = FastAPI().state
    state.ready = True
    state.db_client = Database()
    state.vector_client = VectorClient()

    result = service.files(state, limit=1, cursor="12", app_id="imsdom", principal=Principal(type="admin", app_id=""))

    assert result["files"] == [
        {
            "id": "file-a",
            "filename": "a.txt",
            "chunk_count": 2,
            "created_at": None,
            "indexed_at": None,
            "s3_url": "s3://rag/uploads/imsdom/file-a/a.txt",
            "size": None,
            "status": "success",
            "error": None,
        }
    ]
    assert result["next_cursor"] == "11"
    assert result["has_more"] is True
    assert result["total"] == 3
    assert calls == [("database", "imsdom", 1, "12")]
