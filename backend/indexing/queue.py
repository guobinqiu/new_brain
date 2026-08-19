from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any


INDEX_QUEUE_NAME = "index"
DEFAULT_REDIS_URL = "redis://redis:6379/0"


class IndexQueueRejected(Exception):
    pass


class IndexQueueUnavailable(Exception):
    pass


def enqueue_index_job(*, job_id: str, app_id: str, file_id: str, presigned_url: str, s3_url: str, filename: str | None):
    from redis import Redis
    from redis.exceptions import RedisError

    redis = Redis.from_url(_redis_url())
    queue_name = os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME)
    repository = IndexJobRepository(redis, queue_name)
    try:
        _enforce_queue_limits(redis, queue_name)
        repository.record_job(job_id, app_id=app_id, file_id=file_id, filename=filename, s3_url=s3_url)
        return _celery_app().send_task(
            "indexing.tasks.index_object_task",
            kwargs={
                "app_id": app_id,
                "file_id": file_id,
                "presigned_url": presigned_url,
                "s3_url": s3_url,
                "filename": filename,
            },
            task_id=job_id,
            queue=queue_name,
            retry=True,
        )
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc


def get_index_job(job_id: str):
    from redis import Redis
    from redis.exceptions import RedisError

    redis = Redis.from_url(_redis_url())
    repository = IndexJobRepository(redis, os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME))
    try:
        metadata = repository.get_metadata(job_id)
        result = _celery_app().AsyncResult(job_id)
        if result.status == "PENDING" and not metadata:
            return None
        return CeleryJobAdapter(result, metadata)
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc


def list_index_jobs(*, limit: int = 50, cursor: str | None = None, app_id: str | None = None) -> dict:
    from redis import Redis
    from redis.exceptions import RedisError

    if limit <= 0:
        raise ValueError("limit must be greater than 0")
    limit = min(limit, 200)
    start = int(cursor) if cursor else 0
    redis = Redis.from_url(_redis_url())
    queue_name = os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME)
    repository = IndexJobRepository(redis, queue_name)
    try:
        page = repository.list_jobs(limit=limit, start=start, app_id=app_id)
        celery = _celery_app()
        jobs = []
        for item in page["jobs"]:
            result = celery.AsyncResult(item["job_id"])
            if result.status == "PENDING" and not item["metadata"]:
                continue
            jobs.append(CeleryJobAdapter(result, item["metadata"]))
        return {**page, "jobs": jobs}
    except RedisError as exc:
        raise IndexQueueUnavailable("index queue is unavailable") from exc


class IndexJobRepository:
    def __init__(self, redis, queue_name: str):
        self.redis = redis
        self.queue_name = queue_name

    def record_job(self, job_id: str, *, app_id: str, file_id: str, filename: str | None, s3_url: str) -> None:
        self.update_metadata(
            job_id,
            app_id=app_id,
            file_id=file_id,
            filename=filename or "",
            s3_url=s3_url,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._record_app_job(app_id, job_id)

    def get_metadata(self, job_id: str) -> dict[str, Any]:
        return _decode_hash(self.redis.hgetall(_job_metadata_key(self.queue_name, job_id)))

    def update_metadata(self, job_id: str, **values) -> None:
        self.redis.hset(_job_metadata_key(self.queue_name, job_id), mapping=values)
        ttl = max(_job_result_ttl(), _job_failure_ttl())
        if ttl > 0:
            self.redis.expire(_job_metadata_key(self.queue_name, job_id), ttl)

    def list_jobs(self, *, limit: int, start: int, app_id: str | None = None) -> dict:
        key = _app_jobs_key(self.queue_name, app_id) if app_id else _all_jobs_key(self.queue_name)
        self._prune_job_index(key)
        ids = self.redis.zrevrange(key, start, start + limit)
        job_ids = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in ids]
        next_index = start + limit
        return {
            "jobs": [{"job_id": job_id, "metadata": self.get_metadata(job_id)} for job_id in job_ids[:limit]],
            "next_cursor": str(next_index) if len(job_ids) > limit else None,
            "has_more": len(job_ids) > limit,
        }

    def _record_app_job(self, app_id: str, job_id: str) -> None:
        score = time.time()
        app_key = _app_jobs_key(self.queue_name, app_id)
        all_key = _all_jobs_key(self.queue_name)
        self.redis.zadd(app_key, {job_id: score})
        self.redis.zadd(all_key, {job_id: score})
        self._prune_job_index(app_key)
        self._prune_job_index(all_key)

    def _prune_job_index(self, key: str) -> None:
        ttl = max(_job_result_ttl(), _job_failure_ttl())
        if ttl > 0:
            self.redis.zremrangebyscore(key, 0, time.time() - ttl)


def update_index_job_metadata(job_id: str, **values) -> None:
    from redis import Redis

    redis = Redis.from_url(_redis_url())
    IndexJobRepository(redis, os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME)).update_metadata(job_id, **values)


def _app_jobs_key(queue_name: str, app_id: str) -> str:
    return f"rag:index:jobs:{queue_name}:app:{app_id}"


def _all_jobs_key(queue_name: str) -> str:
    return f"rag:index:jobs:{queue_name}:all"


def _job_metadata_key(queue_name: str, job_id: str) -> str:
    return f"rag:index:job:{queue_name}:{job_id}"


def _decode_hash(values: dict) -> dict[str, Any]:
    decoded = {}
    for key, value in values.items():
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        decoded[str(key)] = value
    return decoded


def _redis_url() -> str:
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


def _job_result_ttl() -> int:
    return int(os.getenv("INDEX_JOB_RESULT_TTL_SECONDS", "-1"))


def _job_failure_ttl() -> int:
    return int(os.getenv("INDEX_JOB_FAILURE_TTL_SECONDS", "-1"))


def _enforce_queue_limits(redis, queue_name) -> None:
    max_pending = int(os.getenv("INDEX_MAX_PENDING_JOBS", "200"))
    if redis.llen(queue_name) >= max_pending:
        raise IndexQueueRejected(f"index queue pending jobs exceeds max limit: {max_pending}")

    per_minute = int(os.getenv("INDEX_RATE_LIMIT_PER_MINUTE", "30"))
    minute = int(time.time() // 60)
    key = f"rag:index:rate:{queue_name}:{minute}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, 120)
    if count > per_minute:
        raise IndexQueueRejected(f"index rate limit exceeds max limit: {per_minute}/minute")


class CeleryJobAdapter:
    def __init__(self, result, metadata: dict[str, Any]):
        self._result = result
        self.id = result.id
        self.meta = metadata
        self.result = result.result if isinstance(result.result, dict) else None
        self.exc_info = getattr(result, "traceback", None)
        self.created_at = _parse_datetime(metadata.get("created_at"))
        self.enqueued_at = self.created_at
        self.started_at = _parse_datetime(metadata.get("started_at"))
        self.ended_at = getattr(result, "date_done", None)

    def get_status(self, refresh: bool = True) -> str:
        return _celery_status(getattr(self._result, "status", "PENDING"))


def _celery_status(status: str) -> str:
    return {
        "PENDING": "queued",
        "RECEIVED": "queued",
        "STARTED": "started",
        "RETRY": "queued",
        "SUCCESS": "finished",
        "FAILURE": "failed",
        "REVOKED": "failed",
    }.get(str(status).upper(), str(status).lower())


def _parse_datetime(value):
    if not value:
        return None
    if not isinstance(value, str):
        return value
    return datetime.fromisoformat(value)


def _celery_app():
    from indexing.celery_app import celery_app

    return celery_app
