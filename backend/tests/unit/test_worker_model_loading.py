"""Verify the Celery index-worker startup path does NOT load query-side components.

The index-worker only needs:
  - dense + sparse (embedding)
  - ocr (text extraction)
  - store (write to qdrant)

It must NOT start `rerank` or `search` (query-side), because rerank holds
~1G of GPU memory that is wasted on a worker that never serves queries.
"""

import pytest


pytestmark = pytest.mark.unit


class _FakeComponent:
    def __init__(self, name, started):
        self.name = name
        self.started = started

    def start(self):
        self.started.append(self.name)


class _FakeApplication:
    """Mimics Application's _start_component error handling without real models."""

    def __init__(self):
        self.models_loaded = False
        self.ready = False
        self.component_errors: dict[str, str] = {}
        started: list[str] = []
        self.dense = _FakeComponent("dense", started)
        self.sparse = _FakeComponent("sparse", started)
        self.ocr = _FakeComponent("ocr", started)
        self.store = _FakeComponent("store", started)
        self.rerank = _FakeComponent("rerank", started)
        self.search = _FakeComponent("search", started)
        self._started = started

    def _start_component(self, name, component):
        self.component_errors.pop(name, None)
        try:
            component.start()
        except Exception as exc:
            self.component_errors[name] = str(exc)
            raise


def test_initialize_child_application_does_not_start_rerank_or_search(monkeypatch):
    from indexing import tasks

    fake = _FakeApplication()
    monkeypatch.setattr(tasks, "_ensure_application", lambda: fake)

    tasks.initialize_child_application()

    assert fake.models_loaded is True
    assert fake.ready is True
    assert fake._started == ["dense", "sparse", "ocr", "store"]
    assert "rerank" not in fake._started
    assert "search" not in fake._started


def test_worker_application_does_not_start_rerank_or_search(monkeypatch):
    from indexing import tasks

    fake = _FakeApplication()
    monkeypatch.setattr(tasks, "_ensure_application", lambda: fake)

    application = tasks._worker_application()

    assert application is fake
    assert application.models_loaded is True
    assert application.ready is True
    assert fake._started == ["dense", "sparse", "ocr", "store"]
    assert "rerank" not in fake._started
    assert "search" not in fake._started


def test_worker_loading_short_circuits_when_already_loaded(monkeypatch):
    """Re-entry must not re-start components (state machine stays consistent)."""
    from indexing import tasks

    fake = _FakeApplication()
    fake.models_loaded = True
    fake.ready = True
    monkeypatch.setattr(tasks, "_ensure_application", lambda: fake)

    tasks.initialize_child_application()
    tasks._worker_application()

    assert fake._started == []
