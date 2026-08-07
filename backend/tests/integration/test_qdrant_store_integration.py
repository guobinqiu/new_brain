import pytest


pytestmark = pytest.mark.integration


def _chunk(chunk_id: str, filename: str, content: str, chunk_index: int = 0) -> dict:
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {"filename": filename, "chunk_index": chunk_index, "created_at": "test"},
    }


class TestQdrantStoreIntegration:
    def test_common_document_reupload_replaces_old_chunks(self, initialized_store):
        store = initialized_store

        namespace = "integration_common_replace"
        filename = "replace_common.txt"

        store.add_common_documents(
            [
                _chunk("replace-common-v1-0", filename, "第一版通用知识 0"),
                _chunk("replace-common-v1-1", filename, "第一版通用知识 1"),
            ],
            namespace=namespace,
        )
        store.add_common_documents(
            [
                _chunk("replace-common-v2-0", filename, "第二版通用知识 0"),
            ],
            namespace=namespace,
        )

        docs = store.list_common_documents(namespace=namespace)
        target = next(doc for doc in docs if doc["filename"] == filename)
        assert target["chunks"] == 1

    def test_scoped_documents_are_filtered_by_multiple_scope_ids(self, initialized_store):
        store = initialized_store

        namespace = "integration_scoped_filter"
        store.add_scoped_documents(
            [_chunk("scoped-a-0", "scoped_a.txt", "scope A 专属知识")],
            namespace=namespace,
            scope_id="scope_a",
        )
        store.add_scoped_documents(
            [_chunk("scoped-b-0", "scoped_b.txt", "scope B 专属知识")],
            namespace=namespace,
            scope_id="scope_b",
        )
        store.add_scoped_documents(
            [_chunk("scoped-c-0", "scoped_c.txt", "scope C 专属知识")],
            namespace=namespace,
            scope_id="scope_c",
        )

        docs = store.list_scoped_documents(namespace=namespace, scope_ids=["scope_a", "scope_c"])
        filenames = {doc["filename"] for doc in docs}

        assert "scoped_a.txt" in filenames
        assert "scoped_c.txt" in filenames
        assert "scoped_b.txt" not in filenames

    def test_delete_common_document_returns_deleted_chunk_count(self, initialized_store):
        store = initialized_store

        namespace = "integration_delete_common"
        filename = "delete_common.txt"
        store.add_common_documents(
            [
                _chunk("delete-common-0", filename, "待删除通用知识 0"),
                _chunk("delete-common-1", filename, "待删除通用知识 1"),
            ],
            namespace=namespace,
        )

        assert store.delete_common_document(filename, namespace=namespace) == 2
        assert not any(doc["filename"] == filename for doc in store.list_common_documents(namespace=namespace))

    def test_delete_scoped_document_can_delete_one_scope_only(self, initialized_store):
        store = initialized_store

        namespace = "integration_delete_scoped"
        filename = "same_name.txt"
        store.add_scoped_documents(
            [_chunk("delete-scoped-a-0", filename, "scope A 同名知识")],
            namespace=namespace,
            scope_id="scope_a",
        )
        store.add_scoped_documents(
            [_chunk("delete-scoped-b-0", filename, "scope B 同名知识")],
            namespace=namespace,
            scope_id="scope_b",
        )

        assert store.delete_scoped_document(filename, namespace=namespace, scope_id="scope_a") == 1

        docs = store.list_scoped_documents(namespace=namespace)
        remaining_scopes = {doc["scope_id"] for doc in docs if doc["filename"] == filename}
        assert remaining_scopes == {"scope_b"}
