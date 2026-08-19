"""indexing.consumer.InlineIndexConsumer 单元测试（架构 C）。

契约来源：docs/architecture-c-inline-index-worker.md §4.2 / §4.4。覆盖：

- ``_run_job``：成功即完成；``ValueError`` 不可重试直接丢弃；超时和一般异常
  进入重试分支，``retry_count`` 小于 ``retry_max`` 时重新入队（计数 +1），
  达到上限后记日志放弃；重入队遇队列满被静默吞掉。
- ``_index_object``：进入 app_context 后调用索引服务；app 集合不存在时抛
  ``ValueError``（从 tasks.py:47-64 迁移）。
- ``index_queue()`` / ``_register_consumer()``：模块级单例，返回/注册消费器
  持有的 queue.Queue，传 ``None`` 清空（测试隔离用）。
- ``ThreadPoolExecutor(max_workers=1)``：索引调用串行执行。
- ``_loop``：start 后按序消费队列任务；stop 在 stop_event 置位后约 1 秒内退出。
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time

import pytest

import indexing.consumer as consumer_mod
from collection_names import collection_name_for_app, current_collection


# --------------------------------------------------------------------------- #
# 测试替身
# --------------------------------------------------------------------------- #

class FakeStore:
    """记录 app_collection_exists / app_context / add_file_chunks 调用。

    ``app_context`` 委托给真实的 ``collection_names.app_collection``
    contextmanager，保证 ContextVar 传播被真实执行。
    """

    def __init__(self, *, exists: bool = True) -> None:
        self._exists = exists
        self.app_context_calls: list[str] = []
        self.add_chunks_calls: list[tuple[str, list]] = []

    def app_collection_exists(self, app_id: str) -> bool:
        return self._exists

    def app_context(self, app_id: str):
        from collection_names import app_collection

        self.app_context_calls.append(app_id)
        return app_collection(app_id)

    def add_file_chunks(self, chunks, *, file_id: str) -> int:
        self.add_chunks_calls.append((file_id, list(chunks)))
        return len(chunks)


class FakeApplication:
    def __init__(self, store: FakeStore | None = None) -> None:
        self.store = store or FakeStore()


def _job(
    *,
    app_id: str = "myapp",
    file_id: str = "f1",
    retry_count: int = 0,
    presigned_url: str = "https://example.com/p",
    s3_url: str = "s3://bucket/key",
    filename: str = "doc.pdf",
) -> dict:
    return {
        "app_id": app_id,
        "file_id": file_id,
        "presigned_url": presigned_url,
        "s3_url": s3_url,
        "filename": filename,
        "retry_count": retry_count,
    }


@pytest.fixture(autouse=True)
def _clear_consumer_singleton():
    yield
    try:
        consumer_mod._register_consumer(None)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# _run_job：成功
# --------------------------------------------------------------------------- #

def test_run_job_success_consumes_without_retry(monkeypatch):
    calls: list[dict] = []

    def fake_index_object(application, job):
        calls.append(job)
        return {"app_id": job["app_id"], "file_id": job["file_id"], "chunk_count": 5}

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(), queue=queue.Queue(maxsize=10)
        )
        try:
            await c._run_job(_job(file_id="f1"))
            assert len(calls) == 1
            assert calls[0]["file_id"] == "f1"
            assert c.queue.empty()
        finally:
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _run_job：不可重试的 ValueError
# --------------------------------------------------------------------------- #

def test_run_job_value_error_is_dropped_not_retried(monkeypatch):
    calls: list[dict] = []

    def fake_index_object(application, job):
        calls.append(job)
        raise ValueError("app database is not initialized")

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(), queue=queue.Queue(maxsize=10)
        )
        try:
            await c._run_job(_job(file_id="f1"))
            assert len(calls) == 1
            assert c.queue.empty(), "ValueError must not re-enqueue the job"
        finally:
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _run_job：可重试的一般异常
# --------------------------------------------------------------------------- #

def test_run_job_generic_exception_re_enqueues_with_incremented_retry(monkeypatch):
    def fake_index_object(application, job):
        raise RuntimeError("transient failure")

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(),
            queue=queue.Queue(maxsize=10),
            retry_max=2,
        )
        try:
            j = _job(file_id="f1", retry_count=0)
            await c._run_job(j)
            requeued = c.queue.get_nowait()
            assert requeued["file_id"] == "f1"
            assert requeued["retry_count"] == 1
        finally:
            await c.stop()

    asyncio.run(_run())


def test_run_job_retry_exhausted_drops_job(monkeypatch):
    def fake_index_object(application, job):
        raise RuntimeError("still failing")

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(),
            queue=queue.Queue(maxsize=10),
            retry_max=2,
        )
        try:
            await c._run_job(_job(file_id="f1", retry_count=2))
            assert c.queue.empty(), "retry_count>=retry_max must drop the job"
        finally:
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _run_job：超时（asyncio.wait_for）按可重试处理
# --------------------------------------------------------------------------- #

def test_run_job_timeout_re_enqueues_with_incremented_retry(monkeypatch):
    done_event = threading.Event()

    def slow_index_object(application, job):
        # 阻塞时间超过注入的 timeout。executor 线程无法被中断；断言后用 event 释放它。
        done_event.wait(timeout=5.0)
        return {"chunk_count": 0}

    monkeypatch.setattr(consumer_mod, "_index_object", slow_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(),
            queue=queue.Queue(maxsize=10),
            timeout=0.05,
            retry_max=2,
        )
        try:
            await c._run_job(_job(file_id="f1", retry_count=0))
            requeued = c.queue.get_nowait()
            assert requeued["file_id"] == "f1"
            assert requeued["retry_count"] == 1
        finally:
            done_event.set()
            await c.stop()

    asyncio.run(_run())


def test_run_job_timeout_retry_exhausted_drops_job(monkeypatch):
    done_event = threading.Event()

    def slow_index_object(application, job):
        done_event.wait(timeout=5.0)
        return {"chunk_count": 0}

    monkeypatch.setattr(consumer_mod, "_index_object", slow_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(),
            queue=queue.Queue(maxsize=10),
            timeout=0.05,
            retry_max=2,
        )
        try:
            await c._run_job(_job(file_id="f1", retry_count=2))
            assert c.queue.empty(), "timeout at retry_count>=retry_max must drop"
        finally:
            done_event.set()
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _run_job：队列满时重入队被静默吞掉
# --------------------------------------------------------------------------- #

def test_reenqueue_when_queue_full_drops_silently(monkeypatch):
    def failing_index_object(application, job):
        raise RuntimeError("fail")

    monkeypatch.setattr(consumer_mod, "_index_object", failing_index_object)

    async def _run():
        # 队列里已有占位任务；失败任务的重入队必须被拒绝。
        q = queue.Queue(maxsize=1)
        q.put_nowait(_job(file_id="occupant"))
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(), queue=q, retry_max=5
        )
        try:
            # 失败任务直接传入（不经过队列）；失败后尝试重入队，
            # 但队列已满 -> 被静默吞掉。
            await c._run_job(_job(file_id="failing"))
            assert q.qsize() == 1
            assert q.get_nowait()["file_id"] == "occupant"
        finally:
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# app_context 传播（真实 _index_object + 假 application + 假索引服务）
# --------------------------------------------------------------------------- #

def test_index_object_enters_app_context_for_app(monkeypatch):
    seen: dict = {}

    def fake_index_presigned(application, file_id, presigned_url, s3_url, filename):
        seen["collection"] = current_collection()
        seen["file_id"] = file_id
        return 7

    monkeypatch.setattr(consumer_mod, "index_presigned_object", fake_index_presigned)
    store = FakeStore(exists=True)
    app = FakeApplication(store=store)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=app, queue=queue.Queue(maxsize=10)
        )
        try:
            await c._run_job(_job(app_id="myapp", file_id="f1"))
            assert store.app_context_calls == ["myapp"]
            assert seen["collection"] == collection_name_for_app("myapp")
            assert seen["file_id"] == "f1"
        finally:
            await c.stop()

    asyncio.run(_run())


def test_app_context_isolation_between_apps(monkeypatch):
    seen: list[tuple[str, str]] = []

    def fake_index_presigned(application, file_id, presigned_url, s3_url, filename):
        seen.append((file_id, current_collection()))
        return 1

    monkeypatch.setattr(consumer_mod, "index_presigned_object", fake_index_presigned)
    store = FakeStore(exists=True)
    app = FakeApplication(store=store)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=app, queue=queue.Queue(maxsize=10)
        )
        try:
            await c._run_job(_job(app_id="appA", file_id="fA"))
            await c._run_job(_job(app_id="appB", file_id="fB"))
            assert seen == [
                ("fA", collection_name_for_app("appA")),
                ("fB", collection_name_for_app("appB")),
            ]
        finally:
            await c.stop()

    asyncio.run(_run())


def test_index_object_raises_value_error_when_app_collection_missing(monkeypatch):
    """app_collection_exists 为 False -> ValueError -> _run_job 丢弃（不可重试）。"""
    monkeypatch.setattr(
        consumer_mod, "index_presigned_object", lambda *a, **k: pytest.fail("must not be called")
    )
    store = FakeStore(exists=False)
    app = FakeApplication(store=store)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=app, queue=queue.Queue(maxsize=10)
        )
        try:
            await c._run_job(_job(app_id="myapp", file_id="f1"))
            assert c.queue.empty(), "missing collection must drop, not retry"
        finally:
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# 串行执行（ThreadPoolExecutor max_workers=1）
# --------------------------------------------------------------------------- #

def test_serial_processing_no_concurrent_index_calls(monkeypatch):
    timeline: list[tuple[float, float]] = []
    lock = threading.Lock()

    def slow_index_object(application, job):
        start = time.monotonic()
        time.sleep(0.05)
        end = time.monotonic()
        with lock:
            timeline.append((start, end))
        return {"chunk_count": 0}

    monkeypatch.setattr(consumer_mod, "_index_object", slow_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(), queue=queue.Queue(maxsize=10)
        )
        try:
            await asyncio.gather(c._run_job(_job(file_id="f1")), c._run_job(_job(file_id="f2")))
            assert len(timeline) == 2
            (s1, e1), (s2, e2) = timeline
            # 时间区间不得重叠（max_workers=1 串行化 executor 调用）
            assert e1 <= s2 or e2 <= s1
        finally:
            await c.stop()

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# _loop 集成：start 后按序消费队列任务；stop 优雅退出
# --------------------------------------------------------------------------- #

def test_loop_consumes_jobs_in_order(monkeypatch):
    processed: list[str] = []

    def fake_index_object(application, job):
        processed.append(job["file_id"])
        return {"chunk_count": 1}

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)

    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(), queue=queue.Queue(maxsize=10)
        )
        for fid in ("a", "b", "c"):
            c.queue.put_nowait(_job(file_id=fid))
        await c.start()
        try:
            for _ in range(200):
                if len(processed) == 3:
                    break
                await asyncio.sleep(0.01)
            assert processed == ["a", "b", "c"]
            assert c.queue.empty()
        finally:
            await c.stop()

    asyncio.run(_run())


def test_stop_terminates_loop_gracefully():
    async def _run():
        c = consumer_mod.InlineIndexConsumer(
            application=FakeApplication(), queue=queue.Queue(maxsize=10)
        )
        await c.start()
        try:
            t0 = time.monotonic()
            await asyncio.wait_for(c.stop(), timeout=2.0)
            elapsed = time.monotonic() - t0
            # 设计 §8.1：stop_event 置位后 _loop 在约 1 秒内退出
            assert elapsed < 1.5
            assert c.task.done()
        except asyncio.TimeoutError:
            pytest.fail("consumer.stop() did not return within 2s")

    asyncio.run(_run())
