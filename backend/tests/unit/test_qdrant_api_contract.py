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

    class FakeJob:
        id = "job123"

    class Store:
        def app_collection_exists(self, app_id):
            return True

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "create_job_id", lambda: "job123")
    monkeypatch.setattr(main.application, "store", Store())
    monkeypatch.setattr(
        main,
        "enqueue_index_job",
        lambda **kwargs: enqueued.append(kwargs) or FakeJob(),
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

    assert result == {"job_id": "job123"}
    assert enqueued == [
        {
            "job_id": "job123",
            "app_id": "imsdom",
            "file_id": "550e8400e29b41d4a716446655440000",
            "presigned_url": "https://example.com/presigned",
            "s3_url": "s3://rag-dev/docs/a.txt",
            "filename": "a.txt",
        }
    ]


def test_create_index_job_returns_429_when_queue_rejects(monkeypatch):
    import main
    from auth import Principal
    from indexing.queue import IndexQueueRejected

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "_require_app_database", lambda principal: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "create_job_id", lambda: "job123")
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


def test_index_jobs_status_returns_index_jobs(monkeypatch):
    import main
    from auth import Principal

    class FakeJob:
        id = "job123"
        created_at = None
        enqueued_at = None
        started_at = None
        ended_at = None
        exc_info = None
        result = {"app_id": "imsdom", "file_id": "abc123", "chunk_count": 3}
        meta = {"app_id": "imsdom", "file_id": "abc123"}

        def get_status(self, refresh=True):
            return "finished"

    monkeypatch.setattr(main, "get_index_job", lambda job_id: FakeJob())

    result = main.client_index_jobs_status(main.IndexJobsStatusRequest(job_ids=["job123"]), Principal(type="app", app_id="imsdom"))

    assert result == {
        "jobs": [
            {
                "app_id": "imsdom",
                "file_id": "abc123",
                "job_id": "job123",
                "status": "finished",
                "filename": None,
                "s3_url": None,
                "chunk_count": 3,
                "error": None,
                "created_at": None,
                "enqueued_at": None,
                "started_at": None,
                "ended_at": None,
            }
        ]
    }


def test_index_jobs_status_matches_multiple_job_ids(monkeypatch):
    import main
    from auth import Principal

    class FakeJob:
        def __init__(self, job_id):
            self.id = job_id
            self.created_at = None
            self.enqueued_at = None
            self.started_at = None
            self.ended_at = None
            self.exc_info = None
            self.result = {"app_id": "imsdom", "file_id": "abc123", "chunk_count": 3}
            self.meta = {"app_id": "imsdom", "file_id": "abc123"}

        def get_status(self, refresh=True):
            return "finished"

    monkeypatch.setattr(main, "get_index_job", lambda job_id: FakeJob(job_id))

    result = main.client_index_jobs_status(
        main.IndexJobsStatusRequest(job_ids=["job123", "job456"]),
        Principal(type="app", app_id="imsdom"),
    )

    assert [job["job_id"] for job in result["jobs"]] == ["job123", "job456"]
    assert all(job["status"] == "finished" for job in result["jobs"])


def test_index_jobs_status_normalizes_job_status_enum(monkeypatch):
    import main
    from auth import Principal

    class FakeStatus:
        value = "failed"

        def __str__(self):
            return "JobStatus.FAILED"

    class FakeJob:
        id = "job123"
        created_at = None
        enqueued_at = None
        started_at = None
        ended_at = None
        exc_info = "Work-horse terminated unexpectedly"
        result = None
        meta = {"app_id": "imsdom", "file_id": "abc123"}

        def get_status(self, refresh=True):
            return FakeStatus()

    monkeypatch.setattr(main, "get_index_job", lambda job_id: FakeJob())

    result = main.client_index_jobs_status(main.IndexJobsStatusRequest(job_ids=["job123"]), Principal(type="app", app_id="imsdom"))

    assert result["jobs"][0]["status"] == "failed"
    assert result["jobs"][0]["error"] == "Work-horse terminated unexpectedly"


def test_index_jobs_status_returns_not_found(monkeypatch):
    import main
    from auth import Principal

    monkeypatch.setattr(main, "get_index_job", lambda job_id: None)

    result = main.client_index_jobs_status(main.IndexJobsStatusRequest(job_ids=["job123"]), Principal(type="app", app_id="imsdom"))

    assert result == {"jobs": [{"job_id": "job123", "status": "not_found"}]}


def test_index_jobs_status_hides_other_app_jobs(monkeypatch):
    import main
    from auth import Principal

    class FakeJob:
        id = "job123"
        created_at = None
        enqueued_at = None
        started_at = None
        ended_at = None
        exc_info = None
        result = {"app_id": "other-app", "file_id": "abc123", "chunk_count": 3}
        meta = {"app_id": "other-app", "file_id": "abc123"}

        def get_status(self, refresh=True):
            return "finished"

    monkeypatch.setattr(main, "get_index_job", lambda job_id: FakeJob())

    result = main.client_index_jobs_status(main.IndexJobsStatusRequest(job_ids=["job123"]), Principal(type="app", app_id="imsdom"))

    assert result == {"jobs": [{"job_id": "job123", "status": "not_found"}]}


def test_index_jobs_status_reports_queue_unavailable(monkeypatch):
    import main
    from auth import Principal
    from indexing.queue import IndexQueueUnavailable

    monkeypatch.setattr(main, "get_index_job", lambda job_id: (_ for _ in ()).throw(IndexQueueUnavailable("index queue is unavailable")))

    with pytest.raises(main.HTTPException) as exc:
        main.client_index_jobs_status(main.IndexJobsStatusRequest(job_ids=["job123"]), Principal(type="app", app_id="imsdom"))

    assert exc.value.status_code == 503
    assert exc.value.detail == "index queue is unavailable"


