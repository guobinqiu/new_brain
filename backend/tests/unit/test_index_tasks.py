import pytest


pytestmark = pytest.mark.unit


def test_worker_parent_initialization_does_not_load_models_or_connections(monkeypatch):
    from indexing import tasks

    calls = []

    class FakeConfig:
        logging = None

    class FakeApplication:
        def __init__(self):
            self.config = FakeConfig()
            self.models_loaded = False
            self.ready = False

        def load_models(self):
            calls.append("load_models")
            self.models_loaded = True

        def init_connections(self):
            calls.append("init_connections")
            self.ready = True

    monkeypatch.setattr(tasks, "_application", None)
    monkeypatch.setattr(tasks, "Application", FakeApplication)
    monkeypatch.setattr(tasks, "configure_logging", lambda config: calls.append("configure_logging"))

    tasks.preload_parent_application()

    application = tasks._application
    assert application.models_loaded is False
    assert application.ready is False
    assert calls == ["configure_logging"]


def test_worker_child_loads_models_and_initializes_connections(monkeypatch):
    from indexing import tasks

    calls = []

    class FakeConfig:
        logging = None

    class FakeApplication:
        def __init__(self):
            self.config = FakeConfig()
            self.models_loaded = False
            self.ready = False

        def load_models(self):
            calls.append("load_models")
            self.models_loaded = True

        def init_connections(self):
            calls.append("init_connections")
            self.ready = True

    monkeypatch.setattr(tasks, "_application", None)
    monkeypatch.setattr(tasks, "Application", FakeApplication)
    monkeypatch.setattr(tasks, "configure_logging", lambda config: calls.append("configure_logging"))

    tasks.preload_parent_application()
    tasks.initialize_child_application()
    application = tasks._worker_application()

    assert application.models_loaded is True
    assert application.ready is True
    assert calls == ["configure_logging", "load_models", "init_connections"]
