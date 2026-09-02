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
    monkeypatch.setattr("rag.bootstrap.Application", FakeApplication)
    monkeypatch.setattr("rag.loader.load_config_file", lambda path: {"loaded": str(path)})

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
    monkeypatch.setattr("rag.bootstrap.Application", FakeApplication)
    monkeypatch.setattr("rag.loader.load_config_file", lambda path: {"loaded": str(path)})

    application = benchmark._start_application(
        benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="bge-reranker-base"),
        tmp_path,
    )

    assert "rerank.start" in calls
    assert application.ready is True


def test_benchmark_start_application_can_skip_ocr(monkeypatch, tmp_path):
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
    monkeypatch.setattr("rag.bootstrap.Application", FakeApplication)
    monkeypatch.setattr("rag.loader.load_config_file", lambda path: {"loaded": str(path)})

    benchmark._start_application(
        benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="none"),
        tmp_path,
        start_ocr=False,
    )

    assert "ocr.start" not in calls


def test_search_benchmark_matrix_skips_ocr(monkeypatch, tmp_path):
    from tests.benchmark import test_search_benchmark as benchmark

    calls = []
    batch = benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="none")

    class FakeApplication:
        def stop(self):
            calls.append(("stop",))

    monkeypatch.setenv("RUN_BENCHMARK", "1")
    monkeypatch.setattr(benchmark, "DOCUMENT_PATH", tmp_path / "fixture.pdf")
    benchmark.DOCUMENT_PATH.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(benchmark, "_benchmark_batches", lambda database: [batch])
    monkeypatch.setattr(benchmark, "_start_application", lambda batch, tmp_path, start_ocr=True: calls.append(("start_ocr", start_ocr)) or FakeApplication())
    monkeypatch.setattr(benchmark, "_rebuild_index", lambda application: calls.append(("rebuild",)))
    monkeypatch.setattr(benchmark, "QUERY_MODES", ["dense"])
    monkeypatch.setattr(benchmark, "TOP_K_VALUES", [5])
    monkeypatch.setattr(benchmark, "_run_scenario", lambda application, batch, mode, top_k: {
        "database": "qdrant",
        "dense": "bge-base",
        "sparse": "simple_bm25",
        "sparse_impl": "app",
        "mode": mode,
        "rerank": "none",
        "top_k": top_k,
        "fetch_k": "-",
        "warmup_runs": 0,
        "runs": 0,
        "samples": 0,
        "p50_ms": "-",
        "p95_ms": "-",
        "p99_ms": "-",
        "avg_ms": "-",
        "min_ms": "-",
        "max_ms": "-",
        "errors": 0,
        "target_found": False,
        "target_rank": "-",
    })
    monkeypatch.setattr(benchmark, "_write_summary", lambda summary, database: calls.append(("summary", database)))

    benchmark.test_search_benchmark_matrix("qdrant", tmp_path)

    assert calls.count(("start_ocr", False)) == 1


def test_benchmark_batches_can_filter_dense_by_environment(monkeypatch):
    from tests.benchmark import test_search_benchmark as benchmark

    monkeypatch.setenv("BENCHMARK_DENSE", "bge-base")

    batches = benchmark._benchmark_batches("qdrant")

    assert batches
    assert {batch.combo.dense for batch in batches} == {"bge-base"}


def test_benchmark_batches_can_filter_sparse_by_environment(monkeypatch):
    from tests.benchmark import test_search_benchmark as benchmark

    monkeypatch.setenv("BENCHMARK_SPARSE", "simple_bm25")
    monkeypatch.setenv("BENCHMARK_SPARSE_IMPL", "app")

    batches = benchmark._benchmark_batches("qdrant")

    assert batches
    assert {batch.combo.sparse for batch in batches} == {"simple_bm25"}
    assert {batch.combo.sparse_impl for batch in batches} == {"app"}


def test_benchmark_sparse_impl_uses_app_or_vector_names():
    from tests.benchmark import test_search_benchmark as benchmark

    sparse_impls = {combo.sparse_impl for combo in benchmark.BACKEND_COMBOS}

    assert sparse_impls <= {"app", "vector"}
    assert "vector" in sparse_impls


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

    assert chroma_config["store"]["persist_dir"] == str(tmp_path / "chroma")
    assert milvus_lite_config["store"]["uri"] == str(tmp_path / "milvus_lite.db")


