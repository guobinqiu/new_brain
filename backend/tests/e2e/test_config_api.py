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

    def test_update_config(self, api_client):
        """``PUT /api/config`` updates search parameters."""
        resp = api_client.put(
            "/api/config",
            json={"dense_weight": 0.8, "sparse_weight": 0.2},
        )
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["dense_weight"] == 0.8
        assert cfg["sparse_weight"] == 0.2

    def test_update_config_partial(self, api_client):
        """``PUT /api/config`` with partial keys only changes those keys."""
        api_client.put("/api/config", json={"dense_weight": 0.5})

        resp = api_client.put("/api/config", json={"rrf_k": 99})
        cfg = resp.json()
        assert cfg["rrf_k"] == 99
        assert cfg["dense_weight"] == 0.5
