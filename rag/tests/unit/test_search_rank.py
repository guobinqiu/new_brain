import pytest


pytestmark = pytest.mark.unit


def test_weighted_reciprocal_rank_merges_weighted_rankings():
    from rag.search.rank import weighted_reciprocal_rank

    results = weighted_reciprocal_rank(
        (
            (0.7, [{"id": "dense-only"}, {"id": "both"}]),
            (0.3, [{"id": "both"}, {"id": "sparse-only"}]),
        ),
        limit=3,
        rrf_k=60,
    )

    assert [item["id"] for item in results] == ["both", "dense-only", "sparse-only"]
    assert all("_score" in item for item in results)


def test_weighted_reciprocal_rank_respects_limit():
    from rag.search.rank import weighted_reciprocal_rank

    results = weighted_reciprocal_rank(
        (
            (1.0, [{"id": "a"}, {"id": "b"}, {"id": "c"}]),
        ),
        limit=2,
        rrf_k=60,
    )

    assert [item["id"] for item in results] == ["a", "b"]


def test_weighted_reciprocal_rank_handles_empty_input():
    from rag.search.rank import weighted_reciprocal_rank

    assert weighted_reciprocal_rank((), limit=10, rrf_k=60) == []
    assert weighted_reciprocal_rank(((1.0, []),), limit=10, rrf_k=60) == []
