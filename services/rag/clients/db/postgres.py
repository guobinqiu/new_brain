from __future__ import annotations

import secrets

from psycopg import errors
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from services.rag.clients.db.base import DbClient, FilePage, FileRecord
from services.rag.core.auth import AppCredential, validate_app_id
from services.rag.core.presign import load_presign_template


CREATE_APPS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS apps (
    app_id      VARCHAR(64)   PRIMARY KEY,
    api_key     VARCHAR(128)  NOT NULL UNIQUE,
    presign_config TEXT,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
)
"""

CREATE_FILES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_files (
    id          BIGSERIAL PRIMARY KEY,
    app_id      VARCHAR(64)   NOT NULL,
    file_id     VARCHAR(128)  NOT NULL,
    filename    VARCHAR(1024) NOT NULL,
    s3_url      TEXT          NOT NULL,
    size        BIGINT,
    chunk_count INTEGER       NOT NULL DEFAULT 0,
    status      VARCHAR(16)   NOT NULL DEFAULT 'success',
    error       TEXT,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    indexed_at  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_app_files_app_file UNIQUE (app_id, file_id),
    CONSTRAINT ck_app_files_status CHECK (status IN ('queued', 'indexing', 'success', 'failed'))
)
"""

CREATE_FILES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_app_files_listing
    ON app_files (app_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL
"""

CREATE_FILE_SQL = """
INSERT INTO app_files (app_id, file_id, filename, s3_url, size, chunk_count, status, error, indexed_at)
VALUES (%s, %s, %s, %s, %s, 0, 'queued', NULL, NULL)
ON CONFLICT (app_id, file_id) DO UPDATE SET
    filename = EXCLUDED.filename,
    s3_url = EXCLUDED.s3_url,
    size = EXCLUDED.size,
    chunk_count = 0,
    status = 'queued',
    error = NULL,
    indexed_at = NULL,
    deleted_at = NULL,
    updated_at = now()
"""

MARK_INDEXING_SQL = """
UPDATE app_files
SET status = 'indexing', error = NULL, updated_at = now()
WHERE app_id = %s AND file_id = %s AND deleted_at IS NULL
"""

MARK_FAILED_SQL = """
UPDATE app_files
SET status = 'failed', error = %s, indexed_at = NULL, updated_at = now()
WHERE app_id = %s AND file_id = %s AND deleted_at IS NULL
"""

MARK_INTERRUPTED_INDEXING_FAILED_SQL = """
UPDATE app_files
SET status = 'failed', error = %s, indexed_at = NULL, updated_at = now()
WHERE status = 'indexing' AND deleted_at IS NULL
"""

UPSERT_FILE_SQL = """
INSERT INTO app_files (app_id, file_id, filename, s3_url, size, chunk_count, status, error, indexed_at)
VALUES (%s, %s, %s, %s, %s, %s, 'success', NULL, now())
ON CONFLICT (app_id, file_id) DO UPDATE SET
    filename = EXCLUDED.filename,
    s3_url = EXCLUDED.s3_url,
    size = EXCLUDED.size,
    chunk_count = EXCLUDED.chunk_count,
    status = 'success',
    error = NULL,
    indexed_at = now(),
    deleted_at = NULL,
    updated_at = now()
"""

SOFT_DELETE_SQL = """
UPDATE app_files SET deleted_at = now(), updated_at = now()
WHERE app_id = %s AND file_id = %s AND deleted_at IS NULL
"""

PURGE_APP_SQL = "DELETE FROM app_files WHERE app_id = %s"

_LIST_SELECT = "id, app_id, file_id, filename, s3_url, size, chunk_count, status, error, created_at, indexed_at"

FIRST_PAGE_SQL = f"""
SELECT {_LIST_SELECT} FROM app_files
WHERE app_id = %s AND deleted_at IS NULL
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

NEXT_PAGE_SQL = f"""
SELECT {_LIST_SELECT} FROM app_files
WHERE app_id = %s AND deleted_at IS NULL AND id < %s
ORDER BY created_at DESC, id DESC
LIMIT %s
"""

COUNT_FILES_SQL = """
SELECT COUNT(*) AS total FROM app_files
WHERE app_id = %s AND deleted_at IS NULL
"""

CREATE_APP_SQL = "INSERT INTO apps (app_id, api_key, presign_config) VALUES (%s, %s, %s)"
GET_APP_SQL = "SELECT app_id, api_key FROM apps WHERE app_id = %s"
GET_APP_BY_API_KEY_SQL = "SELECT app_id, api_key FROM apps WHERE api_key = %s"
LIST_APPS_SQL = "SELECT app_id, api_key FROM apps ORDER BY app_id ASC"
DELETE_APP_SQL = "DELETE FROM apps WHERE app_id = %s"


class PgClient(DbClient):
    def __init__(self, url: str, pool_size: int = 5):
        self.url = url
        self.pool_size = pool_size
        self.ready = True
        self._pool: ConnectionPool | None = None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
        self.ready = False

    def initialize(self) -> None:
        self._get_pool()

    def ping(self) -> bool:
        try:
            with self._get_pool().connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def create_file(self, app_id, file_id, filename, s3_url, *, size=None) -> None:
        with self._get_pool().connection() as conn:
            conn.execute(CREATE_FILE_SQL, (app_id, file_id, filename, s3_url, size))

    def get_file(self, app_id: str, file_id: str) -> FileRecord | None:
        with self._get_pool().connection() as conn:
            row = conn.execute(
                f"SELECT {_LIST_SELECT} FROM app_files WHERE app_id = %s AND file_id = %s AND deleted_at IS NULL",
                (app_id, file_id),
            ).fetchone()
        return _file_record(row) if row else None

    def claim_file_retry(self, app_id: str, file_id: str) -> bool:
        with self._get_pool().connection() as conn:
            result = conn.execute(
                "UPDATE app_files SET status = 'indexing', error = NULL, updated_at = now() "
                "WHERE app_id = %s AND file_id = %s AND status = 'failed' AND deleted_at IS NULL",
                (app_id, file_id),
            )
            return result.rowcount > 0

    def get_presign_config(self, app_id: str) -> str | None:
        with self._get_pool().connection() as conn:
            row = conn.execute("SELECT presign_config FROM apps WHERE app_id = %s", (app_id,)).fetchone()
        return (row["presign_config"] or "") if row else None

    def set_presign_config(self, app_id: str, template: str) -> bool:
        with self._get_pool().connection() as conn:
            result = conn.execute(
                "UPDATE apps SET presign_config = %s, updated_at = now() WHERE app_id = %s",
                (template, app_id),
            )
            return result.rowcount > 0

    def mark_file_indexing(self, app_id, file_id) -> None:
        with self._get_pool().connection() as conn:
            conn.execute(MARK_INDEXING_SQL, (app_id, file_id))

    def mark_file_failed(self, app_id, file_id, error) -> None:
        with self._get_pool().connection() as conn:
            conn.execute(MARK_FAILED_SQL, (error, app_id, file_id))

    def mark_interrupted_indexing_failed(self) -> int:
        with self._get_pool().connection() as conn:
            cur = conn.execute(MARK_INTERRUPTED_INDEXING_FAILED_SQL, ('{"error":"index interrupted by service restart","retryable":false,"traceId":null}',))
            return cur.rowcount

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None:
        with self._get_pool().connection() as conn:
            conn.execute(UPSERT_FILE_SQL, (app_id, file_id, filename, s3_url, size, chunk_count))

    def soft_delete_file(self, app_id, file_id) -> int:
        with self._get_pool().connection() as conn:
            cur = conn.execute(SOFT_DELETE_SQL, (app_id, file_id))
            return cur.rowcount

    def purge_app(self, app_id) -> int:
        with self._get_pool().connection() as conn:
            cur = conn.execute(PURGE_APP_SQL, (app_id,))
            return cur.rowcount

    def list_files(self, app_id, limit=50, cursor=None) -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        cursor_id = int(cursor) if cursor is not None else None
        with self._get_pool().connection() as conn:
            if cursor_id is None:
                rows = conn.execute(FIRST_PAGE_SQL, (app_id, limit + 1)).fetchall()
            else:
                rows = conn.execute(NEXT_PAGE_SQL, (app_id, cursor_id, limit + 1)).fetchall()
            total_row = conn.execute(COUNT_FILES_SQL, (app_id,)).fetchone()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = str(page_rows[-1]["id"]) if has_more else None
        return FilePage(
            files=[_file_record(row) for row in page_rows],
            next_cursor=next_cursor,
            has_more=has_more,
            total=total_row["total"] if total_row else 0,
        )

    def create_app(self, app_id: str) -> AppCredential:
        validate_app_id(app_id)
        credential = AppCredential(app_id=app_id, api_key=f"bk_{secrets.token_urlsafe(32)}")
        try:
            with self._get_pool().connection() as conn:
                conn.execute(CREATE_APP_SQL, (credential.app_id, credential.api_key, load_presign_template(credential.api_key)))
        except errors.UniqueViolation as exc:
            raise ValueError("app_id already exists") from exc
        return credential

    def get_app(self, app_id: str) -> AppCredential | None:
        validate_app_id(app_id)
        with self._get_pool().connection() as conn:
            row = conn.execute(GET_APP_SQL, (app_id,)).fetchone()
        return _app_credential(row) if row else None

    def get_app_by_api_key(self, api_key: str) -> AppCredential | None:
        with self._get_pool().connection() as conn:
            row = conn.execute(GET_APP_BY_API_KEY_SQL, (api_key,)).fetchone()
        return _app_credential(row) if row else None

    def list_apps(self) -> list[AppCredential]:
        with self._get_pool().connection() as conn:
            rows = conn.execute(LIST_APPS_SQL).fetchall()
        return [_app_credential(row) for row in rows]

    def delete_app(self, app_id: str) -> bool:
        validate_app_id(app_id)
        with self._get_pool().connection() as conn:
            cur = conn.execute(DELETE_APP_SQL, (app_id,))
            return cur.rowcount > 0

    def _get_pool(self) -> ConnectionPool:
        if self._pool is None:
            pool = ConnectionPool(
                self.url,
                min_size=1,
                max_size=self.pool_size,
                open=False,
                kwargs={"row_factory": dict_row},
            )
            try:
                pool.open()
                pool.wait()
                self._migrate(pool)
            except Exception:
                pool.close()
                raise
            self._pool = pool
        return self._pool

    def _migrate(self, pool: ConnectionPool) -> None:
        with pool.connection() as conn:
            conn.execute(CREATE_APPS_TABLE_SQL)
            conn.execute("ALTER TABLE apps ADD COLUMN IF NOT EXISTS presign_config TEXT")
            conn.execute(CREATE_FILES_TABLE_SQL)
            conn.execute(CREATE_FILES_INDEX_SQL)


def _file_record(row: dict) -> FileRecord:
    created_at = row["created_at"]
    indexed_at = row["indexed_at"]
    return FileRecord(
        id=row["file_id"],
        filename=row["filename"],
        chunk_count=row["chunk_count"],
        created_at=created_at.isoformat() if created_at else None,
        indexed_at=indexed_at.isoformat() if indexed_at else None,
        s3_url=row["s3_url"],
        size=row["size"],
        status=row["status"],
        error=row["error"],
    )


def _app_credential(row: dict) -> AppCredential:
    return AppCredential(app_id=row["app_id"], api_key=row["api_key"])
