import pytest


pytestmark = pytest.mark.e2e


class TestConfigAPI:
    def test_get_config(self, api_client):
        """``GET /api/config`` returns the search configuration."""
        resp = api_client.get("/api/config")
        assert resp.status_code == 200
        cfg = resp.json()
        for key in ("default_mode", "top_k", "rerank", "rerank_available", "fetch_k", "dense_weight", "sparse_weight", "rrf_k"):
            assert key in cfg
        assert "dense_min_score" not in cfg

    def test_put_config_not_available(self, api_client):
        """``PUT /api/config`` is not part of the production API."""
        resp = api_client.put(
            "/api/config",
            json={"dense_weight": 0.8, "sparse_weight": 0.2},
        )
        assert resp.status_code == 405
