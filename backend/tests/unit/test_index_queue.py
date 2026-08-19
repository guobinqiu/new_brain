import pytest


pytestmark = pytest.mark.unit


def test_default_redis_url_targets_redis_service_name(monkeypatch):
    from indexing import queue

    monkeypatch.delenv("REDIS_URL", raising=False)

    assert queue._redis_url() == "redis://redis:6379/0"


def test_index_jobs_are_retained_until_cleanup(monkeypatch):
    from indexing import queue

    monkeypatch.delenv("INDEX_JOB_RESULT_TTL_SECONDS", raising=False)
    monkeypatch.delenv("INDEX_JOB_FAILURE_TTL_SECONDS", raising=False)

    assert queue._job_result_ttl() == -1
    assert queue._job_failure_ttl() == -1


def test_list_index_jobs_fetches_only_current_app_page(monkeypatch):
    from indexing import queue

    monkeypatch.delenv("INDEX_JOB_RESULT_TTL_SECONDS", raising=False)
    monkeypatch.delenv("INDEX_JOB_FAILURE_TTL_SECONDS", raising=False)

    fetched_batches = []

    class FakeRedis:
        def zrevrange(self, key, start, end):
            assert key == "rag:index:jobs:index:app:imsdom"
            assert start == 1
            assert end == 3
            return ["job-1", "job-2", "job-3"]

        def hgetall(self, key):
            fetched_batches.append(key)
            return {"app_id": "imsdom", "file_id": key.rsplit(":", 1)[-1]}

    class FakeCeleryApp:
        def AsyncResult(self, job_id):
            class Result:
                id = job_id
                status = "PENDING"
                result = None
                traceback = None
                date_done = None

            return Result()

    monkeypatch.setattr("redis.Redis.from_url", lambda url: FakeRedis())
    monkeypatch.setattr(queue, "_celery_app", lambda: FakeCeleryApp())

    page = queue.list_index_jobs(limit=2, cursor="1", app_id="imsdom")

    assert [job.id for job in page["jobs"]] == ["job-1", "job-2"]
    assert fetched_batches == ["rag:index:job:index:job-1", "rag:index:job:index:job-2"]
    assert page["next_cursor"] == "3"
    assert page["has_more"] is True


def test_index_job_repository_records_and_pages_jobs(monkeypatch):
    from indexing import queue

    monkeypatch.delenv("INDEX_JOB_RESULT_TTL_SECONDS", raising=False)
    monkeypatch.delenv("INDEX_JOB_FAILURE_TTL_SECONDS", raising=False)

    calls = []

    class FakeRedis:
        def hset(self, key, mapping):
            calls.append(("hset", key, mapping))

        def zadd(self, key, mapping):
            calls.append(("zadd", key, mapping))

        def zremrangebyscore(self, key, minimum, maximum):
            calls.append(("zremrangebyscore", key, minimum, maximum))

        def zrevrange(self, key, start, end):
            assert key == "rag:index:jobs:index:app:imsdom"
            assert start == 0
            assert end == 2
            return ["job-1", "job-2", "job-3"]

        def hgetall(self, key):
            return {"app_id": "imsdom", "file_id": key.rsplit(":", 1)[-1]}

    repository = queue.IndexJobRepository(FakeRedis(), "index")
    repository.record_job("job-1", app_id="imsdom", file_id="file-1", filename="a.pdf", s3_url="s3://bucket/a.pdf")
    page = repository.list_jobs(limit=2, start=0, app_id="imsdom")

    assert any(call[0] == "hset" and call[1] == "rag:index:job:index:job-1" for call in calls)
    assert any(call[0] == "zadd" and call[1] == "rag:index:jobs:index:app:imsdom" for call in calls)
    assert any(call[0] == "zadd" and call[1] == "rag:index:jobs:index:all" for call in calls)
    assert [job["job_id"] for job in page["jobs"]] == ["job-1", "job-2"]
    assert page["next_cursor"] == "2"
    assert page["has_more"] is True


def test_enqueue_index_job_sends_celery_task_and_records_metadata(monkeypatch):
    from indexing import queue

    calls = []

    class FakeCeleryApp:
        def send_task(self, name, kwargs, task_id, queue, retry):
            calls.append((name, kwargs, task_id, queue, retry))

            class Result:
                id = task_id

            return Result()

    class FakeRedis:
        def hset(self, key, mapping):
            calls.append(("hset", key, mapping))

        def zadd(self, key, mapping):
            calls.append(("zadd", key, mapping))

        def zremrangebyscore(self, key, minimum, maximum):
            calls.append(("zremrangebyscore", key, minimum, maximum))

        def llen(self, key):
            return 0

        def incr(self, key):
            return 1

        def expire(self, key, seconds):
            calls.append(("expire", key, seconds))

    monkeypatch.setattr(queue, "_celery_app", lambda: FakeCeleryApp())
    monkeypatch.setattr("redis.Redis.from_url", lambda url: FakeRedis())

    result = queue.enqueue_index_job(
        job_id="job-1",
        app_id="imsdom",
        file_id="file-1",
        presigned_url="https://example.com/presigned",
        s3_url="s3://bucket/docs/a.pdf",
        filename="a.pdf",
    )

    assert result.id == "job-1"
    assert any(call[0] == "hset" and call[1] == "rag:index:job:index:job-1" and call[2]["app_id"] == "imsdom" for call in calls)
    assert any(call[0] == "zadd" and call[1] == "rag:index:jobs:index:app:imsdom" for call in calls)
    assert calls[-1] == (
        "indexing.tasks.index_object_task",
        {
            "app_id": "imsdom",
            "file_id": "file-1",
            "presigned_url": "https://example.com/presigned",
            "s3_url": "s3://bucket/docs/a.pdf",
            "filename": "a.pdf",
        },
        "job-1",
        "index",
        True,
    )


def test_get_index_job_returns_celery_result_with_saved_metadata(monkeypatch):
    import datetime

    from indexing import queue

    class FakeResult:
        id = "job-1"
        status = "SUCCESS"
        result = {"app_id": "imsdom", "file_id": "file-1", "chunk_count": 3}
        traceback = None
        date_done = datetime.datetime(2026, 8, 17, 9, 0, 18)

    class FakeCeleryApp:
        def AsyncResult(self, job_id):
            assert job_id == "job-1"
            return FakeResult()

    class FakeRedis:
        def hgetall(self, key):
            assert key == "rag:index:job:index:job-1"
            return {
                b"app_id": b"imsdom",
                b"file_id": b"file-1",
                b"filename": b"a.pdf",
                b"s3_url": b"s3://bucket/docs/a.pdf",
                b"created_at": b"2026-08-17T09:00:00+00:00",
            }

    monkeypatch.setattr(queue, "_celery_app", lambda: FakeCeleryApp())
    monkeypatch.setattr("redis.Redis.from_url", lambda url: FakeRedis())

    job = queue.get_index_job("job-1")

    assert job.id == "job-1"
    assert job.get_status() == "finished"
    assert job.meta["filename"] == "a.pdf"
    assert job.result["chunk_count"] == 3
    assert job.ended_at == datetime.datetime(2026, 8, 17, 9, 0, 18)
