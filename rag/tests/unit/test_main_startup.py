import pytest


pytestmark = pytest.mark.unit


def test_component_status_stays_loading_until_application_ready(monkeypatch):
    from rag.api.runtime import runtime
    from rag.api.services import common as service

    class ReadyComponent:
        ready = True

    monkeypatch.setattr(runtime.application, "ready", False)

    assert service.component_status(ReadyComponent(), enabled=True) == "loading"

    monkeypatch.setattr(runtime.application, "ready", True)

    assert service.component_status(ReadyComponent(), enabled=True) == "ready"


def test_required_component_status_has_no_disabled_state(monkeypatch):
    from rag.api.runtime import runtime
    from rag.api.services import common as service

    class StoppedComponent:
        ready = False

    monkeypatch.setattr(runtime.application, "ready", True)

    assert service.required_component_status(StoppedComponent()) == "loading"
    assert service.required_component_status(StoppedComponent(), error="failed") == "error"
    assert service.component_status(StoppedComponent(), enabled=False) == "disabled"


def test_startup_leaves_collection_initialization_to_app_context(monkeypatch):
    import threading
    import main
    from rag.api.runtime import runtime

    class Store:
        def __init__(self):
            self.initialized = []

        def ensure_app_collection(self, app_id):
            self.initialized.append(app_id)

    class Application:
        def __init__(self, config):
            self.config = config
            self.ready = False
            self.store = Store()

        def start(self):
            self.ready = True

        def stop(self):
            pass

    application = Application(runtime.application.config)
    monkeypatch.setattr(runtime, "application", application)

    main._start_application_until_ready(threading.Event())

    assert application.store.initialized == []
