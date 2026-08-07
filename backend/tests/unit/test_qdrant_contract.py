import pytest


pytestmark = pytest.mark.unit


def test_qdrant_collection_names_are_production_names():
    from loader import load_config_file

    config = load_config_file("config/default.yaml")

    assert config.store.collections.common == "knowledge_common"
    assert config.store.collections.scoped == "knowledge_scoped"


def test_search_plan_carries_namespace_and_scope_ids():
    import search

    plan = search.SearchPlan(
        "query",
        mode="hybrid",
        top_k=10,
        rerank=True,
        fetch_k=50,
        namespace="default",
        scope_ids=["scope_001", "scope_002"],
    )

    assert plan.namespace == "default"
    assert plan.scope_ids == ["scope_001", "scope_002"]
    assert not hasattr(plan, "include_common")


def test_search_request_builds_plan_from_post_body(monkeypatch):
    import main

    captured = {}
    monkeypatch.setattr(main, "_require_ready", lambda: None)

    class FakeExecutor:
        def __init__(self, plan, **kwargs):
            captured["plan"] = plan
            captured["kwargs"] = kwargs

        def execute(self):
            return []

    monkeypatch.setattr(main, "_SearchExecutor", FakeExecutor)

    response = main.search(
        main.SearchRequest(
            query="query",
            mode="hybrid",
            top_k=8,
            rerank=True,
            fetch_k=80,
            namespace="tenant_a",
            scope_ids=["scope_001", "scope_002"],
        )
    )

    plan = captured["plan"]
    assert response["results"] == []
    assert plan.namespace == "tenant_a"
    assert plan.scope_ids == ["scope_001", "scope_002"]
    assert not hasattr(plan, "include_common")


def test_search_request_defaults_come_from_config():
    import main

    req = main.SearchRequest(query="query")

    assert req.top_k == main.SEARCH_CONFIG["top_k"]
    assert req.fetch_k == main.SEARCH_CONFIG["fetch_k"]
    assert req.namespace == "default"


def test_search_request_rejects_fetch_k_smaller_than_top_k():
    import pytest
    from pydantic import ValidationError
    import main

    with pytest.raises(ValidationError, match="fetch_k must be greater than or equal to top_k"):
        main.SearchRequest(query="query", top_k=20, fetch_k=10)


def test_search_request_returns_503_when_application_is_not_ready(monkeypatch):
    import pytest
    from fastapi import HTTPException
    import main

    monkeypatch.setattr(main.application, "ready", False)

    with pytest.raises(HTTPException) as exc:
        main.search(main.SearchRequest(query="query"))

    assert exc.value.status_code == 503
    assert exc.value.detail == "search is not initialized"
