import pytest
import uuid


pytestmark = pytest.mark.integration


def _chunk(filename: str, content: str, chunk_id: str | None = None) -> dict:
    return {
        "id": chunk_id or str(uuid.uuid4()),
        "content": content,
        "metadata": {"filename": filename, "chunk_index": 0},
    }


class TestQdrantSearchIntegration:
    def test_search_without_file_ids_searches_all_files(self, initialized_vector):
        vector = initialized_vector
        from services.rag.core.search import SearchPlan, _SearchExecutor

        vector.add_file_chunks([_chunk("all_a.txt", "人工智能 自然语言处理")], file_id="integrationalla")
        vector.add_file_chunks([_chunk("all_b.txt", "人工智能 机器学习")], file_id="integrationallb")

        results = _SearchExecutor(
            SearchPlan("人工智能", top_k=2),
            vector=vector,
        ).execute()

        assert len(results) == 2
        assert {result["metadata"]["file_id"] for result in results} == {"integrationalla", "integrationallb"}

    def test_search_with_file_ids_limits_visible_results(self, initialized_vector):
        vector = initialized_vector
        from services.rag.core.search import SearchPlan, _SearchExecutor

        vector.add_file_chunks([_chunk("visible_a.txt", "范围过滤测试 A")], file_id="integrationvisiblea")
        vector.add_file_chunks([_chunk("visible_b.txt", "范围过滤测试 B")], file_id="integrationvisibleb")

        results = _SearchExecutor(
            SearchPlan("范围过滤测试", top_k=5, file_ids=["integrationvisiblea"]),
            vector=vector,
        ).execute()

        assert results
        assert {result["metadata"]["file_id"] for result in results} == {"integrationvisiblea"}

    def test_search_returns_top_k(self, initialized_vector):
        vector = initialized_vector
        from services.rag.core.search import SearchPlan, _SearchExecutor

        for index in range(5):
            vector.add_file_chunks(
                [_chunk(f"topk_{index}.txt", f"候选 文档 {index} 人工智能")],
                file_id=f"integrationtopk{index}",
            )

        results = _SearchExecutor(
            SearchPlan("候选", top_k=2),
            vector=vector,
        ).execute()

        assert 0 < len(results) <= 2
        assert all("file_id" in result["metadata"] for result in results)
