import pytest


pytestmark = pytest.mark.unit


def test_runner_runs_common_only_when_scoped_function_is_absent():
    from rag.search.runner import SearchRunner

    calls = []
    runner = SearchRunner()

    common_items, scoped_items = runner.run_common_and_scoped(
        lambda: calls.append("common") or ["common"]
    )

    assert calls == ["common"]
    assert common_items == ["common"]
    assert scoped_items == []


def test_runner_runs_common_and_scoped_and_preserves_return_slots():
    from rag.search.runner import SearchRunner

    runner = SearchRunner()

    common_items, scoped_items = runner.run_common_and_scoped(
        lambda: ["common"],
        lambda: ["scoped"],
    )

    assert common_items == ["common"]
    assert scoped_items == ["scoped"]


def test_runner_runs_dense_and_sparse_and_preserves_return_slots():
    from rag.search.runner import SearchRunner

    runner = SearchRunner()

    dense_items, sparse_items = runner.run_dense_and_sparse(
        lambda: ["dense"],
        lambda: ["sparse"],
    )

    assert dense_items == ["dense"]
    assert sparse_items == ["sparse"]
