from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.benchmark import test_search_benchmark as benchmark


pytestmark = pytest.mark.benchmark

DOCUMENT_PATH = benchmark.DOCUMENT_PATH
RESULTS_DIR = benchmark.RESULTS_DIR
NAMESPACE = "accuracy_benchmark"
TOP_K_VALUES = [5, 20]


@dataclass(frozen=True)
class BenchmarkQuery:
    name: str
    query: str
    target_text: str


BENCHMARK_QUERIES = [
    BenchmarkQuery(
        name="keyword",
        query="有多少华为卡",
        target_text="一万六千张卡",
    ),
    BenchmarkQuery(
        name="simple_semantic",
        query="他们怎么看国产算力和英伟达的差距？",
        target_text="国产算力是比较乐观的",
    ),
    BenchmarkQuery(
        name="complex_semantic",
        query="为什么他们觉得落后两年的国产算力仍然值得投入？",
        target_text="四张华为 950 能顶一张 GB300",
    ),
]


def test_search_accuracy_matrix(tmp_path):
    if os.environ.get("RUN_BENCHMARK") != "1":
        pytest.skip("set RUN_BENCHMARK=1 to run long benchmark")
    if not DOCUMENT_PATH.exists():
        pytest.skip(f"benchmark fixture not found: {DOCUMENT_PATH}")

    chunks = None
    for database in benchmark.DATABASES:
        rows_by_query = {query_case.name: [] for query_case in BENCHMARK_QUERIES}
        for batch in benchmark._benchmark_batches(database):
            application = benchmark._start_application(batch, tmp_path, start_ocr=False)
            try:
                if chunks is None:
                    chunks = _parse_document_chunks()
                _rebuild_index(application, chunks)
                for mode in benchmark.QUERY_MODES:
                    for top_k in TOP_K_VALUES:
                        for query_case in BENCHMARK_QUERIES:
                            rows_by_query[query_case.name].append(_run_accuracy_scenario(application, batch, query_case, mode, top_k))
            finally:
                application.stop()

        for query_case in BENCHMARK_QUERIES:
            report = _render_query_report(database, query_case, rows_by_query[query_case.name])
            _write_query_report(database, query_case, report)
            print("\n" + report)


def _parse_document_chunks() -> list[dict]:
    from document_parser import parse_file

    return parse_file(str(DOCUMENT_PATH), original_filename=DOCUMENT_PATH.name, ocr=None)


def _rebuild_index(application, chunks: list[dict]) -> None:
    application.store.delete_common_document(DOCUMENT_PATH.name, namespace=NAMESPACE)
    application.store.add_common_documents(chunks, namespace=NAMESPACE)


def _run_accuracy_scenario(application, batch: benchmark.BenchmarkBatch, query_case: BenchmarkQuery, mode: str, top_k: int) -> dict[str, Any]:
    from search import SearchPlan, _SearchExecutor

    combo = batch.combo
    rerank = batch.rerank != "none"
    plan = SearchPlan(
        query_case.query,
        mode=mode,
        top_k=top_k,
        rerank=rerank,
        fetch_k=benchmark.FETCH_K,
        namespace=NAMESPACE,
        scope_ids=[],
    )
    results = _SearchExecutor(plan, rerank=application.rerank, sparse=application.sparse, store=application.store).execute()
    return {
        "database": combo.database,
        "dense": combo.dense,
        "sparse": combo.sparse,
        "sparse_impl": combo.sparse_impl,
        "mode": mode,
        "rerank": batch.rerank,
        "top_k": top_k,
        "target_rank": _target_rank(results, query_case.target_text) or "-",
    }


def _target_rank(results: list[dict], target_text: str) -> int | None:
    normalized_target = _normalize(target_text)
    for index, result in enumerate(results, start=1):
        if normalized_target in _normalize(result.get("content", "")):
            return index
    return None


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", str(text)).split())


def _render_query_report(database: str, query_case: BenchmarkQuery, rows: list[dict[str, Any]]) -> str:
    columns = ["database", "dense", "sparse", "sparse_impl", "mode", "rerank", "top_k", "target_rank"]
    lines = [
        "# Search Accuracy Benchmark",
        "",
        f"- document: {DOCUMENT_PATH.name}",
        f"- database: {database}",
        f"- query_name: {query_case.name}",
        f"- query: {query_case.query}",
        f"- target_text: {query_case.target_text}",
        f"- scenario_count: {len(rows)}",
        "",
        _markdown_row(columns),
        _markdown_row(["---"] * len(columns)),
    ]
    lines.extend(_markdown_row([row[column] for column in columns]) for row in rows)
    return "\n".join(lines) + "\n"


def _write_query_report(database: str, query_case: BenchmarkQuery, report: str) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    _report_path(database, query_case).write_text(report, encoding="utf-8")


def _report_path(database: str, query_case: BenchmarkQuery) -> Path:
    return RESULTS_DIR / f"search_accuracy_{benchmark._slug(database)}_{benchmark._slug(query_case.name)}.md"


def _markdown_row(values) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"
