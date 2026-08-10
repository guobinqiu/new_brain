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
        def start(self):
            calls.append("store.start")

        def drop_collections(self):
            calls.append("drop")

    class FakeApplication:
        def __init__(self, config):
            self.dense = FakeComponent("dense")
            self.sparse = FakeComponent("sparse")
            self.store = FakeStore()
            self.search = FakeComponent("search")
            self.rerank = FakeComponent("rerank")
            self.ocr = FakeComponent("ocr")
            self.ready = False

    monkeypatch.setattr(benchmark, "_config_for", lambda batch, tmp_path: {"config": "value"})
    monkeypatch.setattr(benchmark, "yaml", type("FakeYaml", (), {"safe_dump": staticmethod(lambda *args, **kwargs: "config: value\n")}))
    monkeypatch.setattr("bootstrap.Application", FakeApplication)
    monkeypatch.setattr("loader.load_config_file", lambda path: {"loaded": str(path)})

    benchmark._start_application(
        benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="none"),
        tmp_path,
    )

    assert calls == ["dense.start", "sparse.start", "drop", "store.start", "search.start", "ocr.start"]


def test_benchmark_start_application_starts_rerank_only_when_enabled(monkeypatch, tmp_path):
    from tests.benchmark import test_search_benchmark as benchmark

    calls = []

    class FakeComponent:
        def __init__(self, name):
            self.name = name

        def start(self):
            calls.append(f"{self.name}.start")

    class FakeStore:
        def start(self):
            calls.append("store.start")

        def drop_collections(self):
            calls.append("drop")

    class FakeApplication:
        def __init__(self, config):
            self.dense = FakeComponent("dense")
            self.sparse = FakeComponent("sparse")
            self.store = FakeStore()
            self.search = FakeComponent("search")
            self.rerank = FakeComponent("rerank")
            self.ocr = FakeComponent("ocr")
            self.ready = False

    monkeypatch.setattr(benchmark, "_config_for", lambda batch, tmp_path: {"config": "value"})
    monkeypatch.setattr(benchmark, "yaml", type("FakeYaml", (), {"safe_dump": staticmethod(lambda *args, **kwargs: "config: value\n")}))
    monkeypatch.setattr("bootstrap.Application", FakeApplication)
    monkeypatch.setattr("loader.load_config_file", lambda path: {"loaded": str(path)})

    application = benchmark._start_application(
        benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="bge-reranker-base"),
        tmp_path,
    )

    assert "rerank.start" in calls
    assert application.ready is True


def test_benchmark_batches_can_filter_dense_by_environment(monkeypatch):
    from tests.benchmark import test_search_benchmark as benchmark

    monkeypatch.setenv("BENCHMARK_DENSE", "bge-base")

    batches = benchmark._benchmark_batches("qdrant")

    assert batches
    assert {batch.combo.dense for batch in batches} == {"bge-base"}


def test_benchmark_batches_can_filter_sparse_by_environment(monkeypatch):
    from tests.benchmark import test_search_benchmark as benchmark

    monkeypatch.setenv("BENCHMARK_SPARSE", "bm25")
    monkeypatch.setenv("BENCHMARK_SPARSE_IMPL", "app")

    batches = benchmark._benchmark_batches("qdrant")

    assert batches
    assert {batch.combo.sparse for batch in batches} == {"bm25"}
    assert {batch.combo.sparse_impl for batch in batches} == {"app"}


def test_benchmark_embedded_stores_use_tmp_path(tmp_path):
    from tests.benchmark import test_search_benchmark as benchmark

    chroma_batch = benchmark.BenchmarkBatch(
        combo=next(combo for combo in benchmark.BACKEND_COMBOS if combo.store_key == "chroma"),
        rerank="none",
    )
    milvus_lite_batch = benchmark.BenchmarkBatch(
        combo=next(combo for combo in benchmark.BACKEND_COMBOS if combo.store_key == "milvus_lite"),
        rerank="none",
    )

    chroma_config = benchmark._config_for(chroma_batch, tmp_path)
    milvus_lite_config = benchmark._config_for(milvus_lite_batch, tmp_path)

    assert chroma_config["store"]["chroma"]["persist_dir"] == str(tmp_path / "chroma")
    assert milvus_lite_config["store"]["milvus_lite"]["uri"] == str(tmp_path / "milvus_lite.db")
