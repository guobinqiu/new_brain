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

        def zrem(self, key, *job_ids):
            raise AssertionError("fresh page should not remove jobs")

    class FakeQueue:
        def __init__(self, name, connection):
            self.name = name

    class FakeJob:
        def __init__(self, job_id):
            self.id = job_id

        @staticmethod
        def fetch_many(job_ids, connection):
            fetched_batches.append(list(job_ids))
            return [FakeJob(job_id) for job_id in job_ids]

    monkeypatch.setattr("redis.Redis.from_url", lambda url: FakeRedis())
    monkeypatch.setattr("rq.Queue", FakeQueue)
    monkeypatch.setattr("rq.job.Job.fetch_many", FakeJob.fetch_many)

    page = queue.list_index_jobs(limit=2, cursor="1", app_id="imsdom")

    assert [job.id for job in page["jobs"]] == ["job-1", "job-2"]
    assert fetched_batches == [["job-1", "job-2"]]
    assert page["next_cursor"] == "3"
    assert page["has_more"] is True
