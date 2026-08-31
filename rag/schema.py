from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


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
class StoreConfig:
    type: str
    url: str | None = None
    persist_dir: str | None = None
    uri: str | None = None
    timeout: int = 30
    import_path: str | None = None


@dataclass(frozen=True)
class DatabaseConfig:
    type: str
    url: str
    pool_size: int = 5
    import_path: str | None = None


@dataclass(frozen=True)
class SearchConfig:
    default_mode: str = "hybrid"
    top_k: int = 5
    fetch_k: int = 20
    dense_weight: float = 0.5
    sparse_weight: float = 0.5
    rrf_k: int = 60


EmbeddingReleasePolicy = Literal["per_batch", "after_call", "never"]
ParserType = Literal["mineru", "unstructured"]
ParserStrategy = Literal["auto", "fast", "hi_res"]


@dataclass(frozen=True)
class EmbeddingConfig:
    dense_batch_size: int = 4
    sparse_batch_size: int = 4
    release_memory: EmbeddingReleasePolicy = "per_batch"


@dataclass(frozen=True)
class TextParserConfig:
    chunk_size: int = 500
    chunk_overlap: int = 80


@dataclass(frozen=True)
class TableParserConfig:
    header_backward_chars: int = 160
    footer_forward_chars: int = 160


@dataclass(frozen=True)
class MineruParserConfig:
    enable: bool = True
    text: TextParserConfig = field(default_factory=TextParserConfig)
    table: TableParserConfig = field(default_factory=TableParserConfig)


@dataclass(frozen=True)
class UnstructuredParserConfig:
    enable: bool = False
    strategy: ParserStrategy = "hi_res"
    infer_table_structure: bool = True
    languages: list[str] = field(default_factory=lambda: ["chi_sim", "eng"])
    text: TextParserConfig = field(default_factory=TextParserConfig)
    table: TableParserConfig = field(default_factory=TableParserConfig)


@dataclass(frozen=True, init=False)
class ParserConfig:
    mineru: MineruParserConfig = field(default_factory=MineruParserConfig)
    unstructured: UnstructuredParserConfig = field(default_factory=UnstructuredParserConfig)

    def __init__(
        self,
        mineru: MineruParserConfig | None = None,
        unstructured: UnstructuredParserConfig | None = None,
    ):
        mineru_config = mineru or MineruParserConfig()
        unstructured_config = unstructured or UnstructuredParserConfig()
        _validate_single_parser_enabled(mineru_config, unstructured_config)
        object.__setattr__(self, "mineru", mineru_config)
        object.__setattr__(self, "unstructured", unstructured_config)

    @property
    def enabled_parser(self) -> ParserType:
        if self.mineru.enable:
            return "mineru"
        return "unstructured"


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: str | None = None
    max_bytes: int = 10485760
    backup_count: int = 5
    search_trace: bool = True


@dataclass(frozen=True)
class ApiConfig:
    rate_limit: str = "120/minute"
    rate_limit_index: str = "10/minute"


@dataclass(frozen=True)
class AdminAuthConfig:
    username: str
    password: str


@dataclass(frozen=True)
class AuthConfig:
    admin: AdminAuthConfig
    registry_file: str | None = None


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
    database: DatabaseConfig
    search: SearchConfig
    rerank: RerankConfig | None
    ocr: OCRConfig
    auth: AuthConfig
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    available_components: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    name: str = ""


