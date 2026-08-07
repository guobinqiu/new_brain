import pytest


pytestmark = pytest.mark.smoke


def test_health(api_client):
    """``GET /api/health`` returns ok."""
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
