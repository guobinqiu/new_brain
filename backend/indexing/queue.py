from __future__ import annotations

import os
import time


INDEX_QUEUE_NAME = "index"
DEFAULT_REDIS_URL = "redis://redis:6379/0"


class IndexQueueRejected(Exception):
    pass


class IndexQueueUnavailable(Exception):
    pass


def enqueue_index_job(*, job_id: str, app_id: str, file_id: str, presigned_url: str, s3_url: str, filename: str | None):
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
        job = queue.enqueue(
            "indexing.jobs.index_object_job",
            app_id=app_id,
            file_id=file_id,
            presigned_url=presigned_url,
            s3_url=s3_url,
            filename=filename,
            job_id=job_id,
            meta={"app_id": app_id, "file_id": file_id, "filename": filename, "s3_url": s3_url},
            job_timeout=int(os.getenv("INDEX_JOB_TIMEOUT_SECONDS", "1800")),
            result_ttl=_job_result_ttl(),
            failure_ttl=_job_failure_ttl(),
            retry=Retry(max=int(os.getenv("INDEX_JOB_RETRY_MAX", "2"))),
        )
        _record_app_job(redis, queue.name, app_id, job.id)
        return job
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


def list_index_jobs(*, limit: int = 50, cursor: str | None = None, app_id: str | None = None) -> dict:
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
    if app_id:
        try:
            return _list_app_index_jobs(redis, queue.name, app_id, limit=limit, start=start)
        except RedisError as exc:
            raise IndexQueueUnavailable("index queue is unavailable") from exc
    started_registry = StartedJobRegistry(queue=queue)
    finished_registry = FinishedJobRegistry(queue=queue)
    failed_registry = FailedJobRegistry(queue=queue)
    try:
        job_ids = _job_id_page(
            (
                (queue.count, lambda offset, length: queue.get_job_ids(offset=offset, length=length)),
                (started_registry.count, lambda offset, length: started_registry.get_job_ids(start=offset, end=offset + length - 1, desc=True)),
                (finished_registry.count, lambda offset, length: finished_registry.get_job_ids(start=offset, end=offset + length - 1, desc=True)),
                (failed_registry.count, lambda offset, length: failed_registry.get_job_ids(start=offset, end=offset + length - 1, desc=True)),
            ),
            start=start,
            limit=limit + 1,
        )
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc
    jobs, _ = _fetch_jobs(Job, job_ids[:limit], redis)
    next_index = start + limit
    return {
        "jobs": jobs,
        "next_cursor": str(next_index) if len(job_ids) > limit else None,
        "has_more": len(job_ids) > limit,
    }


def _job_id_page(groups, *, start: int, limit: int) -> list[str]:
    ids = []
    offset = start
    for count, loader in groups:
        if offset >= count:
            offset -= count
            continue
        remaining = limit - len(ids)
        if remaining <= 0:
            break
        ids.extend(loader(offset, remaining))
        offset = 0
    return _unique_job_ids(ids)


def _unique_job_ids(group: list[str]) -> list[str]:
    seen = set()
    result = []
    for job_id in group:
        if job_id in seen:
            continue
        seen.add(job_id)
        result.append(job_id)
    return result


def _list_app_index_jobs(redis, queue_name: str, app_id: str, *, limit: int, start: int) -> dict:
    from rq.job import Job

    key = _app_jobs_key(queue_name, app_id)
    _prune_app_job_index(redis, key)
    ids = redis.zrevrange(key, start, start + limit)
    job_ids = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in ids]
    jobs, stale_job_ids = _fetch_jobs(Job, job_ids[:limit], redis)
    if stale_job_ids:
        redis.zrem(key, *stale_job_ids)
    next_index = start + limit
    return {
        "jobs": jobs,
        "next_cursor": str(next_index) if len(job_ids) > limit else None,
        "has_more": len(job_ids) > limit,
    }


def _fetch_jobs(job_class, job_ids: list[str], redis) -> tuple[list, list[str]]:
    jobs = []
    stale_job_ids = []
    for job_id, job in zip(job_ids, job_class.fetch_many(job_ids, connection=redis), strict=False):
        if job is None:
            stale_job_ids.append(job_id)
            continue
        jobs.append(job)
    return jobs, stale_job_ids


def _record_app_job(redis, queue_name: str, app_id: str, job_id: str) -> None:
    key = _app_jobs_key(queue_name, app_id)
    redis.zadd(key, {job_id: time.time()})
    _prune_app_job_index(redis, key)


def _prune_app_job_index(redis, key: str) -> None:
    ttl = max(_job_result_ttl(), _job_failure_ttl())
    if ttl > 0:
        redis.zremrangebyscore(key, 0, time.time() - ttl)


def _app_jobs_key(queue_name: str, app_id: str) -> str:
    return f"rag:index:jobs:{queue_name}:app:{app_id}"


def _redis_url() -> str:
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


def _job_result_ttl() -> int:
    return int(os.getenv("INDEX_JOB_RESULT_TTL_SECONDS", "-1"))


def _job_failure_ttl() -> int:
    return int(os.getenv("INDEX_JOB_FAILURE_TTL_SECONDS", "-1"))


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
