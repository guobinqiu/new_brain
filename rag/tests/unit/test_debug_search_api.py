from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from rag.api.runtime import runtime


pytestmark = pytest.mark.unit


class DebugDense:
    ready = True

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class DebugSparse:
    ready = True

    def supports_sparse_vector(self):
        return True

    def embed_query(self, text):
        return {"9": 0.9, "3": 0.3}


class DebugStore:
    ready = True

    def __init__(self):
        self.calls = []

    def app_collection_exists(self, app_id):
        return True

    def app_context(self, app_id):
        from contextlib import nullcontext

        self.calls.append(("app_context", app_id))
        return nullcontext()

    def build_file_filter(self, file_ids=None):
        self.calls.append(("build_file_filter", tuple(file_ids or [])))
        return ("file-filter", tuple(file_ids or []))

    def search_dense(self, query, limit, metadata_filter):
        self.calls.append(("search_dense", query, limit, metadata_filter))
        return [
            {
                "id": "dense-1",
                "content": "dense content",
                "metadata": {"file_id": "file-a", "chunk_index": 1},
                "_score": 0.8,
            }
        ]

    def search_sparse(self, query, limit, metadata_filter):
        self.calls.append(("search_sparse", query, limit, metadata_filter))
        return [
            {
                "id": "sparse-1",
                "content": "sparse content",
                "metadata": {"file_id": "file-a", "chunk_index": 2},
                "_score": 0.9,
            }
        ]

    def sparse_uses_store(self, sparse=None):
        return True


def test_debug_dense_search_encodes_query_and_searches_dense(monkeypatch, tmp_path):
    from rag.auth import Principal, issue_token
    from rag.schema import AuthConfig, AdminAuthConfig, SparseBackendConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(
        runtime.application.config,
        auth=auth_config,
        sparse=SparseBackendConfig(name="bge_m3", model_path="model"),
    )
    store = DebugStore()

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = DebugSparse()
            self.store = store

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "application", Application())
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/open/rag/apps/tenant_a/debug/dense-search",
            json={"query": "表见代理", "top_k": 3, "file_ids": ["file-a"]},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "dense"
    assert body["query_vector"] == [0.1, 0.2, 0.3]
    assert body["results"][0]["id"] == "dense-1"
    assert store.calls == [
        ("build_file_filter", ("file-a",)),
        ("app_context", "tenant_a"),
        ("search_dense", "表见代理", 3, ("file-filter", ("file-a",))),
    ]


def test_debug_sparse_search_encodes_query_and_searches_sparse(monkeypatch, tmp_path):
    from rag.auth import Principal, issue_token
    from rag.schema import AuthConfig, AdminAuthConfig, SparseBackendConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(
        runtime.application.config,
        auth=auth_config,
        sparse=SparseBackendConfig(name="bge_m3", model_path="model"),
    )
    store = DebugStore()

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = DebugSparse()
            self.store = store

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "application", Application())
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/open/rag/apps/tenant_a/debug/sparse-search",
            json={"query": "表见代理", "top_k": 3},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "sparse"
    assert body["query_vector"] == {"indices": [3, 9], "values": [0.3, 0.9]}
    assert body["results"][0]["id"] == "sparse-1"
    assert store.calls == [
        ("build_file_filter", ()),
        ("app_context", "tenant_a"),
        ("search_sparse", "表见代理", 3, ("file-filter", ())),
    ]


def test_debug_dense_encode_only_encodes_query(monkeypatch, tmp_path):
    from rag.auth import Principal, issue_token
    from rag.schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)
    store = DebugStore()

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = None
            self.store = store

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "application", Application())
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/open/rag/apps/tenant_a/debug/dense-encode",
            json={"query": "表见代理"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "type": "dense",
        "query": "表见代理",
        "query_vector": [0.1, 0.2, 0.3],
    }
    assert store.calls == []


def test_debug_sparse_encode_returns_400_when_sparse_disabled(monkeypatch, tmp_path):
    from rag.auth import Principal, issue_token
    from rag.schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = None
            self.store = DebugStore()

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "application", Application())
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/open/rag/apps/tenant_a/debug/sparse-encode",
            json={"query": "表见代理"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "sparse is not enabled"


def test_debug_search_accepts_top_k_up_to_100(monkeypatch, tmp_path):
    from rag.auth import Principal, issue_token
    from rag.schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)
    store = DebugStore()

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = None
            self.store = store

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "application", Application())
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/open/rag/apps/tenant_a/debug/dense-search",
            json={"query": "表见代理", "top_k": 100},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert store.calls[-1] == ("search_dense", "表见代理", 100, ("file-filter", ()))


def test_debug_search_rejects_top_k_over_100(monkeypatch, tmp_path):
    from rag.auth import Principal, issue_token
    from rag.schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.dense = DebugDense()
            self.sparse = None
            self.store = DebugStore()

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runtime, "application", Application())
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/open/rag/apps/tenant_a/debug/dense-search",
            json={"query": "表见代理", "top_k": 101},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422
