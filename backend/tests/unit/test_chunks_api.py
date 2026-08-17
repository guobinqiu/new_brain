from main import _chunk_page


def test_chunks_filters_by_file_ids(monkeypatch):
    import main

    class Store:
        def build_file_filter(self, file_ids=None):
            return {"file_ids": file_ids}

        def get_search_documents(self, metadata_filter):
            assert metadata_filter == {"file_ids": ["file-a", "file-b"]}
            return [
                {"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0}},
            ]

    monkeypatch.setattr(main.application, "store", Store())
    monkeypatch.setattr(main.application, "ready", True)

    page = main.chunks(limit=10, file_ids="file-a, file-b")

    assert page["chunks"][0]["file_id"] == "file-a"


def test_chunk_page_orders_by_file_and_chunk_index():
    documents = [
        {"id": "z", "content": "b1", "metadata": {"file_id": "b", "filename": "b.txt", "chunk_index": 1}},
        {"id": "a", "content": "a2", "metadata": {"file_id": "a", "filename": "a.txt", "chunk_index": 2}},
        {"id": "y", "content": "b0", "metadata": {"file_id": "b", "filename": "b.txt", "chunk_index": 0}},
        {"id": "x", "content": "a0", "metadata": {"file_id": "a", "filename": "a.txt", "chunk_index": 0}},
    ]

    page = _chunk_page(documents, limit=10)

    assert [(item["file_id"], item["chunk_index"]) for item in page["chunks"]] == [
        ("a", 0),
        ("a", 2),
        ("b", 0),
        ("b", 1),
    ]


def test_chunk_page_returns_file_id_without_transform():
    documents = [
        {"id": "x", "content": "a0", "metadata": {"file_id": "file-a", "filename": "a.txt", "chunk_index": 0, "created_at": "2026-08-17T10:00:00+08:00"}},
    ]

    page = _chunk_page(documents, limit=10)

    assert page["chunks"][0]["file_id"] == "file-a"
    assert page["chunks"][0]["created_at"] == "2026-08-17T10:00:00+08:00"
