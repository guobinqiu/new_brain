from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from services.rag.core.api.schemas import AppCreateRequest
from services.rag.core.api.services import apps as service
from services.rag.core.auth import Principal
from services.rag.core.auth import AppCredential


pytestmark = pytest.mark.unit


def test_pg_client_connects_lazily(monkeypatch):
    from services.rag.clients.db import postgres

    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            calls.append(("execute", sql.strip().split()[0]))

    class Pool:
        def __init__(self, *args, **kwargs):
            pass

        def open(self):
            calls.append("open")

        def wait(self):
            calls.append("wait")

        def connection(self):
            return Connection()

    monkeypatch.setattr(postgres, "ConnectionPool", Pool)

    client = postgres.PgClient("postgresql://rag:rag@postgres:5432/rag")

    assert client.ready is True
    assert client._pool is None
    assert calls == []
    client.initialize()
    assert calls == [
        "open",
        "wait",
        ("execute", "CREATE"),
        ("execute", "ALTER"),
        ("execute", "CREATE"),
        ("execute", "CREATE"),
    ]
    calls.clear()
    assert client.ping() is True
    assert calls == [("execute", "SELECT")]


def test_pg_client_discards_pool_when_initialize_fails(monkeypatch):
    from services.rag.clients.db import postgres

    calls = []

    class Pool:
        def __init__(self, *args, **kwargs):
            pass

        def open(self):
            calls.append("open")

        def wait(self):
            calls.append("wait")
            raise RuntimeError("database unavailable")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(postgres, "ConnectionPool", Pool)
    client = postgres.PgClient("postgresql://rag:rag@postgres:5432/rag")

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.initialize()

    assert client._pool is None
    assert calls == ["open", "wait", "close"]


def _state(*, vector=None, database=None, ready=True):
    from shared.config import AdminAuthConfig, AppConfig, AuthConfig, SearchConfig, ServiceClientConfig, ServiceClientsConfig, VectorServiceConfig

    config = AppConfig(
        search=SearchConfig(),
        auth=AuthConfig(
            admin=AdminAuthConfig(username="admin", password="admin123"),
        ),
        services=ServiceClientsConfig(
            parser=ServiceClientConfig(base_url="http://parser:7000"),
            inference=ServiceClientConfig(base_url="http://inference:7001"),
            vector=VectorServiceConfig(provider="qdrant", base_url="http://qdrant:6333"),
        ),
    )

    state = FastAPI().state
    state.config = config
    state.ready = ready
    state.vector_client = vector
    state.db_client = database
    return state


def test_list_apps_reads_database_api_keys(monkeypatch):
    class Database:
        def list_apps(self):
            return [AppCredential(app_id="tenant_a", api_key="tenant-a-key")]

    state = _state(database=Database())

    apps = service.list_apps(state, Principal(type="admin", app_id="admin"))["apps"]

    assert apps == [{"app_id": "tenant_a", "api_key": "tenant-a-key"}]


def test_create_and_delete_apps_use_database(monkeypatch):
    calls = []

    class Database:
        def create_app(self, app_id):
            calls.append(("create", app_id))
            return AppCredential(app_id=app_id, api_key="tenant-b-key")

        def delete_app(self, app_id):
            calls.append(("delete", app_id))
            return True

    state = _state(database=Database())

    created = service.create_app(state, AppCreateRequest(app_id="tenant_b"), Principal(type="admin", app_id="admin"))
    deleted = service.delete_app(state, "tenant_b", Principal(type="admin", app_id="admin"))

    assert created == {"app_id": "tenant_b", "api_key": "tenant-b-key"}
    assert deleted == {"app_id": "tenant_b", "deleted": True}
    assert calls == [("create", "tenant_b"), ("delete", "tenant_b")]


def test_app_database_status_and_empty_delete(monkeypatch):
    class Database:
        def purge_app(self, app_id):
            return 0

    class VectorClient:
        def __init__(self):
            self.exists = True

        def app_collection_exists(self, app_id):
            return self.exists

        def drop_app_collection(self, app_id):
            self.exists = False
            return True

        def get_total_chunks(self, file_ids=None):
            return 0

    vector = VectorClient()
    state = _state(vector=vector, database=Database(), ready=True)

    status = service.app_database_status(state, "tenant_a", Principal(type="admin", app_id="admin"))
    deleted = service.delete_app_database(state, "tenant_a", Principal(type="admin", app_id="admin"))

    assert status == {"app_id": "tenant_a", "exists": True, "chunk_count": 0, "empty": True}
    assert deleted == {"app_id": "tenant_a", "deleted": True}


def test_app_database_initialize_creates_vector_collection(monkeypatch):
    calls = []

    class VectorClient:
        def ensure_app_collection(self, app_id):
            calls.append(("vector", app_id))
            return app_id

    state = _state(vector=VectorClient(), database=object(), ready=True)

    body = service.initialize_app_database(state, "tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"app_id": "tenant_a", "initialized": True}
    assert calls == [("vector", "tenant_a")]


def test_app_database_status_uses_vector_collection(monkeypatch):
    class VectorClient:
        def app_collection_exists(self, app_id):
            return True

        def get_total_chunks(self, file_ids=None):
            return 0

    state = _state(vector=VectorClient(), database=object(), ready=True)

    body = service.app_database_status(state, "tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"app_id": "tenant_a", "exists": True, "chunk_count": 0, "empty": True}


def test_app_database_delete_allows_non_empty_database(monkeypatch):
    from services.rag.core.api.services import common as common_service

    class Database:
        def purge_app(self, app_id):
            return 0

    class VectorClient:
        def app_collection_exists(self, app_id):
            return True

        def drop_app_collection(self, app_id):
            return True

    state = _state(vector=VectorClient(), database=Database(), ready=True)
    monkeypatch.setattr(common_service, "scoped_vector", lambda state, principal: type("ScopedVector", (), {"get_total_chunks": lambda self, file_ids=None: 2})())

    body = service.delete_app_database(state, "tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"app_id": "tenant_a", "deleted": True}


def test_stateless_apps_are_listed_but_cannot_be_created_or_deleted():
    credentials = [AppCredential(app_id="tenant_a", api_key="dummy-key")]
    state = _state()
    state.config = SimpleNamespace(auth=SimpleNamespace(apps=credentials))
    principal = Principal(type="admin", app_id="admin")
    assert service.list_apps(state, principal) == {"apps": [{"app_id": "tenant_a", "api_key": "dummy-key"}]}
    with pytest.raises(HTTPException) as error:
        service.create_app(state, AppCreateRequest(app_id="tenant_b"), principal)
    assert error.value.status_code == 503
    with pytest.raises(HTTPException) as error:
        service.delete_app(state, "tenant_a", principal)
    assert error.value.status_code == 503
    assert state.config.auth.apps == credentials


def test_stateless_collection_can_be_deleted_without_metadata_purge():
    class Vector:
        def __init__(self):
            self.exists = True

        def app_collection_exists(self, app_id):
            return self.exists

        def get_total_chunks(self, file_ids):
            return 3

        def drop_app_collection(self, app_id):
            self.exists = False
            return True

    state = _state(vector=Vector())
    assert service.delete_app_database(state, "tenant_a", Principal(type="admin", app_id="admin")) == {
        "app_id": "tenant_a", "deleted": True,
    }
    assert state.vector_client.exists is False
