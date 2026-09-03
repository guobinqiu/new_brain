from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_chroma_store_resolves_persist_dir_from_project_root(tmp_path):
    from rag.store import chroma

    project_root = tmp_path / "rag"
    project_root.mkdir()

    path = chroma._persist_path("chroma_data", project_root=project_root)

    assert path == str(project_root / "chroma_data")
    assert (project_root / "chroma_data").is_dir()


def test_chroma_store_keeps_absolute_persist_dir(tmp_path):
    from rag.store import chroma

    persist_dir = tmp_path / "absolute_chroma"

    assert chroma._persist_path(str(persist_dir)) == str(persist_dir)


def test_chroma_list_chunks_uses_stable_cursor_order(monkeypatch):
    from rag.scope import app_collection
    from rag.store.chroma import ChromaStore

    calls = []

    class FakeCollection:
        def get(self, **kwargs):
            calls.append(kwargs)
            return {
                "ids": ["chunk-3", "chunk-1", "chunk-2", "chunk-4"],
                "documents": ["c", "a", "b", "d"],
                "metadatas": [
                    {"file_id": "file-b", "filename": "b.txt", "chunk_index": 0},
                    {"file_id": "file-a", "filename": "a.txt", "chunk_index": 1},
                    {"file_id": "file-a", "filename": "a.txt", "chunk_index": 2},
                    {"file_id": "file-a", "filename": "a.txt", "chunk_index": 3},
                ],
            }

    class FakeClient:
        def get_collection(self, name):
            return FakeCollection()

    store = ChromaStore()
    store.client = FakeClient()
    store._ready = True

    with app_collection("imsdom"):
        first_page = store.list_chunks(file_ids=None, limit=1)
        page = store.list_chunks(file_ids=None, limit=2, cursor=first_page["next_cursor"])

    assert [document["id"] for document in first_page["documents"]] == ["chunk-1"]
    assert [document["id"] for document in page["documents"]] == ["chunk-2", "chunk-4"]
    assert page["has_more"] is True
    assert calls == [{"include": ["documents", "metadatas"]}, {"include": ["documents", "metadatas"]}]
