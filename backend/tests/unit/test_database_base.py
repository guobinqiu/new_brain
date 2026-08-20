import pytest

from database.base import FakeDatabase


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


def test_upsert_restores_soft_deleted():
    db = FakeDatabase()
    _seed(db)
    db.soft_delete_file("app1", "f0")
    db.upsert_file("app1", "f0", "a.txt", "s3://b/a.txt", size=99, chunk_count=5)
    page = db.list_files("app1")
    assert any(r.id == "f0" and r.chunk_count == 5 for r in page.files)


def test_list_first_page_and_next():
    db = FakeDatabase()
    _seed(db)  # 4 条
    page = db.list_files("app1", limit=2)
    assert [r.id for r in page.files] == ["f3", "f2"]
    assert page.next_cursor is not None
    assert page.prev_cursor is None
    assert page.has_more is True

    page2 = db.list_files("app1", limit=2, cursor=page.next_cursor, direction="next")
    assert [r.id for r in page2.files] == ["f1", "f0"]
    assert page2.has_more is False
    assert page2.next_cursor is None
    assert page2.prev_cursor is not None


def test_list_prev_page():
    db = FakeDatabase()
    _seed(db)
    page = db.list_files("app1", limit=2)
    page2 = db.list_files("app1", limit=2, cursor=page.next_cursor, direction="next")
    back = db.list_files("app1", limit=2, cursor=page2.prev_cursor, direction="prev")
    assert [r.id for r in back.files] == ["f3", "f2"]
    assert back.prev_cursor is None  # 已到最新边界
    assert back.has_more is True


def test_purge_app():
    db = FakeDatabase()
    _seed(db)
    assert db.purge_app("app1") == 4
    assert db.list_files("app1").files == []


def test_prev_requires_cursor():
    db = FakeDatabase()
    with pytest.raises(ValueError):
        db.list_files("app1", direction="prev")