def test_accuracy_benchmark_defines_one_report_per_query():
    from tests.benchmark import test_search_accuracy_benchmark as accuracy

    assert [query.name for query in accuracy.BENCHMARK_QUERIES] == [
        "keyword",
        "simple_semantic",
        "complex_semantic",
    ]
    assert accuracy._report_path("milvus-standalone", accuracy.BENCHMARK_QUERIES[0]).name == "search_accuracy_milvus_standalone_keyword.md"


def test_accuracy_benchmark_report_contains_only_rank_columns():
    from tests.benchmark import test_search_accuracy_benchmark as accuracy

    report = accuracy._render_query_report(
        "qdrant",
        accuracy.BENCHMARK_QUERIES[0],
        [
            {
                "database": "qdrant",
                "dense": "bge-m3",
                "sparse": "bge-m3",
                "sparse_impl": "store",
                "mode": "hybrid",
                "rerank": "bge-reranker-base",
                "top_k": 20,
                "target_rank": 3,
            }
        ],
    )

    assert "- database: qdrant" in report
    header = next(line for line in report.splitlines() if line.startswith("| database"))
    assert header == "| database | dense | sparse | sparse_impl | mode | rerank | top_k | target_rank |"


def test_accuracy_benchmark_reuses_one_index_for_all_queries(monkeypatch, tmp_path):
    from tests.benchmark import test_search_accuracy_benchmark as accuracy
    from tests.benchmark import test_search_benchmark as benchmark

    class FakeStore:
        def delete_file_chunks(self, file_id):
            calls.append(("delete", file_id))

        def add_file_chunks(self, chunks, file_id):
            calls.append(("add", len(chunks), file_id))

    class FakeApplication:
        def __init__(self):
            self.store = FakeStore()
            self.ocr = object()

        def stop(self):
            calls.append(("stop",))

    calls = []
    query_cases = [
        accuracy.BenchmarkQuery("q1", "query 1", "target 1"),
        accuracy.BenchmarkQuery("q2", "query 2", "target 2"),
    ]
    batch = benchmark.BenchmarkBatch(combo=benchmark.BACKEND_COMBOS[0], rerank="none")
    document_path = tmp_path / "fixture.pdf"
    document_path.write_text("fixture", encoding="utf-8")

    monkeypatch.setenv("RUN_BENCHMARK", "1")
    monkeypatch.setattr(accuracy, "DOCUMENT_PATH", document_path)
    monkeypatch.setattr(accuracy, "BENCHMARK_QUERIES", query_cases)
    monkeypatch.setattr(accuracy.benchmark, "DATABASES", ["qdrant"])
    monkeypatch.setattr(accuracy.benchmark, "_benchmark_batches", lambda database: [batch])
    monkeypatch.setattr(accuracy.benchmark, "QUERY_MODES", ["dense"])
    monkeypatch.setattr(accuracy, "TOP_K_VALUES", [5])
    monkeypatch.setattr(accuracy.benchmark, "_start_application", lambda batch, tmp_path, start_ocr=True: calls.append(("start_ocr", start_ocr)) or FakeApplication())
    monkeypatch.setattr(accuracy, "_parse_document_chunks", lambda: [{"id": "1"}])
    monkeypatch.setattr(accuracy, "_run_accuracy_scenario", lambda application, batch, query_case, mode, top_k: {
        "database": "qdrant",
        "dense": "bge-base",
        "sparse": "simple_bm25",
        "sparse_impl": "app",
        "mode": mode,
        "rerank": "none",
        "top_k": top_k,
        "target_rank": "-",
    })
    monkeypatch.setattr(accuracy, "_write_query_report", lambda database, query_case, report: calls.append(("report", database, query_case.name)))

    accuracy.test_search_accuracy_matrix(tmp_path)

    assert calls.count(("add", 1, accuracy.FILE_ID)) == 1
    assert calls.count(("start_ocr", False)) == 1
    assert ("report", "qdrant", "q1") in calls
    assert ("report", "qdrant", "q2") in calls
