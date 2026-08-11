import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.unit


def test_lifespan_keeps_process_healthy_when_application_start_fails(monkeypatch):
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

    with TestClient(main.app) as client:
        health_resp = client.get("/api/health")
        search_resp = client.post("/api/search", json={"query": "test"})
        upload_resp = client.post(
            "/api/upload",
            files={"file": ("test.txt", b"test", "text/plain")},
        )

    assert health_resp.status_code == 200
    assert health_resp.json() == {"status": "ok"}
    assert search_resp.status_code == 503
    assert upload_resp.status_code == 503
    assert failing_application.stop_called is True
