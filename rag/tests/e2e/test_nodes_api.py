import pytest


pytestmark = pytest.mark.e2e


def test_nodes_monitor_returns_local_node_when_peers_empty(api_client, monkeypatch):
    monkeypatch.delenv("RAG_PEERS", raising=False)
    monkeypatch.setenv("RAG_NODE_ID", "node-local")

    resp = api_client.get("/api/nodes/monitor")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["nodes"]) == 1
    node = body["nodes"][0]
    assert node["node_id"] == "node-local"
    assert node["base_url"] == "local"
    assert node["status"] == "ok"
    assert node["data"]["node_id"] == "node-local"
    assert "generated_at" in body


def test_nodes_config_returns_local_node_when_peers_empty(api_client, monkeypatch):
    monkeypatch.delenv("RAG_PEERS", raising=False)
    monkeypatch.setenv("RAG_NODE_ID", "node-local")

    resp = api_client.get("/api/nodes/config")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["nodes"]) == 1
    node = body["nodes"][0]
    assert node["node_id"] == "node-local"
    assert node["status"] == "ok"
    assert node["data"]["node_id"] == "node-local"
    assert node["data"]["config_name"]