def parse_app_config(raw: dict[str, Any]) -> AppConfig:
    dense = raw.get("dense") or {}
    sparse = raw.get("sparse") or {}
    store = raw.get("store") or {}
    database = raw.get("database") or {}
    search = raw.get("search") or {}
    parser = raw.get("parser") or {}
    embedding = raw.get("embedding") or {}
    logging = raw.get("logging") or {}
    api = raw.get("api") or {}
    auth = raw.get("auth") or {}
    rerank = raw.get("rerank")
    ocr = raw.get("ocr")
    auth_admin = auth.get("admin") or {}

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
    database_name = database.get("type") or database.get("name")
    if database_name is None:
        raise ValueError("database.type is required")
    _validate_supported("database.type", database_name, {"postgres", "database/postgres"})
    _required(database, "url", "database")
    _validate_supported("search.default_mode", search.get("default_mode", "hybrid"), {"dense", "sparse", "hybrid"})
    _validate_supported("embedding.release_memory", embedding.get("release_memory", "per_batch"), {"per_batch", "after_call", "never"})
    parser_config = _parse_parser_config(parser)
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
        ),
        database=DatabaseConfig(
            type=database_name,
            url=_required(database, "url", "database"),
            pool_size=int(database.get("pool_size", 5)),
            import_path=database.get("import_path"),
        ),
        search=SearchConfig(
            default_mode=search.get("default_mode", "hybrid"),
            top_k=int(search.get("top_k", 5)),
            fetch_k=int(search.get("fetch_k", 20)),
            dense_weight=float(search.get("dense_weight", 0.5)),
            sparse_weight=float(search.get("sparse_weight", 0.5)),
            rrf_k=int(search.get("rrf_k", 60)),
        ),
        embedding=EmbeddingConfig(
            dense_batch_size=int(embedding.get("dense_batch_size", 4)),
            sparse_batch_size=int(embedding.get("sparse_batch_size", 4)),
            release_memory=embedding.get("release_memory", "per_batch"),
        ),
        parser=parser_config,
        logging=LoggingConfig(
            level=str(logging.get("level", "INFO")),
            file=logging.get("file"),
            max_bytes=int(logging.get("max_bytes", 10485760)),
            backup_count=int(logging.get("backup_count", 5)),
            search_trace=bool(logging.get("search_trace", True)),
        ),
        api=ApiConfig(
            rate_limit=str(api.get("rate_limit", "120/minute")),
            rate_limit_index=str(api.get("rate_limit_index", "10/minute")),
        ),
        auth=AuthConfig(
            admin=AdminAuthConfig(
                username=str(auth_admin.get("username", "admin")),
                password=str(auth_admin.get("password", "admin123")),
            ),
            registry_file=auth.get("registry_file"),
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


def _parse_parser_config(parser: dict[str, Any]) -> ParserConfig:
    mineru = parser.get("mineru") or {}
    unstructured = parser.get("unstructured") or {}
    _validate_supported("parser.unstructured.strategy", unstructured.get("strategy", "hi_res"), {"auto", "fast", "hi_res"})
    return ParserConfig(
        mineru=MineruParserConfig(
            enable=_bool(mineru.get("enable", True)),
            text=_parse_text_parser_config(mineru),
            table=_parse_table_parser_config(mineru),
        ),
        unstructured=UnstructuredParserConfig(
            enable=_bool(unstructured.get("enable", False)),
            strategy=unstructured.get("strategy", "hi_res"),
            infer_table_structure=_bool(unstructured.get("infer_table_structure", True)),
            languages=list(unstructured.get("languages", ["chi_sim", "eng"])),
            text=_parse_text_parser_config(unstructured),
            table=_parse_table_parser_config(unstructured),
        ),
    )


def _parse_text_parser_config(parser: dict[str, Any]) -> TextParserConfig:
    parser_text = parser.get("text") or {}
    return TextParserConfig(
        chunk_size=int(parser_text.get("chunk_size", 500)),
        chunk_overlap=int(parser_text.get("chunk_overlap", 80)),
    )


def _parse_table_parser_config(parser: dict[str, Any]) -> TableParserConfig:
    parser_table = parser.get("table") or {}
    return TableParserConfig(
        header_backward_chars=int(parser_table.get("header_backward_chars", 160)),
        footer_forward_chars=int(parser_table.get("footer_forward_chars", 160)),
    )


def _validate_single_parser_enabled(mineru: MineruParserConfig, unstructured: UnstructuredParserConfig) -> None:
    enabled_count = int(mineru.enable) + int(unstructured.enable)
    if enabled_count != 1:
        raise ValueError("parser must enable exactly one backend")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"invalid boolean value: {value}")


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
