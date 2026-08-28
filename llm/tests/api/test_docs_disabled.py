"""Interactive API documentation exposure tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_interactive_api_documentation_endpoints_are_not_exposed():
    client = TestClient(app)

    for path in ("/docs", "/openapi.json", "/redoc"):
        resp = client.get(path)
        assert resp.status_code == 404, f"{path} should not be exposed"
