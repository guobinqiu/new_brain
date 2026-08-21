import pytest


pytestmark = pytest.mark.e2e


class TestConfigAPI:
    def test_get_config(self, api_client):
        """``GET /api/config`` returns the search configuration."""
        resp = api_client.get("/api/config")
        assert resp.status_code == 200
        cfg = resp.json()
        assert cfg["node_id"]
        for key in ("default_mode", "top_k", "rerank", "rerank_available", "fetch_k", "dense_weight", "sparse_weight", "rrf_k"):
            assert key in cfg
        assert cfg["sparse"]["name"] == "bm25"

    def test_get_config_includes_components(self, api_client):
        """``GET /api/config`` returns the active component profile."""
        resp = api_client.get("/api/config")
        assert resp.status_code == 200
        cfg = resp.json()

        assert cfg["config_name"]
        assert cfg["store"]["type"] == "qdrant"
        assert cfg["dense"]["name"]
        assert cfg["dense"]["model_name"] == "bge-base-zh-v1.5"
        assert cfg["dense"]["model_path"]
        assert cfg["sparse"]["name"] == "bm25"
        assert cfg["sparse"]["tokenizer"] == "jieba"
        assert cfg["ocr"]["model_name"] == "rapidocr"
        assert cfg["ocr"]["name"]

    def test_get_config_includes_runtime_switchable_components(self, api_client):
        """``GET /api/config`` returns runtime-switchable component candidates."""
        resp = api_client.get("/api/config")
        assert resp.status_code == 200
        available = resp.json()["available_components"]

        assert any(item["name"] == "rapid" and item["active"] for item in available["ocr"])
        assert all("active" in item for item in available["rerank"])

    def test_put_config_not_available(self, api_client):
        """``PUT /api/config`` is not part of the production API."""
        resp = api_client.put(
            "/api/config",
            json={"dense_weight": 0.8, "sparse_weight": 0.2},
        )
        assert resp.status_code == 405


class TestMonitorAPI:
    def test_monitor_returns_runtime_data_and_index_contract(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``GET /api/monitor`` returns read-only runtime state."""
        from tests.e2e.test_search_api import _index_ready_file

        _index_ready_file(app_api_client, test_txt_path, monkeypatch)

        resp = api_client.get("/api/monitor")

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
        assert components["Sparse"]["model"] == "bm25"
        assert components["Rerank"]["status"] in {"disabled", "ready"}
        assert components["OCR"]["status"] == "ready"
        assert components["OCR"]["model"] == "rapidocr"
        assert "database" in components
        assert all(component["status"] in {"ready", "loading", "disabled", "error"} for component in components.values())
        assert monitor["capabilities"]["search_modes"] == ["dense", "sparse", "hybrid"]
        assert monitor["capabilities"]["config_write"] is False
        assert monitor["capabilities"]["restart"] is False

    def test_traces_returns_search_trace_list_after_search(self, app_api_client, api_client, test_txt_path, monkeypatch):
        """``GET /api/traces`` exposes recent search traces for diagnostics."""
        from tests.e2e.test_search_api import _index_ready_file

        file_id = _index_ready_file(app_api_client, test_txt_path, monkeypatch)
        app_api_client.post(
            "/api/open/search",
            json={"query": "人工智能", "mode": "hybrid", "top_k": 5, "file_ids": [file_id]},
        )

        resp = api_client.get("/api/traces", params={"app_id": app_api_client.app_id})

        assert resp.status_code == 200
        traces = resp.json()["traces"]
        assert len(traces) >= 1
        trace = traces[0]
        assert trace["trace_id"]
        assert trace["name"] == "search"
        assert trace["query"] == "人工智能"
        assert trace["elapsed_ms"] >= 0
        assert trace["result_count"] >= 0
        stage_names = {stage["name"] for stage in trace["stages"]}
        assert "prepare_plan" in stage_names
        assert "dedupe" in stage_names
        assert "format_response" in stage_names
