import pytest
import uuid


pytestmark = pytest.mark.integration


def _chunk(filename: str, content: str, chunk_id: str | None = None) -> dict:
    return {
        "id": chunk_id or str(uuid.uuid4()),
        "content": content,
        "metadata": {"filename": filename, "chunk_index": 0},
    }


def _started_bm25_sparse():
    from rag.sparse.simple_bm25 import SimpleBM25Sparse

    sparse = SimpleBM25Sparse()
    sparse.start()
    return sparse


class TestQdrantSearchIntegration:
    def test_search_without_file_ids_searches_all_files(self, initialized_store):
        store = initialized_store
        from rag.search import SearchPlan, _SearchExecutor

        store.add_file_chunks([_chunk("all_a.txt", "人工智能 自然语言处理")], file_id="integrationalla")
        store.add_file_chunks([_chunk("all_b.txt", "人工智能 机器学习")], file_id="integrationallb")

        results = _SearchExecutor(
            SearchPlan("人工智能", mode="hybrid", top_k=2),
            sparse=_started_bm25_sparse(),
            store=store,
        ).execute()

        assert len(results) == 2
        assert {result["metadata"]["file_id"] for result in results} == {"integrationalla", "integrationallb"}

    def test_search_with_file_ids_limits_visible_results(self, initialized_store):
        store = initialized_store
        from rag.search import SearchPlan, _SearchExecutor

        store.add_file_chunks([_chunk("visible_a.txt", "范围过滤测试 A")], file_id="integrationvisiblea")
        store.add_file_chunks([_chunk("visible_b.txt", "范围过滤测试 B")], file_id="integrationvisibleb")

        results = _SearchExecutor(
            SearchPlan("范围过滤测试", mode="dense", top_k=5, file_ids=["integrationvisiblea"]),
            store=store,
        ).execute()

        assert results
        assert {result["metadata"]["file_id"] for result in results} == {"integrationvisiblea"}

    def test_search_rerank_uses_fetch_k_and_returns_top_k(self, initialized_store):
        store = initialized_store
        from rag.rerank.cross_encoder import CrossEncoderRerank
        from rag.search import SearchPlan, _SearchExecutor

        for index in range(5):
            store.add_file_chunks(
                [_chunk(f"rerank_{index}.txt", f"重排候选 文档 {index} 人工智能")],
                file_id=f"integrationrerank{index}",
            )

        rerank = CrossEncoderRerank()
        rerank.start()

        results = _SearchExecutor(
            SearchPlan("重排候选", mode="dense", top_k=2, rerank=True, fetch_k=5),
            rerank=rerank,
            store=store,
        ).execute()

        assert 0 < len(results) <= 2
        assert all("file_id" in result["metadata"] for result in results)

    def test_sparse_search_matches_chinese_file_term(self, initialized_store):
        store = initialized_store
        from rag.search import SearchPlan, _SearchExecutor

        sparse_chunk_id = str(uuid.uuid4())
        store.add_file_chunks([_chunk("sparse_a.txt", "通用知识 巡检 物料 设备")], file_id="integrationsparsea")
        store.add_file_chunks([_chunk("sparse_b.txt", "设备年检单办理流程", sparse_chunk_id)], file_id="integrationsparseb")

        results = _SearchExecutor(
            SearchPlan("年检", mode="sparse", top_k=5, file_ids=["integrationsparseb"]),
            sparse=_started_bm25_sparse(),
            store=store,
        ).execute()

        assert [result["id"] for result in results] == [sparse_chunk_id]
