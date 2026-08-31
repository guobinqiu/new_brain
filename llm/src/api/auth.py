"""API authentication helpers."""

from __future__ import annotations

import hashlib
import hmac
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Literal

from fastapi import HTTPException, Request
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


TIMESTAMP_SKEW_SECONDS = 300


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    access_key: str
    secret_key: str


@dataclass(frozen=True)
class Principal:
    type: Literal["admin", "app"]
    app_id: str


_current_credential: ContextVar[AppCredential | None] = ContextVar("current_credential", default=None)
_auth_pool: AsyncConnectionPool | None = None


async def _get_auth_pool() -> AsyncConnectionPool:
    global _auth_pool
    if _auth_pool is None:
        from llm.src.config import settings

        _auth_pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=settings.db_pool_max,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await _auth_pool.open()
    return _auth_pool


async def close_auth_pool() -> None:
    global _auth_pool
    if _auth_pool is not None:
        await _auth_pool.close()
        _auth_pool = None


async def _get_app(app_id: str) -> AppCredential | None:
    pool = await _get_auth_pool()
    async with pool.connection() as conn:
        row = await (await conn.execute(
            "SELECT app_id, access_key, secret_key FROM apps WHERE app_id = %s",
            (app_id,),
        )).fetchone()
    if row is None:
        return None
    return AppCredential(
        app_id=row["app_id"],
        access_key=row["access_key"],
        secret_key=row["secret_key"],
    )


def get_current_credential() -> AppCredential | None:
    return _current_credential.get()


async def require_aksk(request: Request):
    body = await request.body()
    app_id = request.headers.get("x-app-id", "")
    credential = await _get_app(app_id) if app_id else None
    principal = authenticate_client_signature(request, body, lambda _: credential)
    _current_credential.set(credential)
    return principal


def authenticate_client_signature(
    request: Request,
    body: bytes,
    credential_lookup: Callable[[str], AppCredential | None],
) -> Principal:
    app_id = request.headers.get("x-app-id", "")
    access_key = request.headers.get("x-access-key", "")
    timestamp = request.headers.get("x-timestamp", "")
    signature = request.headers.get("x-signature", "")
    if not all((app_id, access_key, timestamp, signature)):
        raise HTTPException(401, "missing signature headers")
    credential = credential_lookup(app_id)
    if credential is None or access_key != credential.access_key:
        raise HTTPException(401, "invalid access key")
    _validate_timestamp(timestamp)
    expected = sign_request(credential.secret_key, request.method.upper(), request.url.path, timestamp, body, app_id)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "invalid signature")
    return Principal(type="app", app_id=app_id)


def sign_request(secret_key: str, method: str, path: str, timestamp: str, body: bytes, app_id: str) -> str:
    body_sha256 = hashlib.sha256(body).hexdigest()
    string_to_sign = "\n".join([method, path, timestamp, body_sha256, app_id])
    return hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def _validate_timestamp(timestamp: str) -> None:
    try:
        value = int(timestamp)
    except ValueError as exc:
        raise HTTPException(401, "invalid timestamp") from exc
    if abs(int(time.time()) - value) > TIMESTAMP_SKEW_SECONDS:
        raise HTTPException(401, "invalid timestamp")
