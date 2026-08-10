import pytest


pytestmark = pytest.mark.unit


def test_benchmark_results_dir_stays_inside_benchmark_tests():
    from tests.benchmark import test_search_benchmark as benchmark

    assert benchmark.RESULTS_DIR == benchmark.Path(benchmark.__file__).resolve().parent / "results"


def test_benchmark_start_application_drops_collections_before_start(monkeypatch, tmp_path):
    from tests.benchmark import test_search_benchmark as benchmark

    calls = []

    class FakeComponent:
        def __init__(self, name):
            self.name = name

        def start(self):
            calls.append(f"{self.name}.start")

    class FakeStore:
        def drop_collections(self):
            calls.append("drop")

    class FakeApplication:
        def __init__(self, config):
            self.dense = FakeComponent("dense")
            self.sparse = FakeComponent("sparse")
            self.store = FakeStore()

        def start(self):
            calls.append("start")

    monkeypatch.setattr(benchmark, "_config_for", lambda batch: {"config": "value"})
    monkeypatch.setattr(benchmark, "yaml", type("FakeYaml", (), {"safe_dump": staticmethod(lambda *args, **kwargs: "config: value\n")}))
    monkeypatch.setattr("bootstrap.Application", FakeApplication)
    monkeypatch.setattr("loader.load_config_file", lambda path: {"loaded": str(path)})

    benchmark._start_application(
        benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="none"),
        tmp_path,
    )

    assert calls == ["dense.start", "sparse.start", "drop", "start"]
