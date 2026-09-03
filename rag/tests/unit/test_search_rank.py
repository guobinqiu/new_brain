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
