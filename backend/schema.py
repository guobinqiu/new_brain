from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DenseConfig:
    name: str
    model_path: str
    model_name: str | None = None
    import_path: str | None = None


@dataclass(frozen=True)
class SparseBackendConfig:
    name: str
    model_path: str | None = None
    model_name: str | None = None
    tokenizer: str | None = None
    import_path: str | None = None


@dataclass(frozen=True)
class SparseConfig:
    app: SparseBackendConfig
    vector: SparseBackendConfig | None = None

    @property
    def name(self) -> str:
        return self.app.name

    @property
    def model_path(self) -> str | None:
        return self.app.model_path

    @property
    def tokenizer(self) -> str | None:
        return self.app.tokenizer

    @property
    def import_path(self) -> str | None:
        return self.app.import_path


@dataclass(frozen=True)
class StoreCollectionsConfig:
    chunks: str


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
    model_name: str | None = None
    import_path: str | None = None


@dataclass(frozen=True)
class OCRConfig:
    name: str
    model_path: str
    model_name: str | None = None
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
    available_components: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
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
    sparse_app = _parse_sparse_app(sparse)
    sparse_vector = _parse_sparse_vector(sparse)
    sparse_name = sparse_app.name
    rerank_name = _component_name(rerank, "rerank") if rerank is not None else None
    ocr_name = _component_name(ocr, "ocr")
    _validate_supported("dense", dense_name, {"test_dense", "bge_base", "bge_base_zh_v15", "bge_m3", "dense/huggingface"})
    _validate_supported("sparse", sparse_name, {"bm25", "bge_m3", "milvus_bm25", "sparse/bm25", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3", "sparse/milvus_bm25"})
    if sparse_vector is not None:
        _validate_supported("sparse.vector", sparse_vector.name, {"bge_m3", "milvus_bm25", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3", "sparse/milvus_bm25"})
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
    if store_type in ("chroma", "store/chroma") and sparse_vector is not None:
        raise ValueError("Chroma 不支持 bge_m3 sparse")
    sparse_app_model_path = _required(sparse_app.__dict__, "model_path", "sparse.app") if sparse_app.name in ("bge_m3", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3") else None
    sparse_vector_model_path = (
        _required(sparse_vector.__dict__, "model_path", "sparse.vector")
        if sparse_vector is not None and sparse_vector.name in ("bge_m3", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3")
        else None
    )
    if sparse_app_model_path is not None:
        sparse_app = SparseBackendConfig(
            name=sparse_app.name,
            model_path=sparse_app_model_path,
            model_name=sparse_app.model_name,
            tokenizer=sparse_app.tokenizer,
            import_path=sparse_app.import_path,
        )
    if sparse_vector is not None and sparse_vector_model_path is not None:
        sparse_vector = SparseBackendConfig(
            name=sparse_vector.name,
            model_path=sparse_vector_model_path,
            model_name=sparse_vector.model_name,
            tokenizer=sparse_vector.tokenizer,
            import_path=sparse_vector.import_path,
        )

    return AppConfig(
        dense=DenseConfig(
            name=dense_name,
            model_path=_required(dense, "model_path", "dense"),
            model_name=dense.get("model_name"),
            import_path=dense.get("import_path"),
        ),
        sparse=SparseConfig(app=sparse_app, vector=sparse_vector),
        store=StoreConfig(
            type=store_type,
            url=store.get("url"),
            persist_dir=store.get("persist_dir"),
            uri=store.get("uri"),
            timeout=int(store.get("timeout", 30)),
            import_path=store.get("import_path"),
            collections=StoreCollectionsConfig(
                chunks=_required(collections, "chunks", "store.collections"),
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
            model_name=rerank.get("model_name"),
            import_path=rerank.get("import_path"),
        ) if rerank is not None else None,
        ocr=OCRConfig(
            name=ocr_name,
            model_path=_required(ocr, "model_path", "ocr"),
            model_name=ocr.get("model_name"),
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


def _parse_sparse_app(value: Any) -> SparseBackendConfig:
    if isinstance(value, dict) and "app" in value:
        app = value.get("app")
        if not isinstance(app, dict):
            raise ValueError("sparse.app is required")
        return _parse_sparse_backend(app, "sparse.app")
    if isinstance(value, dict) and "vector" in value:
        raise ValueError("sparse.app is required")
    if isinstance(value, dict):
        return _parse_sparse_backend(value, "sparse")
    raise ValueError("sparse.app is required")


def _parse_sparse_vector(value: Any) -> SparseBackendConfig | None:
    if not isinstance(value, dict) or "vector" not in value:
        return None
    vector = value.get("vector")
    if vector is None:
        return None
    if not isinstance(vector, dict):
        raise ValueError("sparse.vector must be an object")
    return _parse_sparse_backend(vector, "sparse.vector")


def _parse_sparse_backend(value: dict[str, Any], section_name: str) -> SparseBackendConfig:
    name = value.get("type") or value.get("name")
    if name is None:
        raise ValueError(f"{section_name}.type is required")
    return SparseBackendConfig(
        name=name,
        model_path=value.get("model_path"),
        model_name=value.get("model_name"),
        tokenizer=value.get("tokenizer"),
        import_path=value.get("import_path"),
    )


def _required(section: dict[str, Any], key: str, section_name: str) -> Any:
    value = section.get(key)
    if value is None:
        raise ValueError(f"{section_name}.{key} is required")
    return value


def _validate_supported(name: str, value: str, supported: set[str]) -> None:
    if value not in supported:
        raise ValueError(f"unsupported {name}: {value}")
