import hashlib
import hmac
import json
import time
from dataclasses import replace

import pytest

from rag.api.runtime import runtime
from rag.api.schemas import AppCreateRequest
from rag.api.services import apps as service
from rag.auth import Principal
from rag.database.base import FakeDatabase


pytestmark = pytest.mark.unit


def test_app_registry_creates_persistent_credentials_and_authenticates(tmp_path):
    from rag.auth import AppRegistry, authenticate_client_signature
    from rag.schema import AdminAuthConfig, AuthConfig

    path = tmp_path / "apps.json"
    registry = AppRegistry(path)
    credential = registry.create_app("tenant_a")

    reloaded = AppRegistry(path)
    assert reloaded.get_app("tenant_a").access_key == credential.access_key
    assert reloaded.get_app("tenant_a").secret_key == credential.secret_key

    config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(path),
    )
    body = json.dumps({"query": "hello", "mode": "sparse"}, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    body_sha256 = hashlib.sha256(body).hexdigest()
    string_to_sign = "\n".join(["POST", "/api/open/rag/search", timestamp, body_sha256, "tenant_a"])
    signature = hmac.new(credential.secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    class Request:
        method = "POST"

        class url:
            path = "/api/open/rag/search"

        headers = {
            "x-app-id": "tenant_a",
            "x-access-key": credential.access_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
        }

    principal = authenticate_client_signature(config, Request(), body)

    assert principal.type == "app"
    assert principal.app_id == "tenant_a"


def _set_application(monkeypatch, *, database=None, store=None, sparse=None, ready=True):
    config = replace(runtime.application.config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = ready
            self.database = database or FakeDatabase()
            self.store = store
            self.sparse = sparse

    application = Application()
    monkeypatch.setattr(runtime, "application", application)
    return application


def test_create_app_service_generates_credentials_and_lists_apps(monkeypatch):
    _set_application(monkeypatch)

    body = service.create_app(AppCreateRequest(app_id="tenant_a"), Principal(type="admin", app_id="admin"))

    assert body["app_id"] == "tenant_a"
    assert body["access_key"]
    assert body["secret_key"]

    apps = service.list_apps(Principal(type="admin", app_id="admin"))["apps"]
    assert {item["app_id"] for item in apps} == {"tenant_a"}
    assert all(item["secret_key"] for item in apps)


def test_create_app_service_returns_duplicate_error(monkeypatch):
    from fastapi import HTTPException

    database = FakeDatabase()
    database.create_app("tenant_a")
    _set_application(monkeypatch, database=database)

    with pytest.raises(HTTPException) as exc:
        service.create_app(AppCreateRequest(app_id="tenant_a"), Principal(type="admin", app_id="admin"))

    assert exc.value.status_code == 400
    assert exc.value.detail == "app_id already exists"


def test_delete_app_service_removes_credentials_and_purges_app(monkeypatch):
    class Database(FakeDatabase):
        def __init__(self):
            super().__init__()
            self.purged = []

        def purge_app(self, app_id):
            self.purged.append(app_id)
            return super().purge_app(app_id)

    database = Database()
    database.create_app("tenant_a")
    _set_application(monkeypatch, database=database)

    body = service.delete_app("tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"deleted": True}
    assert database.purged == ["tenant_a"]
    assert database.get_app("tenant_a") is None


def test_app_database_status_and_empty_delete(monkeypatch):
    class Store:
        def __init__(self):
            self.exists = True

        def app_collection_exists(self, app_id):
            return self.exists

        def drop_app_collection(self, app_id):
            self.exists = False
            return True

        def get_total_chunks(self, file_ids=None):
            return 0

    class Database:
        ready = True

        def __init__(self):
            self.purged = []

        def purge_app(self, app_id):
            self.purged.append(app_id)

    store = Store()
    database = Database()
    _set_application(monkeypatch, database=database, store=store, ready=True)

    status = service.app_database_status("tenant_a", Principal(type="admin", app_id="admin"))
    deleted = service.delete_app_database("tenant_a", Principal(type="admin", app_id="admin"))

    assert status == {"app_id": "tenant_a", "exists": True, "chunk_count": 0, "empty": True}
    assert deleted == {"app_id": "tenant_a", "deleted": True}
    assert database.purged == ["tenant_a"]


def test_app_database_initialize_creates_sparse_collection(monkeypatch):
    calls = []

    class Store:
        def ensure_app_collection(self, app_id):
            calls.append(("store", app_id))
            return app_id

    class Sparse:
        def ensure_app_collection(self, app_id):
            calls.append(("sparse", app_id))
            return app_id

    _set_application(monkeypatch, store=Store(), sparse=Sparse(), ready=True)

    body = service.initialize_app_database("tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"app_id": "tenant_a", "initialized": True}
    assert calls == [("store", "tenant_a"), ("sparse", "tenant_a")]


def test_app_database_status_requires_sparse_collection_when_available(monkeypatch):
    class Store:
        def app_collection_exists(self, app_id):
            return True

        def get_total_chunks(self, file_ids=None):
            return 0

    class Sparse:
        def app_collection_exists(self, app_id):
            return False

    _set_application(monkeypatch, store=Store(), sparse=Sparse(), ready=True)

    body = service.app_database_status("tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"app_id": "tenant_a", "exists": False, "chunk_count": 0, "empty": True}


def test_app_database_delete_allows_non_empty_database(monkeypatch):
    from rag.api.services import common as common_service

    class Store:
        def app_collection_exists(self, app_id):
            return True

        def drop_app_collection(self, app_id):
            return True

    class Database:
        ready = True

        def __init__(self):
            self.purged = []

        def purge_app(self, app_id):
            self.purged.append(app_id)

    database = Database()
    _set_application(monkeypatch, database=database, store=Store(), ready=True)
    monkeypatch.setattr(common_service, "scoped_store", lambda principal: type("ScopedStore", (), {"get_total_chunks": lambda self, file_ids=None: 2})())

    body = service.delete_app_database("tenant_a", Principal(type="admin", app_id="admin"))

    assert body == {"app_id": "tenant_a", "deleted": True}
    assert database.purged == ["tenant_a"]
