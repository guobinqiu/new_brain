from __future__ import annotations

import queue
import threading
import time

import pytest

import rag.index.consumer as consumer_mod
from rag.scope import collection_name_for_app, current_collection


pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(self, *, exists: bool = True) -> None:
        self._exists = exists
        self.app_context_calls: list[str] = []

    def app_collection_exists(self, app_id: str) -> bool:
        return self._exists

    def app_context(self, app_id: str):
        from rag.scope import app_collection

        self.app_context_calls.append(app_id)
        return app_collection(app_id)


class FakeDatabase:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def mark_file_indexing(self, app_id, file_id) -> None:
        self.calls.append(("indexing", app_id, file_id))

    def upsert_file(self, app_id, file_id, filename, s3_url, **kwargs) -> None:
        self.calls.append(("success", app_id, file_id, filename, s3_url, kwargs))

    def mark_file_failed(self, app_id, file_id, error) -> None:
        self.calls.append(("failed", app_id, file_id, error))


class FakeApplication:
    def __init__(self, store: FakeStore | None = None, database: FakeDatabase | None = None) -> None:
        self.store = store or FakeStore()
        self.database = database or FakeDatabase()


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
    consumer_mod._register_consumer(None)


def test_run_job_marks_indexing_then_success(monkeypatch):
    def fake_index_object(application, job):
        return {
            "app_id": job["app_id"],
            "file_id": job["file_id"],
            "chunk_count": 5,
            "size": 10,
            "s3_url": job["s3_url"],
            "filename": job["filename"],
        }

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)
    db = FakeDatabase()
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(database=db), queue=queue.Queue(maxsize=10))

    consumer._run_job(_job(file_id="f1"))

    assert db.calls == [
        ("indexing", "myapp", "f1"),
        ("success", "myapp", "f1", "doc.pdf", "s3://bucket/key", {"size": 10, "chunk_count": 5}),
    ]
    assert consumer.queue.empty()


def test_run_job_value_error_marks_failed_without_retry(monkeypatch):
    def fake_index_object(application, job):
        raise ValueError("app database is not initialized")

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)
    db = FakeDatabase()
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(database=db), queue=queue.Queue(maxsize=10))

    consumer._run_job(_job(file_id="f1"))

    assert consumer.queue.empty()
    assert db.calls == [
        ("indexing", "myapp", "f1"),
        ("failed", "myapp", "f1", "app database is not initialized"),
    ]


def test_run_job_generic_exception_re_enqueues_with_incremented_retry(monkeypatch):
    def fake_index_object(application, job):
        raise RuntimeError("transient failure")

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)
    db = FakeDatabase()
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(database=db), queue=queue.Queue(maxsize=10), retry_max=2)

    consumer._run_job(_job(file_id="f1", retry_count=0))
    requeued = consumer.queue.get_nowait()

    assert requeued["file_id"] == "f1"
    assert requeued["retry_count"] == 1
    assert db.calls == [("indexing", "myapp", "f1")]


def test_run_job_retry_exhausted_marks_failed(monkeypatch):
    def fake_index_object(application, job):
        raise RuntimeError("still failing")

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)
    db = FakeDatabase()
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(database=db), queue=queue.Queue(maxsize=10), retry_max=2)

    consumer._run_job(_job(file_id="f1", retry_count=2))

    assert consumer.queue.empty()
    assert db.calls == [
        ("indexing", "myapp", "f1"),
        ("failed", "myapp", "f1", "index failed: RuntimeError('still failing')"),
    ]


def test_reenqueue_when_queue_full_marks_failed(monkeypatch):
    def failing_index_object(application, job):
        raise RuntimeError("fail")

    monkeypatch.setattr(consumer_mod, "_index_object", failing_index_object)
    q = queue.Queue(maxsize=1)
    q.put_nowait(_job(file_id="occupant"))
    db = FakeDatabase()
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(database=db), queue=q, retry_max=5)

    consumer._run_job(_job(file_id="failing"))

    assert q.qsize() == 1
    assert q.get_nowait()["file_id"] == "occupant"
    assert db.calls == [
        ("indexing", "myapp", "failing"),
        ("failed", "myapp", "failing", "index queue full while retrying"),
    ]


def test_index_object_enters_app_context_for_app(monkeypatch):
    seen: dict = {}

    def fake_index_presigned(application, file_id, presigned_url, s3_url, filename):
        seen["collection"] = current_collection()
        seen["file_id"] = file_id
        return 7, 1

    monkeypatch.setattr(consumer_mod, "index_presigned_object", fake_index_presigned)
    store = FakeStore(exists=True)
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(store=store), queue=queue.Queue(maxsize=10))

    consumer._run_job(_job(app_id="myapp", file_id="f1"))

    assert store.app_context_calls == ["myapp"]
    assert seen["collection"] == collection_name_for_app("myapp")
    assert seen["file_id"] == "f1"


def test_app_context_isolation_between_apps(monkeypatch):
    seen: list[tuple[str, str]] = []

    def fake_index_presigned(application, file_id, presigned_url, s3_url, filename):
        seen.append((file_id, current_collection()))
        return 1, 1

    monkeypatch.setattr(consumer_mod, "index_presigned_object", fake_index_presigned)
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(store=FakeStore(exists=True)), queue=queue.Queue(maxsize=10))

    consumer._run_job(_job(app_id="appA", file_id="fA"))
    consumer._run_job(_job(app_id="appB", file_id="fB"))

    assert seen == [
        ("fA", collection_name_for_app("appA")),
        ("fB", collection_name_for_app("appB")),
    ]


def test_index_object_missing_app_collection_marks_failed(monkeypatch):
    monkeypatch.setattr(
        consumer_mod, "index_presigned_object", lambda *a, **k: pytest.fail("must not be called")
    )
    consumer = consumer_mod.InlineIndexConsumer(
        FakeApplication(store=FakeStore(exists=False)), queue=queue.Queue(maxsize=10)
    )

    consumer._run_job(_job(app_id="myapp", file_id="f1"))

    assert consumer.queue.empty()
    assert consumer.application.database.calls[-1] == (
        "failed",
        "myapp",
        "f1",
        "app database is not initialized",
    )


def test_loop_consumes_jobs_in_order(monkeypatch):
    processed: list[str] = []

    def fake_index_object(application, job):
        processed.append(job["file_id"])
        return {
            "app_id": job["app_id"],
            "file_id": job["file_id"],
            "chunk_count": 1,
            "size": 1,
            "s3_url": job["s3_url"],
            "filename": job["filename"],
        }

    monkeypatch.setattr(consumer_mod, "_index_object", fake_index_object)
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(), queue=queue.Queue(maxsize=10))
    for fid in ("a", "b", "c"):
        consumer.queue.put_nowait(_job(file_id=fid))

    consumer.start()
    try:
        for _ in range(200):
            if len(processed) == 3:
                break
            time.sleep(0.01)
        assert processed == ["a", "b", "c"]
        assert consumer.queue.empty()
    finally:
        consumer.stop()


def test_stop_terminates_loop_gracefully():
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(), queue=queue.Queue(maxsize=10))
    consumer.start()
    t0 = time.monotonic()
    consumer.stop()

    assert time.monotonic() - t0 < 1.5
    assert consumer.thread is not None
    assert not consumer.thread.is_alive()


def test_index_queue_returns_registered_queue():
    consumer = consumer_mod.InlineIndexConsumer(FakeApplication(), queue=queue.Queue(maxsize=10))
    consumer.start()
    try:
        assert consumer_mod.index_queue() is consumer.queue
    finally:
        consumer.stop()
