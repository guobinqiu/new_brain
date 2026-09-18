"""API authentication helpers."""

from __future__ import annotations

import hmac
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from fastapi import Header, HTTPException
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    api_key: str


@dataclass(frozen=True)
class Principal:
    type: Literal["admin", "app"]
    app_id: str


_current_credential: ContextVar[AppCredential | None] = ContextVar("current_credential", default=None)
_auth_pool: ConnectionPool | None = None


def close_auth_pool() -> None:
    global _auth_pool
    if _auth_pool is not None:
        _auth_pool.close()
        _auth_pool = None


def get_current_credential() -> AppCredential | None:
    return _current_credential.get()


async def require_api_key(authorization: str | None = Header(None)):
    credential = _get_app_by_api_key(_bearer_token(authorization))
    if credential is None:
        raise HTTPException(401, "invalid api key")
    _current_credential.set(credential)
    return Principal(type="app", app_id=credential.app_id)


def _get_app_by_api_key(api_key: str) -> AppCredential | None:
    from services.llm.src.config import settings

    pool = _get_auth_pool(settings.database_url)
    with pool.connection() as conn:
        credential = conn.execute("SELECT app_id, api_key FROM apps WHERE api_key = %s", (api_key,)).fetchone()
    if credential is None:
        return None
    stored_api_key = credential["api_key"]
    if not hmac.compare_digest(stored_api_key, api_key):
        return None
    return AppCredential(app_id=credential["app_id"], api_key=stored_api_key)


def _get_auth_pool(database_url: str) -> ConnectionPool:
    global _auth_pool
    if _auth_pool is None:
        _auth_pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        _auth_pool.open()
    return _auth_pool


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "missing bearer token")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "missing bearer token")
    return token
