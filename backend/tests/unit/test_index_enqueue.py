"""RED tests for indexing.queue.enqueue_index_job (Architecture C, Step 1).

Contract (docs/architecture-c-inline-index-worker.md §4.5):

    enqueue_index_job(*, app_id, file_id, presigned_url, s3_url, filename) -> {"file_id": file_id}

- puts a job dict ``{app_id, file_id, presigned_url, s3_url, filename, retry_count: 0}``
  into the process-wide ``queue.Queue`` registered by ``InlineIndexConsumer``.
- queue full -> ``IndexQueueRejected`` (mapped to 429 by the API layer).
- no ``job_id`` (returned shape is ``{file_id}`` only).
- does NOT import redis / indexing.repository (in-process queue, no broker).

These tests run against the *new* queue.py. Until consumer.py exists and queue.py
is rewritten they fail to collect (ModuleNotFoundError) — that is the RED signal.
"""
from __future__ import annotations

import asyncio
import inspect
import queue

import pytest

import indexing.consumer as consumer_mod
import indexing.queue as queue_mod
from indexing.queue import IndexQueueRejected, enqueue_index_job


class _FakeConsumer:
    """Minimal stand-in for InlineIndexConsumer.

    ``index_queue()`` is expected to return ``consumer.queue`` (the queue.Queue
    owned by the registered consumer). This fake only needs that one attribute.
    """

    def __init__(self, maxsize: int = 10) -> None:
        self.queue: queue.Queue = queue.Queue(maxsize=maxsize)


def _register(consumer) -> None:
    consumer_mod._register_consumer(consumer)


def _reset() -> None:
    consumer_mod._register_consumer(None)


@pytest.fixture(autouse=True)
def _clear_consumer_singleton():
    yield
    try:
        consumer_mod._register_consumer(None)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# job shape
# --------------------------------------------------------------------------- #

def test_enqueue_puts_job_with_retry_count_zero():
    async def _run():
        c = _FakeConsumer()
        _register(c)
        try:
            result = enqueue_index_job(
                app_id="myapp",
                file_id="file-1",
                presigned_url="https://example.com/p",
                s3_url="s3://bucket/key",
                filename="doc.pdf",
            )
            job = c.queue.get_nowait()
            assert job == {
                "app_id": "myapp",
                "file_id": "file-1",
                "presigned_url": "https://example.com/p",
                "s3_url": "s3://bucket/key",
                "filename": "doc.pdf",
                "retry_count": 0,
            }
            assert "job_id" not in job
            assert result == {"file_id": "file-1"}
        finally:
            _reset()

    asyncio.run(_run())


def test_enqueue_returns_only_file_id_no_job_id():
    async def _run():
        c = _FakeConsumer()
        _register(c)
        try:
            result = enqueue_index_job(
                app_id="myapp",
                file_id="abc",
                presigned_url="u",
                s3_url="s",
                filename="f.pdf",
            )
            assert result == {"file_id": "abc"}
            assert "job_id" not in result
        finally:
            _reset()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# backpressure
# --------------------------------------------------------------------------- #

def test_enqueue_full_queue_raises_index_queue_rejected():
    async def _run():
        c = _FakeConsumer(maxsize=2)
        c.queue.put_nowait({"file_id": "occupant-1"})
        c.queue.put_nowait({"file_id": "occupant-2"})
        _register(c)
        try:
            with pytest.raises(IndexQueueRejected):
                enqueue_index_job(
                    app_id="myapp",
                    file_id="overflow",
                    presigned_url="u",
                    s3_url="s",
                    filename="f.pdf",
                )
        finally:
            _reset()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# singleton wiring
# --------------------------------------------------------------------------- #

def test_enqueue_uses_registered_queue_singleton():
    async def _run():
        c = _FakeConsumer()
        _register(c)
        try:
            enqueue_index_job(
                app_id="a", file_id="f1", presigned_url="u", s3_url="s", filename="n.pdf"
            )
            enqueue_index_job(
                app_id="a", file_id="f2", presigned_url="u", s3_url="s", filename="n.pdf"
            )
            ids = sorted(c.queue.get_nowait()["file_id"] for _ in range(2))
            assert ids == ["f1", "f2"]
        finally:
            _reset()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# no-redis contract
# --------------------------------------------------------------------------- #

def test_enqueue_module_does_not_import_redis_or_repository():
    """The in-process queue must not depend on redis or the old repository module."""
    source = inspect.getsource(queue_mod)
    lowered = source.lower()
    assert "import redis" not in lowered
    assert "from redis" not in lowered
    assert "repository" not in lowered


# --------------------------------------------------------------------------- #
# maxsize configuration (design §3 key-decision table; §8.1)
# --------------------------------------------------------------------------- #

def test_consumer_queue_maxsize_reads_env(monkeypatch):
    from indexing.consumer import InlineIndexConsumer

    monkeypatch.setenv("INDEX_MAX_PENDING_JOBS", "3")
    consumer = InlineIndexConsumer(application=None)
    try:
        assert consumer.queue.maxsize == 3
    finally:
        consumer.executor.shutdown(wait=False)
