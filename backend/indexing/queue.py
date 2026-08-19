"""In-process index job enqueue (Architecture C, Step 1).

Puts a job dict onto the queue.Queue owned by the registered
``InlineIndexConsumer``. No broker, no task records, no ``job_id``.
"""
from __future__ import annotations

import queue


class IndexQueueRejected(Exception):
    """Raised when the in-process index queue cannot accept a job (full)."""


def enqueue_index_job(*, app_id, file_id, presigned_url, s3_url, filename) -> dict:
    """Enqueue an index job onto the live consumer's queue.

    Returns ``{"file_id": file_id}``. Raises ``IndexQueueRejected`` when the
    queue is full (mapped to 429 by the API layer).
    """
    # Runtime import avoids a circular import with indexing.consumer.
    from indexing.consumer import index_queue

    job = {
        "app_id": app_id,
        "file_id": file_id,
        "presigned_url": presigned_url,
        "s3_url": s3_url,
        "filename": filename,
        "retry_count": 0,
    }
    try:
        index_queue().put_nowait(job)
    except queue.Full as exc:
        raise IndexQueueRejected("index queue full") from exc
    return {"file_id": file_id}
