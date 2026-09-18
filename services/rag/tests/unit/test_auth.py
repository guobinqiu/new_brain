import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.rag.core.api.services import auth as service
from services.rag.core.auth import AppCredential, Principal, authenticate_password, issue_token, verify_token
from shared.config import AdminAuthConfig, AuthConfig, DatabaseConfig


pytestmark = pytest.mark.unit


def _request(database=None, db_client=None):
    auth = AuthConfig(
        admin=AdminAuthConfig(username="admin", password=""),
        apps=[AppCredential("tenant_a", "key-a"), AppCredential("tenant_b", "key-b")],
    )
    state = SimpleNamespace(config=SimpleNamespace(database=database, auth=auth), db_client=db_client)
    return SimpleNamespace(app=SimpleNamespace(state=state))


@pytest.mark.parametrize("app_id, key", [("tenant_a", "key-a"), ("tenant_b", "key-b")])
def test_core_mode_authenticates_each_configured_tenant(app_id, key):
    principal = asyncio.run(service.require_api_key(_request(), f"Bearer {key}"))
    assert principal == Principal(type="app", app_id=app_id)


def test_database_mode_uses_database_identity():
    class Database:
        def get_app_by_api_key(self, key):
            assert key == "key-a"
            return AppCredential("database_tenant", key)

    request = _request(DatabaseConfig("postgres", "postgresql://db/test"), Database())
    assert asyncio.run(service.require_api_key(request, "Bearer key-a")) == Principal("app", "database_tenant")


def test_database_unavailable_returns_503_without_using_configured_apps():
    from psycopg import OperationalError

    class Database:
        def get_app_by_api_key(self, key):
            raise OperationalError("database unavailable")

    request = _request(DatabaseConfig("postgres", "postgresql://db/test"), Database())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.require_api_key(request, "Bearer key-a"))
    assert exc.value.status_code == 503


def test_database_unknown_key_returns_401_without_using_configured_apps():
    class Database:
        def get_app_by_api_key(self, key):
            return None

    request = _request(DatabaseConfig("postgres", "postgresql://db/test"), Database())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.require_api_key(request, "Bearer key-a"))
    assert exc.value.status_code == 401


def test_admin_login_and_jwt_use_configured_password():
    config = AuthConfig(admin=AdminAuthConfig(username="admin", password="dummy-password"))
    principal = authenticate_password(config, "admin", "dummy-password")
    assert verify_token(config, issue_token(config, principal)) == Principal("admin", "")


def test_core_mode_without_admin_password_disables_admin_login_and_jwt():
    config = AuthConfig(admin=AdminAuthConfig(username="admin", password=""))
    with pytest.raises(HTTPException) as login_error:
        authenticate_password(config, "admin", "")
    assert login_error.value.status_code == 503
    with pytest.raises(HTTPException) as token_error:
        issue_token(config, Principal("admin", ""))
    assert token_error.value.status_code == 503

    enabled = AuthConfig(admin=AdminAuthConfig("admin", "test-password"))
    token = issue_token(enabled, Principal(type="admin", app_id=""))
    with pytest.raises(HTTPException) as verify_error:
        verify_token(config, token)
    assert verify_error.value.status_code == 503
