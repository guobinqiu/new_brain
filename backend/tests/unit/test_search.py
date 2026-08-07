import pytest


pytestmark = pytest.mark.unit


class TestSearchPlan:
    def test_construction_does_not_touch_store(self):
        """SearchPlan 只描述查询计划,构造时不读取全集或访问检索器。"""
        import search as search_mod

        plan = search_mod.SearchPlan("query", mode="hybrid", top_k=20, rerank=True, fetch_k=100)

        assert plan.query == "query"
        assert plan.mode == "hybrid"
        assert plan.top_k == 20
        assert plan.rerank is True
        assert plan.fetch_k == 100

    def test_no_rerank_keeps_top_k_and_default_fetch_k(self):
        """无重排计划保留 top_k,fetch_k 只是默认值,执行期不会使用。"""
        import search as search_mod

        plan = search_mod.SearchPlan("query", mode="dense", top_k=7)

        assert plan.top_k == 7
        assert plan.fetch_k == 100
        assert plan.rerank is False

    def test_rerank_keeps_top_k_and_fetch_k(self):
        """重排计划同时描述最终返回条数 top_k 和候选池 fetch_k。"""
        import search as search_mod

        plan = search_mod.SearchPlan("query", mode="dense", top_k=3, rerank=True, fetch_k=30)

        assert plan.top_k == 3
        assert plan.fetch_k == 30
        assert plan.rerank is True
