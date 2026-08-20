from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from database.base import FilePage, FileRecord

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_files (
    id          BIGSERIAL PRIMARY KEY,
    app_id      VARCHAR(64)   NOT NULL,
    file_id     UUID          NOT NULL,
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

ALTER_TABLE_SQL = """
ALTER TABLE app_files
    ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'success',
    ADD COLUMN IF NOT EXISTS error TEXT,
    ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ
"""

CREATE_INDEX_SQL = """
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

class PostgresDatabase:
    def __init__(self, url: str, pool_size: int = 5):
        self.url = url
        self.pool_size = pool_size
        self._pool: ConnectionPool | None = None
        self.ready = False

    def start(self) -> None:
        self._pool = ConnectionPool(
            self.url,
            min_size=1,
            max_size=self.pool_size,
            open=False,
            kwargs={"row_factory": dict_row},
        )
        self._pool.open()
        self._pool.wait()
        with self._pool.connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(ALTER_TABLE_SQL)
            conn.execute(CREATE_INDEX_SQL)
        self.ready = True

    def stop(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
        self.ready = False

    def create_file(self, app_id, file_id, filename, s3_url, *, size=None) -> None:
        with self._pool.connection() as conn:
            conn.execute(CREATE_FILE_SQL, (app_id, file_id, filename, s3_url, size))

    def mark_file_indexing(self, app_id, file_id) -> None:
        with self._pool.connection() as conn:
            conn.execute(MARK_INDEXING_SQL, (app_id, file_id))

    def mark_file_failed(self, app_id, file_id, error) -> None:
        with self._pool.connection() as conn:
            conn.execute(MARK_FAILED_SQL, (error, app_id, file_id))

    def upsert_file(self, app_id, file_id, filename, s3_url, *, size=None, chunk_count=0) -> None:
        with self._pool.connection() as conn:
            conn.execute(UPSERT_FILE_SQL, (app_id, file_id, filename, s3_url, size, chunk_count))

    def soft_delete_file(self, app_id, file_id) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(SOFT_DELETE_SQL, (app_id, file_id))
            return cur.rowcount

    def purge_app(self, app_id) -> int:
        with self._pool.connection() as conn:
            cur = conn.execute(PURGE_APP_SQL, (app_id,))
            return cur.rowcount

    def list_files(self, app_id, limit=50, cursor=None) -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        cursor_id = int(cursor) if cursor is not None else None
        if cursor_id is None:
            with self._pool.connection() as conn:
                rows = conn.execute(FIRST_PAGE_SQL, (app_id, limit + 1)).fetchall()
        else:
            with self._pool.connection() as conn:
                rows = conn.execute(NEXT_PAGE_SQL, (app_id, cursor_id, limit + 1)).fetchall()
        with self._pool.connection() as conn:
            total_row = conn.execute(COUNT_FILES_SQL, (app_id,)).fetchone()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = str(page_rows[-1]["id"]) if has_more else None
        return FilePage(
            files=[_record(row) for row in page_rows],
            next_cursor=next_cursor,
            has_more=has_more,
            total=total_row["total"] if total_row else 0,
        )


def _record(row: dict) -> FileRecord:
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
