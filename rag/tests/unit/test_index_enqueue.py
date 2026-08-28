"""index.queue.enqueue_index_job 单元测试（架构 C）。

契约来源：docs/architecture-c-inline-index-worker.md §4.5：

    enqueue_index_job(*, app_id, file_id, presigned_url, s3_url, filename) -> {"file_id": file_id}

- 把 ``{app_id, file_id, presigned_url, s3_url, filename, retry_count: 0}``
  字典放入 ``InlineIndexConsumer`` 注册的进程级 ``queue.Queue``。
- 队列满 -> ``IndexQueueRejected``（API 层映射为 429）。
- 无 ``job_id``（返回只有 ``{"file_id"}``）。
- 不 import redis / index.repository（进程内队列，无 broker）。
"""
from __future__ import annotations

import asyncio
import inspect
import queue

import pytest

import rag.index.consumer as consumer_mod
import rag.index.queue as queue_mod
from rag.index.queue import IndexQueueRejected, enqueue_index_job


class _FakeConsumer:
    """InlineIndexConsumer 的最小替身。

    ``index_queue()`` 预期返回 ``consumer.queue``（已注册消费器持有的
    queue.Queue）。这个替身只需要这一个属性。
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
# job 字典结构
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
# 背压
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
# 单例接线
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
# 无 redis 契约
# --------------------------------------------------------------------------- #

def test_enqueue_module_does_not_import_redis_or_repository():
    """进程内队列不得依赖 redis 或旧 repository 模块。"""
    source = inspect.getsource(queue_mod)
    lowered = source.lower()
    assert "import redis" not in lowered
    assert "from redis" not in lowered
    assert "repository" not in lowered
