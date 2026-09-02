import pytest


pytestmark = pytest.mark.e2e


class TestConfigAPI:
    def test_get_config(self, api_client):
        """``GET /api/open/rag/config`` returns the search configuration."""
        resp = api_client.get("/api/open/rag/config")
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["node_id"]
        for key in ("default_mode", "top_k", "rerank", "rerank_available", "fetch_k", "dense_weight", "sparse_weight", "rrf_k"):
            assert key in cfg
        assert cfg["sparse"]["name"] == "opensearch_bm25"
        assert isinstance(cfg["parser"]["available"], bool)

    def test_get_config_includes_components(self, api_client):
        """``GET /api/open/rag/config`` returns the active component profile."""
        resp = api_client.get("/api/open/rag/config")
        assert resp.status_code == 200
        cfg = resp.json()

        assert cfg["config_name"]
        assert cfg["store"]["type"] == "qdrant"
        assert cfg["dense"]["name"]
        assert cfg["dense"]["model_name"] == "bge-base-zh-v1.5"
        assert cfg["dense"]["model_path"]
        assert cfg["sparse"]["name"] == "opensearch_bm25"
        assert cfg["sparse"]["url"] == "http://opensearch:9200"
        assert cfg["ocr"]["model_name"] == "paddleocr"
        assert cfg["ocr"]["name"]

    def test_get_config_includes_runtime_switchable_components(self, api_client):
        """``GET /api/open/rag/config`` returns runtime-switchable component candidates."""
        resp = api_client.get("/api/open/rag/config")
        assert resp.status_code == 200
        available = resp.json()["available_components"]

        assert any(item["name"] == "paddle" and item["active"] for item in available["ocr"])
        assert all("active" in item for item in available["rerank"])

    def test_put_config_not_available(self, api_client):
        """``PUT /api/open/rag/config`` is not part of the production API."""
        resp = api_client.put(
            "/api/open/rag/config",
            json={"dense_weight": 0.8, "sparse_weight": 0.2},
        )
        assert resp.status_code == 405


class TestMonitorAPI:
    def test_monitor_returns_runtime_data_and_index_contract(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``GET /api/open/rag/monitor`` returns read-only runtime state."""
        from tests.e2e.test_search_api import _index_ready_file

        _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = api_client.get("/api/open/rag/monitor")

        assert resp.status_code == 200
        monitor = resp.json()
        assert monitor["ready"] is True
        assert monitor["node_id"]
        assert monitor["profile"]["config_name"]
        assert monitor["profile"]["store"]["type"] == "qdrant"
        components = {component["name"]: component for component in monitor["components"]}
        assert components["Store"]["status"] == "ready"
        assert components["Store"]["model"] == "qdrant"
        assert components["Dense"]["status"] == "ready"
        assert components["Dense"]["model"] == "bge-base-zh-v1.5"
        assert components["Sparse"]["status"] == "ready"
        assert components["Sparse"]["model"] == "opensearch_bm25"
        assert components["Rerank"]["status"] in {"disabled", "ready"}
        assert components["OCR"]["status"] == "ready"
        assert components["OCR"]["model"] == "paddleocr"
        parser_config = api_client.get("/api/open/rag/config").json()["parser"]
        expected_parser_status = "ready" if parser_config["available"] else "error"
        assert components["Parser"]["status"] == expected_parser_status
        assert components["Parser"]["model"] == parser_config["enabled"]
        assert "database" in components
        assert all(component["status"] in {"ready", "loading", "disabled", "error"} for component in components.values())
        assert monitor["capabilities"]["search_modes"] == ["dense", "sparse", "hybrid"]
        assert monitor["capabilities"]["config_write"] is False
        assert monitor["capabilities"]["restart"] is False
