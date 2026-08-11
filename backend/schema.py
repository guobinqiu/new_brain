from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DenseConfig:
    name: str
    model_path: str
    import_path: str | None = None


@dataclass(frozen=True)
class SparseConfig:
    name: str
    model_path: str | None = None
    tokenizer: str | None = None
    import_path: str | None = None


@dataclass(frozen=True)
class StoreCollectionsConfig:
    common: str
    scoped: str


@dataclass(frozen=True)
class StoreConfig:
    type: str
    collections: StoreCollectionsConfig
    url: str | None = None
    persist_dir: str | None = None
    uri: str | None = None
    timeout: int = 30
    import_path: str | None = None


@dataclass(frozen=True)
class SearchConfig:
    default_mode: str = "hybrid"
    top_k: int = 20
    fetch_k: int = 100
    dense_weight: float = 0.5
    sparse_weight: float = 0.5
    rrf_k: int = 60


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: str | None = None
    max_bytes: int = 10485760
    backup_count: int = 5
    search_trace: bool = True


@dataclass(frozen=True)
class RerankConfig:
    name: str
    model_path: str
    import_path: str | None = None


@dataclass(frozen=True)
class OCRConfig:
    name: str
    model_path: str
    import_path: str | None = None


@dataclass(frozen=True)
class AppConfig:
    dense: DenseConfig
    sparse: SparseConfig
    store: StoreConfig
    search: SearchConfig
    rerank: RerankConfig | None
    ocr: OCRConfig
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    name: str = ""


def parse_app_config(raw: dict[str, Any]) -> AppConfig:
    dense = raw.get("dense") or {}
    sparse = raw.get("sparse") or {}
    store = raw.get("store") or {}
    collections = store.get("collections") or {}
    search = raw.get("search") or {}
    logging = raw.get("logging") or {}
    rerank = raw.get("rerank")
    ocr = raw.get("ocr")

    store_type = _required(store, "type", "store")
    dense_name = _component_name(dense, "dense")
    sparse_name = _sparse_name(sparse)
    rerank_name = _component_name(rerank, "rerank") if rerank is not None else None
    ocr_name = _component_name(ocr, "ocr")
    _validate_supported("dense", dense_name, {"test_dense", "bge_base", "bge_base_zh_v15", "bge_m3", "dense/huggingface"})
    _validate_supported("sparse", sparse_name, {"bm25", "bge_m3", "milvus_bm25", "sparse/bm25", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3", "sparse/milvus_bm25"})
    if rerank_name is not None:
        _validate_supported("rerank", rerank_name, {"test_rerank", "bge_base", "bge_large", "bge_m3", "bge_reranker_base", "bge_reranker_large", "bge_reranker_v2_m3", "rerank/cross_encoder"})
    _validate_supported("ocr", ocr_name, {"test_ocr", "rapid", "paddle", "rapidocr", "paddleocr", "tesseract", "ocr/rapid", "ocr/paddle", "ocr/tesseract"})
    _validate_supported("store.type", store_type, {"qdrant", "chroma", "milvus", "milvus_lite", "store/qdrant", "store/chroma", "store/milvus"})
    _validate_supported("search.default_mode", search.get("default_mode", "hybrid"), {"dense", "sparse", "hybrid"})
    if store_type in ("qdrant", "store/qdrant"):
        _required(store, "url", "store")
    if store_type in ("chroma", "store/chroma"):
        _required(store, "persist_dir", "store")
    if store_type in ("milvus", "milvus_lite", "store/milvus"):
        _required(store, "uri", "store")
    if store_type in ("chroma", "store/chroma") and sparse_name == "bge_m3":
        raise ValueError("Chroma 不支持 bge_m3 sparse")
    sparse_model_path = _required(sparse, "model_path", "sparse") if sparse_name in ("bge_m3", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3") else None

    return AppConfig(
        dense=DenseConfig(
            name=dense_name,
            model_path=_required(dense, "model_path", "dense"),
            import_path=dense.get("import_path"),
        ),
        sparse=SparseConfig(
            name=sparse_name,
            model_path=sparse_model_path,
            tokenizer=sparse.get("tokenizer"),
            import_path=sparse.get("import_path"),
        ),
        store=StoreConfig(
            type=store_type,
            url=store.get("url"),
            persist_dir=store.get("persist_dir"),
            uri=store.get("uri"),
            timeout=int(store.get("timeout", 30)),
            import_path=store.get("import_path"),
            collections=StoreCollectionsConfig(
                common=_required(collections, "common", "store.collections"),
                scoped=_required(collections, "scoped", "store.collections"),
            ),
        ),
        search=SearchConfig(
            default_mode=search.get("default_mode", "hybrid"),
            top_k=int(search.get("top_k", 20)),
            fetch_k=int(search.get("fetch_k", 100)),
            dense_weight=float(search.get("dense_weight", 0.5)),
            sparse_weight=float(search.get("sparse_weight", 0.5)),
            rrf_k=int(search.get("rrf_k", 60)),
        ),
        logging=LoggingConfig(
            level=str(logging.get("level", "INFO")),
            file=logging.get("file"),
            max_bytes=int(logging.get("max_bytes", 10485760)),
            backup_count=int(logging.get("backup_count", 5)),
            search_trace=bool(logging.get("search_trace", True)),
        ),
        rerank=RerankConfig(
            name=rerank_name,
            model_path=_required(rerank, "model_path", "rerank"),
            import_path=rerank.get("import_path"),
        ) if rerank is not None else None,
        ocr=OCRConfig(
            name=ocr_name,
            model_path=_required(ocr, "model_path", "ocr"),
            import_path=ocr.get("import_path"),
        ),
    )


def _component_name(value: Any, section_name: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{section_name} is required")
    name = value.get("name")
    if name is None:
        raise ValueError(f"{section_name}.name is required")
    return name


def _sparse_name(value: Any) -> str:
    if isinstance(value, dict):
        name = value.get("type") or value.get("name")
        if name is None:
            raise ValueError("sparse.type is required")
        return name
    raise ValueError("sparse is required")


def _required(section: dict[str, Any], key: str, section_name: str) -> Any:
    value = section.get(key)
    if value is None:
        raise ValueError(f"{section_name}.{key} is required")
    return value


def _validate_supported(name: str, value: str, supported: set[str]) -> None:
    if value not in supported:
        raise ValueError(f"unsupported {name}: {value}")
