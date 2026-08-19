from __future__ import annotations

import os


def _result_expires() -> int | None:
    values = [
        int(os.getenv("INDEX_JOB_RESULT_TTL_SECONDS", "-1")),
        int(os.getenv("INDEX_JOB_FAILURE_TTL_SECONDS", "-1")),
    ]
    ttl = max(values)
    return ttl if ttl > 0 else None


def create_celery_app():
    from celery import Celery

    broker_url = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://redis:6379/0")
    result_backend = os.getenv("CELERY_RESULT_BACKEND") or os.getenv("REDIS_URL", "redis://redis:6379/0")
    app = Celery("rag_indexing", broker=broker_url, backend=result_backend, include=["indexing.tasks"])
    app.conf.update(
        task_track_started=True,
        result_extended=True,
        result_expires=_result_expires(),
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_default_queue=os.getenv("INDEX_QUEUE_NAME", "index"),
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
    )
    return app


celery_app = create_celery_app()
