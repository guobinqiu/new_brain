from __future__ import annotations

import os
import time


INDEX_QUEUE_NAME = "index"
DEFAULT_REDIS_URL = "redis://redis:6379/0"


class IndexQueueRejected(Exception):
    pass


class IndexQueueUnavailable(Exception):
    pass


def enqueue_index_job(*, job_id: str, file_id: str, presigned_url: str, s3_url: str, filename: str | None):
    from redis import Redis
    from redis.exceptions import RedisError
    from rq import Queue, Retry

    redis = Redis.from_url(_redis_url())
    queue = Queue(
        os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME),
        connection=redis,
    )
    try:
        _enforce_queue_limits(redis, queue)
        return queue.enqueue(
            "indexing.jobs.index_object_job",
            file_id=file_id,
            presigned_url=presigned_url,
            s3_url=s3_url,
            filename=filename,
            job_id=job_id,
            meta={"file_id": file_id, "filename": filename, "s3_url": s3_url},
            job_timeout=int(os.getenv("INDEX_JOB_TIMEOUT_SECONDS", "1800")),
            retry=Retry(max=int(os.getenv("INDEX_JOB_RETRY_MAX", "2"))),
        )
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc


def get_index_job(job_id: str):
    from redis import Redis
    from redis.exceptions import RedisError
    from rq.job import Job
    from rq.exceptions import NoSuchJobError

    redis = Redis.from_url(_redis_url())
    try:
        return Job.fetch(job_id, connection=redis)
    except NoSuchJobError:
        return None
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc


def list_index_jobs(*, limit: int = 50, cursor: str | None = None) -> dict:
    from redis import Redis
    from redis.exceptions import RedisError
    from rq import Queue
    from rq.job import Job
    from rq.registry import FailedJobRegistry, FinishedJobRegistry, StartedJobRegistry

    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    start = int(cursor) if cursor else 0
    redis = Redis.from_url(_redis_url())
    queue = Queue(os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME), connection=redis)
    try:
        job_ids = _unique_job_ids(
            queue.get_job_ids(),
            StartedJobRegistry(queue=queue).get_job_ids(desc=True),
            FinishedJobRegistry(queue=queue).get_job_ids(desc=True),
            FailedJobRegistry(queue=queue).get_job_ids(desc=True),
        )
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc
    page_ids = job_ids[start:start + limit]
    jobs = []
    for job_id in page_ids:
        try:
            jobs.append(Job.fetch(job_id, connection=redis))
        except Exception:
            continue
    next_index = start + limit
    return {
        "jobs": jobs,
        "next_cursor": str(next_index) if next_index < len(job_ids) else None,
        "has_more": next_index < len(job_ids),
    }


def _unique_job_ids(*groups: list[str]) -> list[str]:
    seen = set()
    result = []
    for group in groups:
        for job_id in group:
            if job_id in seen:
                continue
            seen.add(job_id)
            result.append(job_id)
    return result


def _redis_url() -> str:
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


def _enforce_queue_limits(redis, queue) -> None:
    max_pending = int(os.getenv("INDEX_MAX_PENDING_JOBS", "200"))
    if queue.count >= max_pending:
        raise IndexQueueRejected(f"index queue pending jobs exceeds max limit: {max_pending}")

    per_minute = int(os.getenv("INDEX_RATE_LIMIT_PER_MINUTE", "30"))
    minute = int(time.time() // 60)
    key = f"rag:index:rate:{queue.name}:{minute}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, 120)
    if count > per_minute:
        raise IndexQueueRejected(f"index rate limit exceeds max limit: {per_minute}/minute")
