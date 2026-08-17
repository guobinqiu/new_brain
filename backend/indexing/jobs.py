from __future__ import annotations

import logging
import threading

from bootstrap import Application
from indexing.service import index_presigned_object
from logging_config import configure_logging


logger = logging.getLogger("rag.index_worker")
_application: Application | None = None
_application_lock = threading.Lock()


def index_object_job(*, file_id: str, presigned_url: str, s3_url: str, filename: str | None = None) -> dict:
    application = _worker_application()
    count = index_presigned_object(application, file_id, presigned_url, s3_url, filename)
    logger.info(
        "Object indexed",
        extra={
            "event": "object_indexed",
            "file_id": file_id,
            "document_filename": filename,
            "s3_url": s3_url,
            "chunk_count": count,
        },
    )
    return {"file_id": file_id, "chunk_count": count}


def _worker_application() -> Application:
    global _application
    with _application_lock:
        if _application is None or not _application.ready:
            _application = Application()
            configure_logging(_application.config.logging)
            _application.start()
        return _application
