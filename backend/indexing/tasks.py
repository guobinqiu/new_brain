from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone

from celery.signals import worker_init, worker_process_init
from bootstrap import Application
from indexing.celery_app import celery_app
from indexing.queue import update_index_job_metadata
from indexing.service import index_presigned_object
from logging_config import configure_logging


logger = logging.getLogger("rag.index_worker")
_application: Application | None = None
_application_lock = threading.Lock()


@celery_app.task(name="indexing.tasks.index_object_task", bind=True)
def index_object_task(self, *, app_id: str, file_id: str, presigned_url: str, s3_url: str, filename: str | None = None) -> dict:
    update_index_job_metadata(self.request.id, started_at=datetime.now(timezone.utc).isoformat())
    try:
        return _index_object(app_id=app_id, file_id=file_id, presigned_url=presigned_url, s3_url=s3_url, filename=filename)
    except ValueError:
        raise
    except Exception as exc:
        max_retries = int(os.getenv("INDEX_JOB_RETRY_MAX", "2"))
        if self.request.retries >= max_retries:
            raise
        raise self.retry(exc=exc)


def _index_object(*, app_id: str, file_id: str, presigned_url: str, s3_url: str, filename: str | None = None) -> dict:
    application = _worker_application()
    if not application.store.app_collection_exists(app_id):
        raise ValueError("app database is not initialized")
    with application.store.app_context(app_id):
        count = index_presigned_object(application, file_id, presigned_url, s3_url, filename)
    logger.info(
        "Object indexed",
        extra={
            "event": "object_indexed",
            "app_id": app_id,
            "file_id": file_id,
            "document_filename": filename,
            "s3_url": s3_url,
            "chunk_count": count,
        },
    )
    return {"app_id": app_id, "file_id": file_id, "chunk_count": count}


def _worker_application() -> Application:
    application = _ensure_application()
    if not application.models_loaded:
        application.load_models()
    if not application.ready:
        application.init_connections()
    return application


def _ensure_application() -> Application:
    global _application
    with _application_lock:
        if _application is None:
            _application = Application()
            configure_logging(_application.config.logging)
        return _application


@worker_init.connect
def preload_parent_application(**_kwargs) -> None:
    _ensure_application()


@worker_process_init.connect
def initialize_child_application(**_kwargs) -> None:
    application = _ensure_application()
    if not application.models_loaded:
        application.load_models()
    if not application.ready:
        application.init_connections()
