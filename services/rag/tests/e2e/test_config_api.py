import pytest


pytestmark = pytest.mark.e2e


class TestConfigAPI:
    def test_get_config(self, api_client):
        """``GET /api/rag/config`` returns the search configuration."""
        resp = api_client.get("/api/rag/config")
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["node_id"]
        assert cfg["top_k"]
        assert cfg["services"]["parser"]["base_url"]
        assert cfg["services"]["inference"]["base_url"]
        assert cfg["services"]["vector"]["base_url"]

    def test_get_config_includes_components(self, api_client):
        """``GET /api/rag/config`` returns the active component profile."""
        resp = api_client.get("/api/rag/config")
        assert resp.status_code == 200
        cfg = resp.json()

        assert cfg["config_name"]
        assert cfg["services"]["parser"]["base_url"]
        assert cfg["services"]["inference"]["base_url"]
        assert cfg["services"]["vector"]["base_url"]

    def test_put_config_not_available(self, api_client):
        """``PUT /api/rag/config`` is not part of the production API."""
        resp = api_client.put(
            "/api/rag/config",
            json={"top_k": 8},
        )
        assert resp.status_code == 405
