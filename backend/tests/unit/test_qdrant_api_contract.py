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

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(
        main,
        "index_presigned_object",
        lambda application, file_id, presigned_url, s3_url, filename: 3,
    )

    result = main.index_object(
        main.ObjectIndexRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag-dev/docs/a.txt",
            filename="a.txt",
        )
    )

    assert result == {"file_id": "abc123"}


def test_create_index_job_enqueues_async_job(monkeypatch):
    import main

    enqueued = []

    class FakeJob:
        id = "job123"

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "create_job_id", lambda: "job123")
    monkeypatch.setattr(
        main,
        "enqueue_index_job",
        lambda **kwargs: enqueued.append(kwargs) or FakeJob(),
    )

    result = main.create_index_job(
        main.ObjectIndexRequest(
            presigned_url="https://example.com/presigned",
            s3_url="s3://rag-dev/docs/a.txt",
            filename="a.txt",
        )
    )

    assert result == {"job_id": "job123"}
    assert enqueued == [
        {
            "job_id": "job123",
            "file_id": "abc123",
            "presigned_url": "https://example.com/presigned",
            "s3_url": "s3://rag-dev/docs/a.txt",
            "filename": "a.txt",
        }
    ]


def test_create_index_job_returns_429_when_queue_rejects(monkeypatch):
    import main
    from indexing.queue import IndexQueueRejected

    monkeypatch.setattr(main, "_require_ready", lambda: None)
    monkeypatch.setattr(main, "create_file_id", lambda: "abc123")
    monkeypatch.setattr(main, "create_job_id", lambda: "job123")
    monkeypatch.setattr(main, "enqueue_index_job", lambda **kwargs: (_ for _ in ()).throw(IndexQueueRejected("queue full")))

    with pytest.raises(main.HTTPException) as exc:
        main.create_index_job(
            main.ObjectIndexRequest(
                presigned_url="https://example.com/presigned",
                s3_url="s3://rag-dev/docs/a.txt",
                filename="a.txt",
            )
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == "queue full"


def test_index_job_status_returns_rq_job(monkeypatch):
    import main

    class FakeJob:
        id = "job123"
        created_at = None
        enqueued_at = None
        started_at = None
        ended_at = None
        exc_info = None
        result = {"file_id": "abc123", "chunk_count": 3}
        meta = {"file_id": "abc123"}

        def get_status(self, refresh=True):
            return "finished"

    monkeypatch.setattr(main, "get_index_job", lambda job_id: FakeJob())

    result = main.index_job_status("job123")

    assert result == {
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


def test_index_job_status_normalizes_rq_status_enum(monkeypatch):
    import main

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
        meta = {"file_id": "abc123"}

        def get_status(self, refresh=True):
            return FakeStatus()

    monkeypatch.setattr(main, "get_index_job", lambda job_id: FakeJob())

    result = main.index_job_status("job123")

    assert result["status"] == "failed"
    assert result["error"] == "Work-horse terminated unexpectedly"


def test_index_job_status_returns_not_found(monkeypatch):
    import main

    monkeypatch.setattr(main, "get_index_job", lambda job_id: None)

    result = main.index_job_status("job123")

    assert result["file_id"] is None
    assert result["job_id"] == "job123"
    assert result["status"] == "not_found"


def test_index_job_status_reports_queue_unavailable(monkeypatch):
    import main
    from indexing.queue import IndexQueueUnavailable

    monkeypatch.setattr(main, "get_index_job", lambda job_id: (_ for _ in ()).throw(IndexQueueUnavailable("index queue is unavailable")))

    with pytest.raises(main.HTTPException) as exc:
        main.index_job_status("job123")

    assert exc.value.status_code == 503
    assert exc.value.detail == "index queue is unavailable"


def test_index_jobs_returns_paginated_job_list(monkeypatch):
    import main

    class FakeJob:
        id = "job123"
        created_at = None
        enqueued_at = None
        started_at = None
        ended_at = None
        exc_info = "Traceback\nValueError: parse failed"
        result = {"file_id": "abc123", "chunk_count": 3}
        meta = {"file_id": "abc123", "filename": "a.pdf", "s3_url": "s3://rag-dev/a.pdf"}

        def get_status(self, refresh=True):
            return "finished"

    monkeypatch.setattr(
        main,
        "list_index_jobs",
        lambda limit=50, cursor=None: {"jobs": [FakeJob()], "next_cursor": "50", "has_more": True},
    )

    result = main.index_jobs(limit=50)

    assert result == {
        "jobs": [
            {
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
        "next_cursor": "50",
        "has_more": True,
    }


def test_index_jobs_reports_queue_unavailable(monkeypatch):
    import main
    from indexing.queue import IndexQueueUnavailable

    monkeypatch.setattr(main, "list_index_jobs", lambda limit=50, cursor=None: (_ for _ in ()).throw(IndexQueueUnavailable("index queue is unavailable")))

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


def test_recent_search_traces_returns_cursor_page(monkeypatch):
    import main

    main._search_traces.clear()
    main._search_traces.extend(
        [
            {"trace_id": "trace-1"},
            {"trace_id": "trace-2"},
            {"trace_id": "trace-3"},
        ]
    )

    page = main._recent_search_traces(limit=2, cursor="1")

    assert page == {
        "traces": [{"trace_id": "trace-2"}, {"trace_id": "trace-3"}],
        "next_cursor": None,
        "has_more": False,
    }


def test_index_queue_rejects_when_pending_jobs_exceed_limit(monkeypatch):
    from indexing.queue import IndexQueueRejected, _enforce_queue_limits

    class FakeRedis:
        def incr(self, key):
            return 1

        def expire(self, key, seconds):
            pass

    class FakeQueue:
        name = "index"
        count = 2

    monkeypatch.setenv("INDEX_MAX_PENDING_JOBS", "2")

    with pytest.raises(IndexQueueRejected, match="pending jobs"):
        _enforce_queue_limits(FakeRedis(), FakeQueue())


def test_index_queue_rejects_when_rate_limit_exceeds(monkeypatch):
    from indexing.queue import IndexQueueRejected, _enforce_queue_limits

    class FakeRedis:
        def incr(self, key):
            return 31

        def expire(self, key, seconds):
            pass

    class FakeQueue:
        name = "index"
        count = 0

    monkeypatch.setenv("INDEX_MAX_PENDING_JOBS", "200")
    monkeypatch.setenv("INDEX_RATE_LIMIT_PER_MINUTE", "30")

    with pytest.raises(IndexQueueRejected, match="rate limit"):
        _enforce_queue_limits(FakeRedis(), FakeQueue())


def test_index_request_does_not_accept_file_id():
    import main

    schema = main.ObjectIndexRequest.model_json_schema()

    assert "file_id" not in schema["properties"]


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


def test_presign_route_is_top_level_api_endpoint():
    import main

    paths = {route.path for route in main.app.routes}

    assert "/api/presign" in paths


def test_sync_and_async_index_routes_are_separate():
    import main

    routes = [(route.path, route.methods) for route in main.app.routes if hasattr(route, "methods")]

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

    result = main._upload_file_to_storage("docs/a.txt", b"hello", "text/plain")

    assert result == "s3://rag-dev/uploads/abc123/a.txt"
    assert calls == [
        ("bucket_exists", "rag-dev"),
        ("make_bucket", "rag-dev"),
        ("put_object", "rag-dev", "uploads/abc123/a.txt", b"hello", 5, "text/plain"),
    ]
