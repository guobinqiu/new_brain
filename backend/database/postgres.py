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
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_app_files_app_file UNIQUE (app_id, file_id)
)
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_app_files_listing
    ON app_files (app_id, created_at DESC, id DESC)
    WHERE deleted_at IS NULL
"""

UPSERT_FILE_SQL = """
INSERT INTO app_files (app_id, file_id, filename, s3_url, size, chunk_count)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (app_id, file_id) DO UPDATE SET
    filename = EXCLUDED.filename,
    s3_url = EXCLUDED.s3_url,
    size = EXCLUDED.size,
    chunk_count = EXCLUDED.chunk_count,
    deleted_at = NULL,
    updated_at = now()
"""

SOFT_DELETE_SQL = """
UPDATE app_files SET deleted_at = now(), updated_at = now()
WHERE app_id = %s AND file_id = %s AND deleted_at IS NULL
"""

PURGE_APP_SQL = "DELETE FROM app_files WHERE app_id = %s"

_LIST_SELECT = "id, app_id, file_id, filename, s3_url, size, chunk_count, created_at"

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

PREV_PAGE_SQL = f"""
SELECT {_LIST_SELECT} FROM app_files
WHERE app_id = %s AND deleted_at IS NULL AND id > %s
ORDER BY created_at ASC, id ASC
LIMIT %s
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
            conn.execute(CREATE_INDEX_SQL)
        self.ready = True

    def stop(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
        self.ready = False

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

    def list_files(self, app_id, limit=50, cursor=None, direction="next") -> FilePage:
        if limit <= 0:
            raise ValueError("limit must be greater than 0")
        limit = min(limit, 200)
        cursor_id = int(cursor) if cursor is not None else None
        if direction == "prev":
            if cursor_id is None:
                raise ValueError("cursor is required for prev direction")
            with self._pool.connection() as conn:
                raw = conn.execute(PREV_PAGE_SQL, (app_id, cursor_id, limit + 1)).fetchall()
                rows = list(reversed(raw))
                prev_cursor = str(rows[0]["id"]) if len(raw) > limit else None
                has_more = False
                next_cursor = None
                if rows:
                    last_id = rows[-1]["id"]
                    probe = conn.execute(
                        "SELECT 1 FROM app_files WHERE app_id = %s AND deleted_at IS NULL AND id < %s LIMIT 1",
                        (app_id, last_id),
                    ).fetchone()
                    has_more = probe is not None
                    next_cursor = str(last_id) if has_more else None
        else:
            if cursor_id is None:
                with self._pool.connection() as conn:
                    rows = conn.execute(FIRST_PAGE_SQL, (app_id, limit + 1)).fetchall()
            else:
                with self._pool.connection() as conn:
                    rows = conn.execute(NEXT_PAGE_SQL, (app_id, cursor_id, limit + 1)).fetchall()
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            prev_cursor = str(page_rows[0]["id"]) if cursor_id is not None and page_rows else None
            next_cursor = str(page_rows[-1]["id"]) if has_more else None
        page_rows = rows[:limit]
        return FilePage(
            files=[_record(row) for row in page_rows],
            prev_cursor=prev_cursor,
            next_cursor=next_cursor,
            has_more=has_more,
        )


def _record(row: dict) -> FileRecord:
    created_at = row["created_at"]
    return FileRecord(
        id=row["file_id"],
        filename=row["filename"],
        chunk_count=row["chunk_count"],
        created_at=created_at.isoformat() if created_at else None,
        s3_url=row["s3_url"],
        size=row["size"],
    )