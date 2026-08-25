import hashlib
import hmac
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from api.services import common as service
from api.runtime import runtime


pytestmark = pytest.mark.unit


def test_app_registry_creates_persistent_credentials_and_authenticates(monkeypatch, tmp_path):
    from auth import authenticate_client_signature
    from app_registry import AppRegistry
    from schema import AuthConfig, AdminAuthConfig

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
    string_to_sign = "\n".join(["POST", "/api/open/search", timestamp, body_sha256, "tenant_a"])
    signature = hmac.new(credential.secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    class Request:
        method = "POST"

        class url:
            path = "/api/open/search"

        headers = {
            "x-app-id": "tenant_a",
            "x-access-key": credential.access_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
        }

    principal = authenticate_client_signature(config, Request(), body)

    assert principal.type == "app"
    assert principal.app_id == "tenant_a"


def test_create_app_api_generates_credentials(monkeypatch, tmp_path):
    from auth import Principal, issue_token
    from database.base import FakeDatabase
    from schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = False
            self.database = FakeDatabase()

        def start(self):
            pass

        def stop(self):
            pass

    application = Application()
    monkeypatch.setattr(runtime, "application", application)
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/apps",
            json={"app_id": "tenant_a"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["app_id"] == "tenant_a"
    assert body["access_key"]
    assert body["secret_key"]

    list_response = client.get("/api/apps", headers={"Authorization": f"Bearer {token}"})

    assert list_response.status_code == 200
    apps = list_response.json()["apps"]
    assert {item["app_id"] for item in apps} == {"tenant_a"}
    assert all(item["secret_key"] for item in apps)


def test_create_app_api_returns_duplicate_error(monkeypatch, tmp_path):
    from auth import Principal, issue_token
    from database.base import FakeDatabase
    from schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = False
            self.database = FakeDatabase()

        def start(self):
            pass

        def stop(self):
            pass

    application = Application()
    application.database.create_app("tenant_a")
    monkeypatch.setattr(runtime, "application", application)
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.post(
            "/api/apps",
            json={"app_id": "tenant_a"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "app_id already exists"


def test_delete_app_api_removes_credentials(monkeypatch, tmp_path):
    from auth import Principal, issue_token
    from database.base import FakeDatabase
    from schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

    class Database(FakeDatabase):
        def __init__(self):
            super().__init__()
            self.purged = []

        def purge_app(self, app_id):
            self.purged.append(app_id)
            return super().purge_app(app_id)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = False
            self.database = Database()

        def start(self):
            pass

        def stop(self):
            pass

    application = Application()
    application.database.create_app("tenant_a")
    monkeypatch.setattr(runtime, "application", application)
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.delete("/api/apps/tenant_a", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert application.database.purged == ["tenant_a"]


def test_app_database_status_and_empty_delete(monkeypatch, tmp_path):
    from auth import Principal, issue_token
    from schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

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
        def __init__(self):
            self.purged = []

        def purge_app(self, app_id):
            self.purged.append(app_id)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.store = Store()
            self.database = Database()

        def start(self):
            pass

        def stop(self):
            pass

    application = Application()
    monkeypatch.setattr(runtime, "application", application)
    monkeypatch.setattr(runtime, "startup_in_background", False)
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        status = client.get("/api/apps/tenant_a/database", headers={"Authorization": f"Bearer {token}"})
        deleted = client.delete("/api/apps/tenant_a/database", headers={"Authorization": f"Bearer {token}"})

    assert status.status_code == 200
    assert status.json() == {"app_id": "tenant_a", "exists": True, "chunk_count": 0, "empty": True}
    assert deleted.status_code == 200
    assert deleted.json() == {"app_id": "tenant_a", "deleted": True}
    assert application.database.purged == ["tenant_a"]


def test_app_database_delete_allows_non_empty_database(monkeypatch, tmp_path):
    from auth import Principal, issue_token
    from schema import AuthConfig, AdminAuthConfig
    import main

    auth_config = AuthConfig(
        admin=AdminAuthConfig(username="admin", password="admin123"),
        registry_file=str(tmp_path / "apps.json"),
    )
    config = replace(runtime.application.config, auth=auth_config)

    class Store:
        def app_collection_exists(self, app_id):
            return True

        def drop_app_collection(self, app_id):
            return True

    class Database:
        def __init__(self):
            self.purged = []

        def purge_app(self, app_id):
            self.purged.append(app_id)

    class Application:
        def __init__(self):
            self.config = config
            self.ready = True
            self.store = Store()
            self.database = Database()

        def start(self):
            pass

        def stop(self):
            pass

    application = Application()
    monkeypatch.setattr(runtime, "application", application)
    monkeypatch.setattr(runtime, "startup_in_background", False)
    monkeypatch.setattr(service, "scoped_store", lambda principal: type("ScopedStore", (), {"get_total_chunks": lambda self, file_ids=None: 2})())
    token = issue_token(auth_config, Principal(type="admin", app_id="admin"))

    with TestClient(main.app) as client:
        response = client.delete("/api/apps/tenant_a/database", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"app_id": "tenant_a", "deleted": True}
    assert application.database.purged == ["tenant_a"]
