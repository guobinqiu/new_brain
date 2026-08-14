import pytest


pytestmark = pytest.mark.unit


def test_list_files_from_documents_groups_chunks_and_paginates():
    from store.files import list_files_from_documents

    page = list_files_from_documents(
        [
            {"metadata": {"file_id": "file_a", "filename": "a.pdf", "chunk_index": 0}},
            {"metadata": {"file_id": "file_a", "filename": "a.pdf", "chunk_index": 1}},
            {"metadata": {"file_id": "file_b", "filename": "b.pdf", "chunk_index": 0}},
        ],
        limit=1,
    )

    assert len(page.files) == 1
    assert page.files[0].id == "file_b"
    assert page.files[0].filename == "b.pdf"
    assert page.files[0].chunk_count == 1
    assert page.next_cursor == "1"
    assert page.has_more is True


def test_count_files_from_documents_counts_distinct_file_ids():
    from store.files import count_files_from_documents

    assert count_files_from_documents(
        [
            {"metadata": {"file_id": "file_a"}},
            {"metadata": {"file_id": "file_a"}},
            {"metadata": {"file_id": "file_b"}},
            {"metadata": {}},
        ]
    ) == 2
