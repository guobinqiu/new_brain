import pytest

from database.postgres import PostgresDatabase, FIRST_PAGE_SQL, NEXT_PAGE_SQL, COUNT_FILES_SQL


pytestmark = pytest.mark.unit


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, page_rows, probe_rows=None, total=0):
        self._page_rows = page_rows
        self._probe_rows = probe_rows
        self._total = total
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql == COUNT_FILES_SQL:
            return FakeCursor([{"total": self._total}])
        if sql.startswith("SELECT 1"):
            return FakeCursor(self._probe_rows or [])
        return FakeCursor(self._page_rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePool:
    def __init__(self, page_rows, probe_rows=None, total=0):
        self._page_rows = page_rows
        self._probe_rows = probe_rows
        self._total = total
        self.conn = None
        self.connections = []

    def connection(self):
        self.conn = FakeConn(self._page_rows, self._probe_rows, self._total)
        self.connections.append(self.conn)
        return self.conn


def _row(i, file_id):
    return {
        "id": i,
        "app_id": "app1",
        "file_id": file_id,
        "filename": f"{file_id}.txt",
        "s3_url": f"s3://b/{file_id}.txt",
        "size": 10,
        "chunk_count": 1,
        "status": "success",
        "error": None,
        "created_at": __import__("datetime").datetime(2026, 8, 20, tzinfo=__import__("datetime").timezone.utc),
        "indexed_at": __import__("datetime").datetime(2026, 8, 20, tzinfo=__import__("datetime").timezone.utc),
    }


def _db(rows, probe_rows=None, total=0):
    db = PostgresDatabase(url="postgresql://x")
    db._pool = FakePool(rows, probe_rows, total)
    db.ready = True
    return db


def test_first_page_uses_first_page_sql():
    db = _db([_row(4, "f4"), _row(3, "f3"), _row(2, "f2")], total=4)  # limit=2 → 多取1判断 has_more
    page = db.list_files("app1", limit=2)
    assert [r.id for r in page.files] == ["f4", "f3"]
    assert page.has_more is True
    assert page.total == 4
    sql, params = db._pool.connections[0].executed[0]
    assert sql == FIRST_PAGE_SQL
    assert params == ("app1", 3)
    count_sql, count_params = db._pool.connections[1].executed[0]
    assert count_sql == COUNT_FILES_SQL
    assert count_params == ("app1",)


def test_next_page_uses_next_page_sql():
    db = _db([_row(2, "f2"), _row(1, "f1")], total=4)
    page = db.list_files("app1", limit=2, cursor="3")
    assert [r.id for r in page.files] == ["f2", "f1"]
    assert page.has_more is False
    assert page.total == 4
    sql, params = db._pool.connections[0].executed[0]
    assert sql == NEXT_PAGE_SQL
    assert params == ("app1", 3, 3)


def test_record_maps_file_id_and_iso_created_at():
    db = _db([_row(1, "f1")])
    page = db.list_files("app1")
    record = page.files[0]
    assert record.id == "f1"
    assert record.created_at == "2026-08-20T00:00:00+00:00"
    assert record.indexed_at == "2026-08-20T00:00:00+00:00"
    assert record.status == "success"
    assert record.error is None
