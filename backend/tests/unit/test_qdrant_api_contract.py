import re

import pytest
from datetime import timedelta


pytestmark = pytest.mark.unit


def test_index_chunks_returns_file_id_after_sync_index(monkeypatch, tmp_path):
    import main

    indexed = []
    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "index_file", lambda application, file_id, path, filename, extra_metadata=None: indexed.append((application, file_id, path, filename, extra_metadata)) or 3)

    path = tmp_path / "faq.txt"
    path.write_text("content", encoding="utf-8")

    result = main.index_chunks(str(path), filename="faq.txt")

    assert result == {"file_id": "abc123"}
    assert indexed == [(main.application, "abc123", path, "faq.txt", None)]


def test_index_object_indexes_presigned_object_synchronously(monkeypatch):
    import main
    from auth import Principal

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

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main.application, "store", Store())
    monkeypatch.setattr(
        main,
        "index_presigned_object",
        lambda application, file_id, presigned_url, s3_url, filename: calls.append(("index", file_id, s3_url, filename)) or 3,
    )

    result = main.index_object(
        main.ObjectIndexRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag-dev/docs/a.txt",
            filename="a.txt",
        ),
        Principal(type="app", app_id="imsdom"),
    )

    assert result == {"file_id": "abc123"}
    assert calls == [
        ("exists", "imsdom"),
        ("context", "imsdom"),
        ("enter", "imsdom"),
        ("index", "abc123", "s3://rag-dev/docs/a.txt", "a.txt"),
        ("exit", "imsdom"),
    ]


def test_create_index_job_enqueues_async_job(monkeypatch):
    import main
    from auth import Principal

    enqueued = []

    class Store:
        def app_collection_exists(self, app_id):
            return True

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main.application, "store", Store())
    monkeypatch.setattr(
        main,
        "enqueue_index_job",
        lambda **kwargs: enqueued.append(kwargs) or {"file_id": kwargs["file_id"]},
    )

    result = main.create_index_job(
        main.AdminIndexJobRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag-dev/docs/a.txt",
            filename="a.txt",
            file_id="550e8400e29b41d4a716446655440000",
        ),
        Principal(type="app", app_id="imsdom"),
    )

    assert result == {"file_id": "550e8400e29b41d4a716446655440000"}
    assert enqueued == [
        {
            "app_id": "imsdom",
            "file_id": "550e8400e29b41d4a716446655440000",
            "presigned_url": "https://example.com/presigned",
            "s3_url": "s3://rag-dev/docs/a.txt",
            "filename": "a.txt",
        }
    ]
    assert all("job_id" not in kwargs for kwargs in enqueued)


def test_create_index_job_returns_429_when_queue_rejects(monkeypatch):
    import main
    from auth import Principal
    from indexing.queue import IndexQueueRejected

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "_require_app_database", lambda principal: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "enqueue_index_job", lambda **kwargs: (_ for _ in ()).throw(IndexQueueRejected("queue full")))

    with pytest.raises(main.HTTPException) as exc:
        main.create_index_job(
            main.AdminIndexJobRequest(
                presigned_url="https://example.com/presigned",
                s3_url="s3://rag-dev/docs/a.txt",
                filename="a.txt",
                file_id="550e8400e29b41d4a716446655440000",
            ),
            Principal(type="app", app_id="imsdom"),
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "queue full"


def test_admin_index_job_requires_file_id():
    import main
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        main.AdminIndexJobRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag-dev/docs/a.txt",
            filename="a.txt",
        )


def test_recent_search_traces_returns_recent_rows(monkeypatch):
    import main

    main._search_traces.clear()
    main._search_traces.extend(
        [
            {"trace_id": "trace-1"},
            {"trace_id": "trace-2"},
            {"trace_id": "trace-3"},
        ]
    )

    page = main._recent_search_traces(limit=2)

    assert page == {"traces": [{"trace_id": "trace-1"}, {"trace_id": "trace-2"}]}


def test_generated_file_id_is_uuid_hex_without_prefix_or_dash():
    from indexing.service import create_file_id

    file_id = create_file_id()

    assert re.fullmatch(r"[0-9a-f]{32}", file_id)


def test_storage_presign_uses_minio_and_public_endpoint(monkeypatch):
    import main

    class FakeMinio:
        def presigned_get_object(self, bucket, object_name, expires):
            assert bucket == "rag-dev"
            assert object_name == "docs/a.pdf"
            assert expires == timedelta(seconds=120)
            return "http://minio:9000/rag-dev/docs/a.pdf?token=abc"

    monkeypatch.setattr(main, "_minio_client", lambda: FakeMinio())
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.delenv("S3_PUBLIC_ENDPOINT_URL", raising=False)

    result = main.presign_object(main.PresignRequest(s3_url="s3://rag-dev/docs/a.pdf", expires_in=120))

    assert result == {"presigned_url": "http://minio:9000/rag-dev/docs/a.pdf?token=abc"}


def test_presign_route_is_admin_api_endpoint():
    import main

    paths = {route.path for route in main.app.routes}

    assert "/api/presign" in paths


def test_sync_and_async_index_routes_are_separate():
    import main

    routes = [(route.path, route.methods) for route in main.app.routes if hasattr(route, "methods")]

    assert any(path == "/api/open/index" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/open/index/jobs" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/index" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/index/jobs" and "POST" in methods for path, methods in routes)


def test_upload_file_to_storage_puts_object_in_bucket(monkeypatch):
    import main

    calls = []

    class FakeMinio:
        def bucket_exists(self, bucket):
            calls.append(("bucket_exists", bucket))
            return False

        def make_bucket(self, bucket):
            calls.append(("make_bucket", bucket))

        def put_object(self, bucket, object_name, data, length, content_type):
            calls.append(("put_object", bucket, object_name, data.read(), length, content_type))

    monkeypatch.setattr(main, "_minio_client", lambda: FakeMinio())
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setenv("S3_BUCKET", "rag-dev")

    result = main._upload_file_to_storage("imsdom", "abc123", "docs/a.txt", b"hello", "text/plain")

    assert result == "s3://rag-dev/uploads/imsdom/abc123/a.txt"
    assert calls == [
        ("bucket_exists", "rag-dev"),
        ("make_bucket", "rag-dev"),
        ("put_object", "rag-dev", "uploads/imsdom/abc123/a.txt", b"hello", 5, "text/plain"),
    ]


def test_client_delete_file_removes_index_only(monkeypatch):
    import main
    from auth import Principal

    calls = []

    monkeypatch.setattr(main, "_delete_index_file", lambda file_id, principal: calls.append(("index", file_id, principal.app_id)) or {"deleted_chunks": 2})
    monkeypatch.setattr(main, "_delete_storage_file", lambda app_id, file_id: calls.append(("storage", app_id, file_id)) or 1)

    result = main.client_delete_file("file-a", Principal(type="app", app_id="imsdom"))

    assert result == {"deleted_chunks": 2}
    assert calls == [("index", "file-a", "imsdom")]
