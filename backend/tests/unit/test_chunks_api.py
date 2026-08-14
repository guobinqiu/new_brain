from main import _chunk_page


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
