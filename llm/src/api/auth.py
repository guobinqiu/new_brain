"""API authentication helpers."""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from auth import AppCredential, authenticate_client_signature
from llm.src.config import settings

_auth_config = object()
_current_credential: ContextVar[AppCredential | None] = ContextVar("current_credential", default=None)
_rag_pool: AsyncConnectionPool | None = None


async def _get_rag_pool() -> AsyncConnectionPool:
    global _rag_pool
    if _rag_pool is None:
        _rag_pool = AsyncConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=settings.db_pool_max,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        await _rag_pool.open()
    return _rag_pool


async def close_auth_pool() -> None:
    global _rag_pool
    if _rag_pool is not None:
        await _rag_pool.close()
        _rag_pool = None


async def _get_app(app_id: str) -> AppCredential | None:
    pool = await _get_rag_pool()
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
    principal = authenticate_client_signature(_auth_config, request, body, lambda _: credential)
    _current_credential.set(credential)
    return principal
