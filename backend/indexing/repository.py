from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any


INDEX_QUEUE_NAME = "index"
DEFAULT_REDIS_URL = "redis://redis:6379/0"
_redis_client = None
_redis_client_url = None
_redis_lock = threading.Lock()


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
        ttl = max(job_result_ttl(), job_failure_ttl())
        if ttl > 0:
            self.redis.expire(_job_metadata_key(self.queue_name, job_id), ttl)

    def list_jobs(self, *, limit: int, app_id: str | None = None) -> list[dict]:
        key = _app_jobs_key(self.queue_name, app_id) if app_id else _all_jobs_key(self.queue_name)
        self._prune_job_index(key)
        ids = self.redis.zrevrange(key, 0, max(limit - 1, 0))
        job_ids = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in ids]
        return [{"job_id": job_id, "metadata": self.get_metadata(job_id)} for job_id in job_ids]

    def _record_app_job(self, app_id: str, job_id: str) -> None:
        score = time.time()
        app_key = _app_jobs_key(self.queue_name, app_id)
        all_key = _all_jobs_key(self.queue_name)
        self.redis.zadd(app_key, {job_id: score})
        self.redis.zadd(all_key, {job_id: score})
        self._prune_job_index(app_key)
        self._prune_job_index(all_key)

    def _prune_job_index(self, key: str) -> None:
        ttl = max(job_result_ttl(), job_failure_ttl())
        if ttl > 0:
            self.redis.zremrangebyscore(key, 0, time.time() - ttl)

    def rollback_job(self, job_id: str, *, app_id: str) -> None:
        """send_task 失败时清理已登记的 job，避免产生永远不会执行的僵尸任务。"""
        self.redis.delete(_job_metadata_key(self.queue_name, job_id))
        self.redis.zrem(_app_jobs_key(self.queue_name, app_id), job_id)
        self.redis.zrem(_all_jobs_key(self.queue_name), job_id)


def update_index_job_metadata(job_id: str, **values) -> None:
    IndexJobRepository(redis_client(), os.getenv("INDEX_QUEUE_NAME", INDEX_QUEUE_NAME)).update_metadata(job_id, **values)


def publish_index_job_event(app_id: str, job_id: str, status: str, filename: str | None = None) -> None:
    """发布索引任务状态事件到 Redis Pub/Sub，供 API 进程 SSE 端点消费。"""
    from redis.exceptions import RedisError
    payload = json.dumps({"app_id": app_id, "job_id": job_id, "status": status, "filename": filename}, ensure_ascii=False)
    try:
        redis_client().publish(_index_events_channel(app_id), payload)
    except RedisError:
        pass


def _index_events_channel(app_id: str) -> str:
    return f"rag:index:events:{app_id}"


def redis_url() -> str:
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


def redis_client():
    global _redis_client, _redis_client_url
    url = redis_url()
    with _redis_lock:
        if _redis_client is None or _redis_client_url != url:
            from redis import Redis

            _redis_client = Redis.from_url(url)
            _redis_client_url = url
        return _redis_client


def job_result_ttl() -> int:
    return int(os.getenv("INDEX_JOB_RESULT_TTL_SECONDS", "-1"))


def job_failure_ttl() -> int:
    return int(os.getenv("INDEX_JOB_FAILURE_TTL_SECONDS", "-1"))


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
