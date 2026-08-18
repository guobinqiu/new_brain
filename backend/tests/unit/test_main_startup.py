import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.unit


def test_lifespan_keeps_process_healthy_when_application_start_fails(monkeypatch):
    from auth import Principal, issue_token
    import main

    class FailingApplication:
        def __init__(self, config):
            self.config = config
            self.ready = False
            self.stop_called = False

        def start(self):
            raise RuntimeError("vector store is not ready")

        def stop(self):
            self.stop_called = True

    failing_application = FailingApplication(main.application.config)
    monkeypatch.setattr(main, "application", failing_application)
    monkeypatch.setattr(main, "STARTUP_IN_BACKGROUND", True)
    token = issue_token(failing_application.config.auth, Principal(type="admin", app_id=""))

    with TestClient(main.app) as client:
        health_resp = client.get("/api/health")
        search_resp = client.post("/api/admin/search", json={"query": "test", "app_id": "imsdom"}, headers={"Authorization": f"Bearer {token}"})

    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}
    assert search_resp.status_code == 503
    assert failing_application.stop_called is True


def test_component_status_stays_loading_until_application_ready(monkeypatch):
    import main

    class ReadyComponent:
        ready = True

    monkeypatch.setattr(main.application, "ready", False)

    assert main._component_status(ReadyComponent(), enabled=True) == "loading"

    monkeypatch.setattr(main.application, "ready", True)

    assert main._component_status(ReadyComponent(), enabled=True) == "ready"


def test_startup_leaves_collection_initialization_to_app_context(monkeypatch):
    import threading
    import main

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

    application = Application(main.application.config)
    monkeypatch.setattr(main, "application", application)

    main._start_application_until_ready(threading.Event())

    assert application.store.initialized == []
