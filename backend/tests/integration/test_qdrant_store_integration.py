import pytest


pytestmark = pytest.mark.integration


def _chunk(chunk_id: str, filename: str, content: str, chunk_index: int = 0) -> dict:
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {"filename": filename, "chunk_index": chunk_index},
    }


class TestQdrantStoreIntegration:
    def test_file_reupload_replaces_old_chunks(self, initialized_store):
        store = initialized_store
        file_id = "integrationfilereplace"

        store.add_file_chunks(
            [
                _chunk("replace-file-v1-0", "replace.txt", "旧版知识 0"),
                _chunk("replace-file-v1-1", "replace.txt", "旧版知识 1"),
            ],
            file_id=file_id,
        )
        store.add_file_chunks(
            [
                _chunk("replace-file-v2-0", "replace.txt", "第二版知识 0"),
            ],
            file_id=file_id,
        )

        docs = store.get_search_documents(store.build_file_filter([file_id]))
        assert len(docs) == 1
        assert docs[0]["content"] == "第二版知识 0"

    def test_file_filter_limits_results_to_selected_files(self, initialized_store):
        store = initialized_store

        store.add_file_chunks([_chunk("file-a-0", "a.txt", "A 文件知识")], file_id="integrationfilea")
        store.add_file_chunks([_chunk("file-b-0", "b.txt", "B 文件知识")], file_id="integrationfileb")
        store.add_file_chunks([_chunk("file-c-0", "c.txt", "C 文件知识")], file_id="integrationfilec")

        docs = store.get_search_documents(store.build_file_filter(["integrationfilea", "integrationfilec"]))
        filenames = {doc["metadata"]["filename"] for doc in docs}

        assert filenames == {"a.txt", "c.txt"}

    def test_delete_file_chunks_returns_deleted_chunk_count(self, initialized_store):
        store = initialized_store
        file_id = "integrationfiledelete"

        store.add_file_chunks(
            [
                _chunk("delete-file-0", "delete.txt", "待删除知识 0"),
                _chunk("delete-file-1", "delete.txt", "待删除知识 1"),
            ],
            file_id=file_id,
        )

        assert store.delete_file_chunks(file_id) == 2
        assert store.get_search_documents(store.build_file_filter([file_id])) == []
