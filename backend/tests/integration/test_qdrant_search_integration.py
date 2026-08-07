import pytest


pytestmark = pytest.mark.integration


def _chunk(chunk_id: str, filename: str, content: str) -> dict:
    return {
        "id": chunk_id,
        "content": content,
        "metadata": {"filename": filename, "chunk_index": 0, "created_at": "test"},
    }


def _started_bm25_sparse():
    from sparse.bm25 import BM25Sparse

    sparse = BM25Sparse()
    sparse.start()
    return sparse


class TestQdrantSearchIntegration:
    def test_search_common_and_scoped_returns_scoped_first(self, initialized_store):
        store = initialized_store
        from search import SearchPlan, _SearchExecutor
        from rerank.cross_encoder import CrossEncoderRerank

        namespace = "integration_search_merge"
        store.add_common_documents(
            [_chunk("search-common-0", "common_search.txt", "人工智能 通用知识 自然语言处理")],
            namespace=namespace,
        )
        store.add_scoped_documents(
            [_chunk("search-scoped-0", "scoped_search.txt", "人工智能 专属知识 机器学习")],
            namespace=namespace,
            scope_id="scope_a",
        )

        results = _SearchExecutor(
            SearchPlan(
                "人工智能",
                mode="hybrid",
                top_k=2,
                namespace=namespace,
                scope_ids=["scope_a"],
            ),
            sparse=_started_bm25_sparse(),
        ).execute()

        assert len(results) == 2
        assert results[0]["collection_type"] == "scoped"
        assert {result["collection_type"] for result in results} == {"common", "scoped"}
        assert all("method" not in result for result in results)

    def test_search_with_scope_ids_always_includes_common_collection(self, initialized_store):
        store = initialized_store
        from search import SearchPlan, _SearchExecutor

        namespace = "integration_search_scoped_only"
        store.add_common_documents(
            [_chunk("scoped-only-common-0", "common_only.txt", "范围过滤测试 通用知识")],
            namespace=namespace,
        )
        store.add_scoped_documents(
            [_chunk("scoped-only-scoped-0", "scoped_only.txt", "范围过滤测试 专属知识")],
            namespace=namespace,
            scope_id="scope_a",
        )

        results = _SearchExecutor(
            SearchPlan(
                "范围过滤测试",
                mode="dense",
                top_k=5,
                namespace=namespace,
                scope_ids=["scope_a"],
            )
        ).execute()

        assert results
        assert {result["collection_type"] for result in results} == {"common", "scoped"}

    def test_search_rerank_uses_fetch_k_and_returns_top_k(self, initialized_store):
        store = initialized_store
        from rerank.cross_encoder import CrossEncoderRerank
        from search import SearchPlan, _SearchExecutor

        namespace = "integration_search_rerank"
        for index in range(5):
            store.add_common_documents(
                [_chunk(f"rerank-common-{index}", f"rerank_{index}.txt", f"重排候选 文档 {index} 人工智能")],
                namespace=namespace,
            )

        rerank = CrossEncoderRerank()
        rerank.start()

        results = _SearchExecutor(
            SearchPlan(
                "重排候选",
                mode="dense",
                top_k=2,
                rerank=True,
                fetch_k=5,
                namespace=namespace,
            ),
            rerank=rerank,
        ).execute()

        assert 0 < len(results) <= 2
        assert all("collection_type" in result for result in results)

    def test_scoped_term_is_hidden_without_scope_and_visible_with_scope(self, initialized_store):
        store = initialized_store
        from search import SearchPlan, _SearchExecutor

        namespace = "integration_scope_visibility"
        store.add_common_documents(
            [_chunk("scope-visibility-common", "common_visibility.txt", "通用知识 巡检 物料 设备")],
            namespace=namespace,
        )
        store.add_scoped_documents(
            [_chunk("scope-visibility-scoped", "scope_visibility.txt", "年检 设备维护 scope_alpha 专属流程")],
            namespace=namespace,
            scope_id="scope_alpha",
        )

        without_scope = _SearchExecutor(
            SearchPlan(
                "年检",
                mode="hybrid",
                top_k=5,
                namespace=namespace,
                scope_ids=[],
            ),
            sparse=_started_bm25_sparse(),
        ).execute()
        with_scope = _SearchExecutor(
            SearchPlan(
                "年检",
                mode="hybrid",
                top_k=5,
                namespace=namespace,
                scope_ids=["scope_alpha"],
            ),
            sparse=_started_bm25_sparse(),
        ).execute()

        assert all(result["collection_type"] == "common" for result in without_scope)
        assert not any(result["metadata"].get("scope_id") == "scope_alpha" for result in without_scope)
        assert any(result["metadata"].get("scope_id") == "scope_alpha" for result in with_scope)
        assert with_scope[0]["collection_type"] == "scoped"

    def test_sparse_search_matches_chinese_scope_term(self, initialized_store):
        store = initialized_store
        from search import SearchPlan, _SearchExecutor

        namespace = "integration_sparse_chinese_term"
        store.add_common_documents(
            [_chunk("sparse-chinese-common", "sparse_common.txt", "通用知识 巡检 物料 设备")],
            namespace=namespace,
        )
        store.add_scoped_documents(
            [_chunk("sparse-chinese-scoped", "sparse_scope.txt", "设备年检单办理流程适用于scopealpha范围")],
            namespace=namespace,
            scope_id="scope_alpha",
        )

        results = _SearchExecutor(
            SearchPlan(
                "年检",
                mode="sparse",
                top_k=5,
                namespace=namespace,
                scope_ids=["scope_alpha"],
            ),
            sparse=_started_bm25_sparse(),
        ).execute()

        assert [result["id"] for result in results] == ["sparse-chinese-scoped"]
