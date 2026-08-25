import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.unit


def test_lifespan_keeps_process_healthy_when_application_start_fails(monkeypatch):
    from auth import Principal, issue_token
    import main
    from api.runtime import runtime

    class FailingApplication:
        def __init__(self, config):
            self.config = config
            self.ready = False
            self.stop_called = False

        def start(self):
            raise RuntimeError("vector store is not ready")

        def stop(self):
            self.stop_called = True

    failing_application = FailingApplication(runtime.application.config)
    monkeypatch.setattr(runtime, "application", failing_application)
    monkeypatch.setattr(runtime, "startup_in_background", True)
    token = issue_token(failing_application.config.auth, Principal(type="admin", app_id=""))

    with TestClient(main.app) as client:
        health_resp = client.get("/api/health")
        search_resp = client.post("/api/search", json={"query": "test", "app_id": "imsdom"}, headers={"Authorization": f"Bearer {token}"})

    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}
    assert search_resp.status_code == 503
    assert failing_application.stop_called is True


def test_component_status_stays_loading_until_application_ready(monkeypatch):
    from api.runtime import runtime
    from api.services import common as service

    class ReadyComponent:
        ready = True

    monkeypatch.setattr(runtime.application, "ready", False)

    assert service.component_status(ReadyComponent(), enabled=True) == "loading"

    monkeypatch.setattr(runtime.application, "ready", True)

    assert service.component_status(ReadyComponent(), enabled=True) == "ready"


def test_startup_leaves_collection_initialization_to_app_context(monkeypatch):
    import threading
    import main
    from api.runtime import runtime

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
