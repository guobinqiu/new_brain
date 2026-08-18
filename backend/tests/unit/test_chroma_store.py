from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_chroma_store_resolves_persist_dir_from_project_root(tmp_path):
    from store import chroma

    project_root = tmp_path / "rag"
    project_root.mkdir()

    path = chroma._persist_path("chroma_data", project_root=project_root)

    assert path == str(project_root / "chroma_data")
    assert (project_root / "chroma_data").is_dir()


def test_chroma_store_keeps_absolute_persist_dir(tmp_path):
    from store import chroma

    persist_dir = tmp_path / "absolute_chroma"

    assert chroma._persist_path(str(persist_dir)) == str(persist_dir)


def test_chroma_list_chunks_uses_collection_limit_offset(monkeypatch):
    from store import chroma

    calls = []

    class FakeCollection:
        def get(self, **kwargs):
            calls.append(kwargs)
            return {
                "ids": ["chunk-1", "chunk-2", "chunk-3"],
                "documents": ["a", "b", "c"],
                "metadatas": [
                    {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0},
                    {"file_id": "file-a", "filename": "a.txt", "chunk_index": 1},
                    {"file_id": "file-a", "filename": "a.txt", "chunk_index": 2},
                ],
            }

    monkeypatch.setattr(chroma, "_collection", lambda: FakeCollection())

    page = chroma.list_chunks(file_ids=["file-a"], limit=2, cursor="5")

    assert [document["id"] for document in page["documents"]] == ["chunk-1", "chunk-2"]
    assert page["next_cursor"] == "7"
    assert page["has_more"] is True
    assert calls == [{
        "where": {"file_id": {"$in": ["file-a"]}},
        "limit": 3,
        "offset": 5,
        "include": ["documents", "metadatas"],
    }]