def test_index_jobs_returns_recent_job_list(monkeypatch):
    import main

    class FakeJob:
        id = "job123"
        created_at = None
        enqueued_at = None
        started_at = None
        ended_at = None
        exc_info = "Traceback\nValueError: parse failed"
        result = {"app_id": "imsdom", "file_id": "abc123", "chunk_count": 3}
        meta = {"app_id": "imsdom", "file_id": "abc123", "filename": "a.pdf", "s3_url": "s3://rag-dev/a.pdf"}

        def get_status(self, refresh=True):
            return "finished"

    monkeypatch.setattr(
        main,
        "list_index_jobs",
        lambda limit=50, app_id=None: {"jobs": [FakeJob()]},
    )

    result = main.index_jobs(limit=50)

    assert result == {
        "jobs": [
            {
                "app_id": "imsdom",
                "file_id": "abc123",
                "job_id": "job123",
                "status": "finished",
                "filename": "a.pdf",
                "s3_url": "s3://rag-dev/a.pdf",
                "chunk_count": 3,
                "error": None,
                "created_at": None,
                "enqueued_at": None,
                "started_at": None,
                "ended_at": None,
            }
        ],
    }


def test_index_jobs_reports_queue_unavailable(monkeypatch):
    import main
    from indexing.queue import IndexQueueUnavailable

    monkeypatch.setattr(main, "list_index_jobs", lambda limit=50, app_id=None: (_ for _ in ()).throw(IndexQueueUnavailable("index queue is unavailable")))

    with pytest.raises(main.HTTPException) as exc:
        main.index_jobs(limit=50)

    assert exc.value.status_code == 503
    assert exc.value.detail == "index queue is unavailable"


def test_monitor_components_include_redis(monkeypatch):
    import main

    monkeypatch.setattr(main, "_redis_ready", lambda: True)

    components = {item["name"]: item for item in main._components()}

    assert components["Redis"]["status"] == "ready"
    assert components["Redis"]["model"] == "redis://redis:6379/0"


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


def test_index_queue_rejects_when_pending_jobs_exceed_limit(monkeypatch):
    from indexing.queue import IndexQueueRejected, _enforce_queue_limits

    class FakeRedis:
        def llen(self, key):
            return 2

        def incr(self, key):
            return 1

        def expire(self, key, seconds):
            pass

    monkeypatch.setenv("INDEX_MAX_PENDING_JOBS", "2")

    with pytest.raises(IndexQueueRejected, match="pending jobs"):
        _enforce_queue_limits(FakeRedis(), "index")


def test_index_queue_rejects_when_rate_limit_exceeds(monkeypatch):
    from indexing.queue import IndexQueueRejected, _enforce_queue_limits

    class FakeRedis:
        def llen(self, key):
            return 0

        def incr(self, key):
            return 31

        def expire(self, key, seconds):
            pass

    monkeypatch.setenv("INDEX_MAX_PENDING_JOBS", "200")
    monkeypatch.setenv("INDEX_RATE_LIMIT_PER_MINUTE", "30")

    with pytest.raises(IndexQueueRejected, match="rate limit"):
        _enforce_queue_limits(FakeRedis(), "index")


def test_generated_file_id_is_uuid_hex_without_prefix_or_dash():
    from indexing.service import create_file_id

    file_id = create_file_id()

    assert re.fullmatch(r"[0-9a-f]{32}", file_id)


def test_generated_job_id_is_uuid_hex_without_prefix_or_dash():
    import main

    job_id = main.create_job_id()

    assert re.fullmatch(r"[0-9a-f]{32}", job_id)


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
    assert any(path == "/api/open/index/jobs/status" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/index" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/index/jobs" and "POST" in methods for path, methods in routes)
    assert any(path == "/api/index/jobs/{job_id}" and "GET" in methods for path, methods in routes)


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


def test_list_storage_files_uses_minio_object_pagination(monkeypatch):
    import main
    from datetime import datetime, timezone

    calls = []

    class Item:
        def __init__(self, object_name, size):
            self.object_name = object_name
            self.size = size
            self.last_modified = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)

    class FakeMinio:
        def bucket_exists(self, bucket):
            calls.append(("bucket_exists", bucket))
            return True

        def list_objects(self, bucket, prefix, recursive, start_after):
            calls.append(("list_objects", bucket, prefix, recursive, start_after))
            return iter([
                Item("uploads/imsdom/a/a.txt", 10),
                Item("uploads/imsdom/b/b.txt", 20),
                Item("uploads/imsdom/c/c.txt", 30),
            ])

    monkeypatch.setattr(main, "_minio_client", lambda: FakeMinio())
    monkeypatch.setenv("S3_BUCKET", "rag-dev")

    page = main._list_storage_files("imsdom", limit=2, cursor="uploads/imsdom/0.txt")

    assert [item["id"] for item in page["files"]] == ["a", "b"]
    assert page["files"][0]["s3_url"] == "s3://rag-dev/uploads/imsdom/a/a.txt"
    assert page["next_cursor"] == "uploads/imsdom/b/b.txt"
    assert page["has_more"] is True
    assert calls == [
        ("bucket_exists", "rag-dev"),
        ("list_objects", "rag-dev", "uploads/imsdom/", True, "uploads/imsdom/0.txt"),
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
