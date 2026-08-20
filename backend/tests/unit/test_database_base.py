import pytest

from database.base import FakeDatabase


pytestmark = pytest.mark.unit


def _seed(db):
    for i, fname in enumerate(["a.txt", "b.txt", "c.txt", "d.txt"]):
        db.upsert_file("app1", f"f{i}", fname, f"s3://b/{fname}", size=10 + i, chunk_count=1)


def test_upsert_and_soft_delete():
    db = FakeDatabase()
    _seed(db)
    assert db.soft_delete_file("app1", "f1") == 1
    assert db.soft_delete_file("app1", "f1") == 0  # 幂等
    page = db.list_files("app1")
    assert [r.id for r in page.files] == ["f3", "f2", "f0"]  # f1 已软删，新→旧
    assert all(r.status == "success" for r in page.files)
    assert page.total == 3


def test_upsert_restores_soft_deleted():
    db = FakeDatabase()
    _seed(db)
    db.soft_delete_file("app1", "f0")
    db.upsert_file("app1", "f0", "a.txt", "s3://b/a.txt", size=99, chunk_count=5)
    page = db.list_files("app1")
    assert any(r.id == "f0" and r.chunk_count == 5 and r.status == "success" for r in page.files)


def test_list_first_page_and_next():
    db = FakeDatabase()
    _seed(db)  # 4 条
    page = db.list_files("app1", limit=2)
    assert [r.id for r in page.files] == ["f3", "f2"]
    assert page.next_cursor is not None
    assert page.has_more is True
    assert page.total == 4

    page2 = db.list_files("app1", limit=2, cursor=page.next_cursor)
    assert [r.id for r in page2.files] == ["f1", "f0"]
    assert page2.has_more is False
    assert page2.next_cursor is None
    assert page2.total == 4


def test_purge_app():
    db = FakeDatabase()
    _seed(db)
    assert db.purge_app("app1") == 4
    assert db.list_files("app1").files == []


def test_mark_file_status_lifecycle():
    db = FakeDatabase()
    db.create_file("app1", "f1", "a.txt", "s3://b/a.txt", size=10)
    assert db.list_files("app1").files[0].status == "queued"

    db.mark_file_indexing("app1", "f1")
    assert db.list_files("app1").files[0].status == "indexing"

    db.mark_file_failed("app1", "f1", "parse failed")
    failed = db.list_files("app1").files[0]
    assert failed.status == "failed"
    assert failed.error == "parse failed"
    assert failed.indexed_at is None

    db.upsert_file("app1", "f1", "a.txt", "s3://b/a.txt", size=10, chunk_count=3)
    success = db.list_files("app1").files[0]
    assert success.status == "success"
    assert success.error is None
    assert success.indexed_at is not None
