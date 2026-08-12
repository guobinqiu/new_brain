from __future__ import annotations

import math
import os
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml


pytestmark = pytest.mark.benchmark

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DOCUMENT_PATH = FIXTURE_DIR / "梁文锋投资者交流会.pdf"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

QUERY = "有多少华为卡"
TARGET_TEXT = "一万六千张卡"
NAMESPACE = "benchmark"
TOP_K_VALUES = [5, 20]
FETCH_K = 50
WARMUP_RUNS = int(os.environ.get("BENCHMARK_WARMUP_RUNS", "2"))
MEASURED_RUNS = int(os.environ.get("BENCHMARK_RUNS", "10"))


@dataclass(frozen=True)
class BackendCombo:
    database: str
    store_key: str
    store_config: dict[str, Any]
    dense: str
    sparse: str
    sparse_impl: str
    sparse_key: str


@dataclass(frozen=True)
class BenchmarkBatch:
    combo: BackendCombo
    rerank: str


BACKEND_COMBOS = [
    BackendCombo("qdrant", "qdrant", {"url": "http://localhost:6333"}, "bge-base", "bm25", "app", "bm25"),
    BackendCombo("qdrant", "qdrant", {"url": "http://localhost:6333"}, "bge-m3", "bm25", "app", "bm25"),
    BackendCombo("qdrant", "qdrant", {"url": "http://localhost:6333"}, "bge-m3", "bge-m3", "vector", "bge_m3"),
    BackendCombo("chroma", "chroma", {"persist_dir": "chroma_data"}, "bge-base", "bm25", "app", "bm25"),
    BackendCombo("chroma", "chroma", {"persist_dir": "chroma_data"}, "bge-m3", "bm25", "app", "bm25"),
    BackendCombo("milvus-standalone", "milvus", {"uri": "http://localhost:19530"}, "bge-base", "bm25", "app", "bm25"),
    BackendCombo("milvus-standalone", "milvus", {"uri": "http://localhost:19530"}, "bge-m3", "bm25", "app", "bm25"),
    BackendCombo("milvus-standalone", "milvus", {"uri": "http://localhost:19530"}, "bge-m3", "bge-m3", "vector", "bge_m3"),
    BackendCombo("milvus-standalone", "milvus", {"uri": "http://localhost:19530"}, "bge-base", "bm25", "vector", "milvus_bm25"),
    BackendCombo("milvus-standalone", "milvus", {"uri": "http://localhost:19530"}, "bge-m3", "bm25", "vector", "milvus_bm25"),
    BackendCombo("milvus-lite", "milvus_lite", {"uri": "milvus_data/lite/lite.db"}, "bge-base", "bm25", "app", "bm25"),
    BackendCombo("milvus-lite", "milvus_lite", {"uri": "milvus_data/lite/lite.db"}, "bge-m3", "bm25", "app", "bm25"),
    BackendCombo("milvus-lite", "milvus_lite", {"uri": "milvus_data/lite/lite.db"}, "bge-m3", "bge-m3", "vector", "bge_m3"),
    BackendCombo("milvus-lite", "milvus_lite", {"uri": "milvus_data/lite/lite.db"}, "bge-base", "bm25", "vector", "milvus_bm25"),
    BackendCombo("milvus-lite", "milvus_lite", {"uri": "milvus_data/lite/lite.db"}, "bge-m3", "bm25", "vector", "milvus_bm25"),
]

RERANK_MODELS = [value.strip() for value in os.environ.get(
    "BENCHMARK_RERANK",
    "none,bge-reranker-base,bge-reranker-large,bge-reranker-v2-m3",
).split(",") if value.strip()]
QUERY_MODES = ["dense", "sparse", "hybrid"]
DATABASES = ["qdrant", "chroma", "milvus-standalone", "milvus-lite"]


@pytest.mark.parametrize("database", DATABASES)
def test_search_benchmark_matrix(database: str, tmp_path):
    if os.environ.get("RUN_BENCHMARK") != "1":
        pytest.skip("set RUN_BENCHMARK=1 to run long benchmark")
    if not DOCUMENT_PATH.exists():
        pytest.skip(f"benchmark fixture not found: {DOCUMENT_PATH}")

    rows = []
    for batch in _benchmark_batches(database):
        application = _start_application(batch, tmp_path, start_ocr=False)
        try:
            _rebuild_index(application)
            for mode in QUERY_MODES:
                for top_k in TOP_K_VALUES:
                    rows.append(_run_scenario(application, batch, mode, top_k))
        finally:
            application.stop()

    summary = _render_summary(rows)
    _write_summary(summary, database)
    print("\n" + summary)


