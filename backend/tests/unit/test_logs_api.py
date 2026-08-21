import pytest
from fastapi.testclient import TestClient


pytestmark = pytest.mark.unit


def test_logs_stream_requires_valid_token(monkeypatch):
    from schema import AuthConfig, AdminAuthConfig
    import main

    class Application:
        def __init__(self):
            self.config = type("Config", (), {
                "auth": AuthConfig(admin=AdminAuthConfig(username="admin", password="admin123"))
            })()
            self.ready = False

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(main, "application", Application())
    monkeypatch.setattr(main, "STARTUP_IN_BACKGROUND", False)

    client = TestClient(main.app)
    missing = client.get("/api/logs/stream")
    invalid = client.get("/api/logs/stream?token=bad")
    trace_missing = client.get("/api/traces/stream")
    trace_invalid = client.get("/api/traces/stream?token=bad&app_id=test")

    assert missing.status_code == 422
    assert invalid.status_code == 401
    assert trace_missing.status_code == 422
    assert trace_invalid.status_code == 401
