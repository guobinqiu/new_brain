import pytest

from database.postgres import PostgresDatabase, FIRST_PAGE_SQL, NEXT_PAGE_SQL, PREV_PAGE_SQL


pytestmark = pytest.mark.unit


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self, page_rows, probe_rows=None):
        self._page_rows = page_rows
        self._probe_rows = probe_rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if sql.startswith("SELECT 1"):
            return FakeCursor(self._probe_rows or [])
        return FakeCursor(self._page_rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePool:
    def __init__(self, page_rows, probe_rows=None):
        self._page_rows = page_rows
        self._probe_rows = probe_rows
        self.conn = None

    def connection(self):
        self.conn = FakeConn(self._page_rows, self._probe_rows)
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
        "created_at": __import__("datetime").datetime(2026, 8, 20, tzinfo=__import__("datetime").timezone.utc),
    }


def _db(rows, probe_rows=None):
    db = PostgresDatabase(url="postgresql://x")
    db._pool = FakePool(rows, probe_rows)
    db.ready = True
    return db


def test_first_page_uses_first_page_sql():
    db = _db([_row(4, "f4"), _row(3, "f3"), _row(2, "f2")])  # limit=2 → 多取1判断 has_more
    page = db.list_files("app1", limit=2)
    assert [r.id for r in page.files] == ["f4", "f3"]
    assert page.has_more is True
    sql, params = db._pool.conn.executed[0]
    assert sql == FIRST_PAGE_SQL
    assert params == ("app1", 3)


def test_next_page_uses_next_page_sql():
    db = _db([_row(2, "f2"), _row(1, "f1")])
    page = db.list_files("app1", limit=2, cursor="3", direction="next")
    assert [r.id for r in page.files] == ["f2", "f1"]
    assert page.has_more is False
    sql, params = db._pool.conn.executed[0]
    assert sql == NEXT_PAGE_SQL
    assert params == ("app1", 3, 3)


def test_prev_page_reverses_rows():
    # prev 查询 ASC 取回 limit+1 条 raw=[2,3,4]：raw[limit]=4 是探针（表示还有更新记录），
    # 探针行不进本页；本页 = raw[:limit]=[2,3] 反转 → [f3,f2]；
    # prev_cursor 指向本页第一条（最新一条）f3 → "3"，而非探针 id。
    db = _db([_row(2, "f2"), _row(3, "f3"), _row(4, "f4")], probe_rows=[_row(1, "f1")])
    page = db.list_files("app1", limit=2, cursor="1", direction="prev")
    assert [r.id for r in page.files] == ["f3", "f2"]
    assert page.prev_cursor == "3"
    assert page.has_more is True  # 探测到 id < 2 的记录（更旧方向）
    assert page.next_cursor == "2"
    sql, params = db._pool.conn.executed[0]
    assert sql == PREV_PAGE_SQL
    assert params == ("app1", 1, 3)


def test_prev_at_newest_boundary_has_no_prev_cursor():
    db = _db([_row(3, "f3"), _row(4, "f4")], probe_rows=[])  # 已到最新边界，且无更旧记录
    page = db.list_files("app1", limit=2, cursor="1", direction="prev")
    assert [r.id for r in page.files] == ["f4", "f3"]
    assert page.prev_cursor is None
    assert page.has_more is False


def test_prev_requires_cursor():
    db = _db([])
    try:
        db.list_files("app1", direction="prev")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_record_maps_file_id_and_iso_created_at():
    db = _db([_row(1, "f1")])
    page = db.list_files("app1")
    record = page.files[0]
    assert record.id == "f1"
    assert record.created_at == "2026-08-20T00:00:00+00:00"