def _benchmark_batches(database: str) -> list[BenchmarkBatch]:
    return [
        BenchmarkBatch(combo=combo, rerank=rerank)
        for combo in BACKEND_COMBOS
        if combo.database == database and _combo_matches_filter(combo)
        for rerank in RERANK_MODELS
    ]


def _combo_matches_filter(combo: BackendCombo) -> bool:
    return (
        _matches_env_filter("BENCHMARK_DENSE", combo.dense)
        and _matches_env_filter("BENCHMARK_SPARSE", combo.sparse)
        and _matches_env_filter("BENCHMARK_SPARSE_IMPL", combo.sparse_impl)
    )


def _matches_env_filter(name: str, value: str) -> bool:
    values = [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]
    return not values or value in values


def _start_application(batch: BenchmarkBatch, tmp_path: Path, start_ocr: bool = True):
    from bootstrap import Application
    from loader import load_config_file

    combo = batch.combo
    config_path = tmp_path / f"{_slug(combo.database)}_{_slug(combo.dense)}_{_slug(combo.sparse)}_{_slug(combo.sparse_impl)}_{_slug(batch.rerank)}.yaml"
    config_path.write_text(yaml.safe_dump(_config_for(batch, tmp_path), allow_unicode=True, sort_keys=False), encoding="utf-8")
    application = Application(config=load_config_file(config_path))
    application.dense.start()
    application.sparse.start()
    application.store.drop_collections()
    application.store.start()
    application.search.start()
    if batch.rerank != "none":
        application.rerank.start()
    if start_ocr:
        application.ocr.start()
    application.ready = True
    return application


def _rebuild_index(application) -> None:
    from document_parser import parse_file

    application.store.delete_common_document(DOCUMENT_PATH.name, namespace=NAMESPACE)
    chunks = parse_file(str(DOCUMENT_PATH), original_filename=DOCUMENT_PATH.name, ocr=None)
    application.store.add_common_documents(chunks, namespace=NAMESPACE)


def _run_scenario(application, batch: BenchmarkBatch, mode: str, top_k: int) -> dict[str, Any]:
    from search import SearchPlan, _SearchExecutor

    combo = batch.combo
    rerank = batch.rerank != "none"
    plan = SearchPlan(
        QUERY,
        mode=mode,
        top_k=top_k,
        rerank=rerank,
        fetch_k=FETCH_K,
        namespace=NAMESPACE,
        scope_ids=[],
    )

    for _ in range(WARMUP_RUNS):
        _SearchExecutor(plan, rerank=application.rerank, sparse=application.sparse, store=application.store).execute()

    samples = []
    errors = 0
    for _ in range(MEASURED_RUNS):
        started_at = time.perf_counter()
        try:
            _SearchExecutor(plan, rerank=application.rerank, sparse=application.sparse, store=application.store).execute()
        except Exception:
            errors += 1
        else:
            samples.append((time.perf_counter() - started_at) * 1000)

    rank_results = _SearchExecutor(plan, rerank=application.rerank, sparse=application.sparse, store=application.store).execute()
    target_rank = _target_rank(rank_results)
    stats = _stats(samples)
    return {
        "database": combo.database,
        "dense": combo.dense,
        "sparse": combo.sparse,
        "sparse_impl": combo.sparse_impl,
        "mode": mode,
        "rerank": batch.rerank,
        "top_k": top_k,
        "fetch_k": FETCH_K if rerank else "-",
        "warmup_runs": WARMUP_RUNS,
        "runs": MEASURED_RUNS,
        "samples": len(samples),
        "p50_ms": stats["p50"],
        "p95_ms": stats["p95"],
        "p99_ms": stats["p99"],
        "avg_ms": stats["avg"],
        "min_ms": stats["min"],
        "max_ms": stats["max"],
        "errors": errors,
        "target_found": target_rank is not None,
        "target_rank": target_rank or "-",
    }


