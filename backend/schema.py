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


SparseConfig = SparseBackendConfig


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
class AdminAuthConfig:
    username: str
    password: str


@dataclass(frozen=True)
class AppAuthConfig:
    app_id: str
    access_key: str
    secret_key: str


@dataclass(frozen=True)
class AuthConfig:
    admin: AdminAuthConfig
    app: AppAuthConfig


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
    auth: AuthConfig
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
    auth = raw.get("auth") or {}
    rerank = raw.get("rerank")
    ocr = raw.get("ocr")
    auth_admin = auth.get("admin") or {}
    auth_app = auth.get("app") or {}

    store_type = _required(store, "type", "store")
    dense_name = _component_name(dense, "dense")
    sparse_config = _parse_sparse_backend(sparse, "sparse")
    sparse_name = sparse_config.name
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
    if store_type in ("chroma", "store/chroma") and sparse_config.name in ("bge_m3", "milvus_bm25", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3", "sparse/milvus_bm25"):
        raise ValueError("Chroma 不支持 bge_m3 sparse")
    sparse_model_path = _required(sparse_config.__dict__, "model_path", "sparse") if sparse_config.name in ("bge_m3", "sparse/qdrant_bge_m3", "sparse/milvus_bge_m3") else None
    if sparse_model_path is not None:
        sparse_config = SparseBackendConfig(
            name=sparse_config.name,
            model_path=sparse_model_path,
            model_name=sparse_config.model_name,
            tokenizer=sparse_config.tokenizer,
            import_path=sparse_config.import_path,
        )

    return AppConfig(
        dense=DenseConfig(
            name=dense_name,
            model_path=_required(dense, "model_path", "dense"),
            model_name=dense.get("model_name"),
            import_path=dense.get("import_path"),
        ),
        sparse=SparseConfig(
            name=sparse_config.name,
            model_path=sparse_config.model_path,
            model_name=sparse_config.model_name,
            tokenizer=sparse_config.tokenizer,
            import_path=sparse_config.import_path,
        ),
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
        auth=AuthConfig(
            admin=AdminAuthConfig(
                username=str(auth_admin.get("username", "admin")),
                password=str(auth_admin.get("password", "admin123")),
            ),
            app=AppAuthConfig(
                app_id=str(auth_app.get("app_id", "imsdom")),
                access_key=str(auth_app.get("access_key", "0d01c6bc9577a6dae3095cb7972a9f8c")),
                secret_key=str(auth_app.get("secret_key", "78ddbd0730125b050b607c81c8398c4fe96f707cfa66f222d42a8eeae3aa47e6")),
            ),
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


def _parse_sparse_backend(value: Any, section_name: str) -> SparseBackendConfig:
    if not isinstance(value, dict):
        raise ValueError("sparse is required")
    if "app" in value or "vector" in value:
        raise ValueError("sparse must define exactly one backend")
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
