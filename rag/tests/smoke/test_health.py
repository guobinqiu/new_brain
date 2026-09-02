import pytest


pytestmark = pytest.mark.smoke


def test_health(api_client):
    """``GET /api/open/rag/health`` returns ok."""
    resp = api_client.get("/api/open/rag/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