def _config_for(batch: BenchmarkBatch, tmp_path: Path) -> dict[str, Any]:
    combo = batch.combo
    collection_suffix = f"{_slug(combo.database)}_{_slug(combo.dense)}_{_slug(combo.sparse)}_{_slug(combo.sparse_impl)}"
    store_config = dict(combo.store_config)
    if combo.store_key == "chroma":
        store_config["persist_dir"] = str(tmp_path / "chroma")
    if combo.store_key == "milvus_lite":
        store_config["uri"] = str(tmp_path / "milvus_lite.db")
    store = {
        combo.store_key: {
            "enable": True,
            "import_path": _store_import_path(combo.store_key),
            "collections": {
                "common": f"benchmark_{collection_suffix}_common",
                "scoped": f"benchmark_{collection_suffix}_scoped",
            },
            **store_config,
        }
    }
    dense_model = "bge-m3" if combo.dense == "bge-m3" else "bge-base-zh-v1.5"
    sparse = {
        combo.sparse_key: {
            "enable": True,
            "import_path": _sparse_import_path(combo.store_key, combo.sparse_key),
        }
    }
    if combo.sparse == "bm25":
        sparse[combo.sparse_key]["tokenizer"] = "jieba"
    elif combo.sparse == "bge-m3":
        sparse[combo.sparse_key]["model_name"] = "bge-m3"
    rerank_model = "bge-reranker-base" if batch.rerank == "none" else batch.rerank

    return {
        "logging": {
            "level": "WARNING",
            "max_bytes": 10485760,
            "backup_count": 5,
            "search_trace": False,
        },
        "store": store,
        "dense": {
            "bge_m3" if combo.dense == "bge-m3" else "bge_base": {
                "enable": True,
                "model_name": dense_model,
                "import_path": "dense.huggingface.HuggingFaceDense",
            }
        },
        "sparse": sparse,
        "search": {
            "default_mode": "hybrid",
            "top_k": 20,
            "fetch_k": FETCH_K,
            "dense_weight": 0.5,
            "sparse_weight": 0.5,
            "rrf_k": 60,
        },
        "rerank": {
            _rerank_key(rerank_model): {
                "enable": True,
                "model_name": rerank_model,
                "import_path": "rerank.cross_encoder.CrossEncoderRerank",
            }
        },
        "ocr": {
            "rapid": {
                "enable": True,
                "model_name": "rapidocr",
                "import_path": "ocr.rapid.RapidOCR",
            }
        },
    }


def _target_rank(results: list[dict]) -> int | None:
    normalized_target = _normalize(TARGET_TEXT)
    for index, result in enumerate(results, start=1):
        if normalized_target in _normalize(result.get("content", "")):
            return index
    return None


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", str(text)).split())


def _stats(values: list[float]) -> dict[str, float | str]:
    if not values:
        return {"p50": "-", "p95": "-", "p99": "-", "avg": "-", "min": "-", "max": "-"}
    values = sorted(values)
    return {
        "p50": round(_percentile(values, 50), 1),
        "p95": round(_percentile(values, 95), 1),
        "p99": round(_percentile(values, 99), 1),
        "avg": round(sum(values) / len(values), 1),
        "min": round(values[0], 1),
        "max": round(values[-1], 1),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[int(position)]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _render_summary(rows: list[dict[str, Any]]) -> str:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    columns = [
        "database", "dense", "sparse", "sparse_impl", "mode", "rerank", "top_k", "fetch_k",
        "warmup_runs", "runs", "samples", "p50_ms", "p95_ms", "p99_ms",
        "avg_ms", "min_ms", "max_ms", "errors", "target_found", "target_rank",
    ]
    lines = [
        "# Search Benchmark Summary",
        "",
        f"- generated_at: {generated_at}",
        f"- document: {DOCUMENT_PATH.name}",
        f"- query: {QUERY}",
        f"- target_text: {TARGET_TEXT}",
        f"- scenario_count: {len(rows)}",
        "",
        _markdown_row(columns),
        _markdown_row(["---"] * len(columns)),
    ]
    lines.extend(_markdown_row([row[column] for column in columns]) for row in rows)
    return "\n".join(lines) + "\n"


def _write_summary(summary: str, database: str) -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    database_summary_path = RESULTS_DIR / f"search_benchmark_{_slug(database)}_summary.md"
    database_summary_path.write_text(summary, encoding="utf-8")


def _markdown_row(values) -> str:
    return "| " + " | ".join(str(value) for value in values) + " |"


def _rerank_key(model_name: str) -> str:
    return {
        "bge-reranker-base": "bge_base",
        "bge-reranker-large": "bge_large",
        "bge-reranker-v2-m3": "bge_m3",
    }[model_name]


def _store_import_path(store_key: str) -> str:
    if store_key in ("milvus", "milvus_lite"):
        return "store.milvus.MilvusStore"
    return {
        "qdrant": "store.qdrant.QdrantStore",
        "chroma": "store.chroma.ChromaStore",
    }[store_key]


def _sparse_import_path(store_key: str, sparse_key: str) -> str:
    if sparse_key == "bm25":
        return "sparse.bm25.BM25Sparse"
    if sparse_key == "milvus_bm25":
        return "sparse.milvus_bm25.MilvusBM25Sparse"
    if store_key == "qdrant":
        return "sparse.qdrant_bge_m3.QdrantBGEM3Sparse"
    if store_key in ("milvus", "milvus_lite"):
        return "sparse.milvus_bge_m3.MilvusBGEM3Sparse"
    raise ValueError(f"unsupported sparse benchmark combination: {store_key} {sparse_key}")


def _slug(value: str) -> str:
    return value.replace("-", "_").replace("+", "_").replace("/", "_")
