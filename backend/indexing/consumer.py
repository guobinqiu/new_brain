"""In-process queue.Queue index consumer (Architecture C).

Lives in the backend process; owns a single queue.Queue and a single-worker
ThreadPoolExecutor. ``_index_object`` was migrated from the former
``indexing/tasks.py`` celery wrapper, which has been removed together with
``indexing/celery_app.py`` and ``indexing/repository.py``.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import os
import queue as _queue
from concurrent.futures import ThreadPoolExecutor

from indexing.service import index_presigned_object

logger = logging.getLogger("rag.index_consumer")

# Module-level singleton set by ``InlineIndexConsumer.start``; ``index_queue()``
# reads it so ``enqueue_index_job`` (in queue.py) can reach the live queue.
_consumer = None


def _max_pending_jobs() -> int:
    # max(1, ...) guards against 0 (which would make the queue unbounded and
    # defeat backpressure) and negative values (which would crash Queue()).
    return max(1, int(os.getenv("INDEX_MAX_PENDING_JOBS", "10")))


def _job_timeout_seconds() -> int:
    return int(os.getenv("INDEX_JOB_TIMEOUT_SECONDS", "1800"))


def _job_retry_max() -> int:
    return int(os.getenv("INDEX_JOB_RETRY_MAX", "2"))


def index_queue() -> _queue.Queue:
    """Return the queue.Queue owned by the registered consumer."""
    if _consumer is None:
        raise RuntimeError("no inline index consumer registered")
    return _consumer.queue


def _register_consumer(consumer) -> None:
    """Module-level singleton setter; ``None`` clears it (test isolation)."""
    global _consumer
    _consumer = consumer


class InlineIndexConsumer:
    """Single-worker inline index consumer.

    ``queue``/``timeout``/``retry_max`` are optional kwargs for testability;
    when omitted they read ``INDEX_MAX_PENDING_JOBS`` / ``INDEX_JOB_TIMEOUT_SECONDS``
    / ``INDEX_JOB_RETRY_MAX`` (defaults 10 / 1800 / 2).
    """

    def __init__(self, application, *, queue=None, timeout=None, retry_max=None):
        self.application = application
        self.queue = queue if queue is not None else _queue.Queue(maxsize=_max_pending_jobs())
        self.stop_event = asyncio.Event()
        self.task = None
        self.timeout = timeout if timeout is not None else _job_timeout_seconds()
        self.retry_max = retry_max if retry_max is not None else _job_retry_max()
        # max_workers=1 serializes indexing so a timed-out orphan thread can
        # never overlap the next job's GPU work (design §4.3).
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="index-worker")

    async def start(self) -> None:
        _register_consumer(self)
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.stop_event.set()
        if self.task is not None:
            await asyncio.gather(self.task, return_exceptions=True)
        self.executor.shutdown(wait=False)
        # Symmetric with start()'s registration: clear the singleton so
        # enqueue_index_job raises RuntimeError instead of silently putting
        # jobs onto a dead queue after shutdown.
        _register_consumer(None)

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self.stop_event.is_set():
            try:
                job = await loop.run_in_executor(
                    None, lambda: self.queue.get(timeout=1.0)
                )
            except _queue.Empty:
                continue
            await self._run_job(job)

    async def _run_job(self, job) -> None:
        app_id = job["app_id"]
        file_id = job["file_id"]
        filename = job.get("filename")
        retry_count = job.get("retry_count", 0)
        loop = asyncio.get_running_loop()
        # copy_context() gives this executor run an isolated ContextVar scope;
        # _index_object also enters app_context itself, so this is defensive.
        ctx = contextvars.copy_context()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    self.executor,
                    ctx.run,
                    functools.partial(_index_object, self.application, job),
                ),
                timeout=self.timeout,
            )
            return
        except ValueError as exc:
            # Non-retryable (app db not initialized, unsupported file type): drop.
            logger.warning(
                "Index failed (non-retryable)",
                exc_info=True,
                extra={
                    "event": "index_failed",
                    "app_id": app_id,
                    "file_id": file_id,
                    "error": str(exc),
                },
            )
            return
        except asyncio.TimeoutError:
            reason = f"index timeout after {self.timeout}s"
        except Exception as exc:  # noqa: BLE001 - retryable branch
            reason = f"index failed: {exc!r}"

        # Retryable branch: timeout or generic exception.
        if retry_count < self.retry_max:
            job["retry_count"] = retry_count + 1
            try:
                self.queue.put_nowait(job)
            except _queue.Full:
                logger.error(
                    "Re-enqueue failed (queue full), dropping job",
                    extra={
                        "event": "index_reenqueue_dropped",
                        "app_id": app_id,
                        "file_id": file_id,
                    },
                )
        else:
            logger.error(
                "Index job exhausted retries, giving up",
                extra={
                    "event": "index_failed_final",
                    "app_id": app_id,
                    "file_id": file_id,
                    # "filename" collides with LogRecord.filename (reserved);
                    # use document_filename like the success-path log.
                    "document_filename": filename,
                    "retry_count": retry_count,
                    "error": reason,
                },
            )


def _index_object(application, job) -> dict:
    """Migrated from indexing/tasks.py L47-64; takes the job dict + application.

    Raises ``ValueError`` when the app collection is missing (non-retryable).
    """
    app_id = job["app_id"]
    file_id = job["file_id"]
    presigned_url = job["presigned_url"]
    s3_url = job["s3_url"]
    filename = job.get("filename")
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
