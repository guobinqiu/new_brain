from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    interval_seconds: float = 0.5


@dataclass(frozen=True)
class DenseConfig:
    name: str
    model_path: str | None = None
    model_name: str | None = None
    batch_size: int = 4
    release_memory: EmbeddingReleasePolicy = "per_batch"


@dataclass(frozen=True)
class SparseConfig:
    name: str
    model_path: str | None = None
    model_name: str | None = None
    batch_size: int = 4
    release_memory: EmbeddingReleasePolicy = "per_batch"


@dataclass(frozen=True)
class QdrantQuantizationConfig:
    enable: bool = False
    type: str = "int8"
    quantile: float | None = None
    always_ram: bool | None = None


@dataclass(frozen=True)
class VectorServiceConfig:
    provider: str
    base_url: str | None = None
    timeout: int = 30
    query_timeout: int = 10
    write_timeout: int = 60
    init_timeout: int = 120
    drop_timeout: int = 180
    retry: RetryConfig = field(default_factory=RetryConfig)
    quantization: QdrantQuantizationConfig | None = None
    api_key: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class TimeoutConfig:
    timeout: int = 60


@dataclass(frozen=True)
class SearchConfig:
    mode: str = "dense"
    top_k: int = 5
    rerank_fetch_k: int = 20
    rerank: bool = False
    rrf_k: int = 60


EmbeddingReleasePolicy = Literal["per_batch", "after_call", "never"]


@dataclass(frozen=True)
class TextParserConfig:
    chunk_size: int = 500
    chunk_overlap: int = 80


@dataclass(frozen=True)
class MineruParserConfig:
    enable: bool = False
    tier: str = "basic"
    parse_method: str = "auto"
    image_analysis: bool = False


@dataclass(frozen=True)
class MineruCloudParserConfig:
    enable: bool = False
    base_url: str = "https://mineru.net"
    timeout: int = 300
    model_version: str = "vlm"
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "ch"
    retry: RetryConfig = field(default_factory=RetryConfig)
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ChunkingConfig:
    text: TextParserConfig = field(default_factory=TextParserConfig)


@dataclass(frozen=True)
class VolcengineParserConfig:
    enable: bool = False
    model: str | None = None
    prompt: str | None = None
    thinking: bool = False
    stream: bool = False
    service_tier: str = "auto"
    timeout: int = 300
    base_url: str | None = None
    retry: RetryConfig = field(default_factory=RetryConfig)
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True, init=False)
class ParserConfig:
    download_timeout: int = 60
    mineru: MineruParserConfig = field(default_factory=MineruParserConfig)
    mineru_cloud: MineruCloudParserConfig = field(default_factory=MineruCloudParserConfig)
    active: str = "mineru"
    volcengine: VolcengineParserConfig = field(default_factory=VolcengineParserConfig)

    def __init__(
        self,
        active: str = "mineru",
        volcengine: VolcengineParserConfig | None = None,
        download_timeout: int = 60,
        mineru_cloud: MineruCloudParserConfig | None = None,
        mineru: MineruParserConfig | None = None,
    ):
        object.__setattr__(self, "download_timeout", download_timeout)
        object.__setattr__(self, "mineru", mineru or MineruParserConfig())
        object.__setattr__(self, "mineru_cloud", mineru_cloud or MineruCloudParserConfig())
        object.__setattr__(self, "active", active)
        object.__setattr__(self, "volcengine", volcengine or VolcengineParserConfig())


@dataclass(frozen=True)
class ServiceClientConfig:
    base_url: str | None = None
    timeout: int = 60
    api_key: str | None = field(default=None, repr=False)
    provider: str = "internal"
    embedding: TimeoutConfig = field(default_factory=TimeoutConfig)
    rerank: TimeoutConfig = field(default_factory=TimeoutConfig)


@dataclass(frozen=True)
class ServiceClientsConfig:
    parser: ServiceClientConfig = field(default_factory=ServiceClientConfig)
    inference: ServiceClientConfig = field(default_factory=ServiceClientConfig)
    vector: VectorServiceConfig | None = None


@dataclass(frozen=True)
class DatabaseConfig:
    provider: str
    url: str
    pool_size: int = 5
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: str | None = None
    max_bytes: int = 10485760
    backup_count: int = 5
    search_trace: bool = True
    loki_url: str | None = None


@dataclass(frozen=True)
class StorageConfig:
    endpoint_url: str | None = None
    bucket: str = "rag"
    download_timeout: int = 60


@dataclass(frozen=True)
class BatchIndexConfig:
    base_url: str = "http://rag:6000"
    max_files: int = 10
    max_concurrency: int = 5


@dataclass(frozen=True)
class ApiConfig:
    rate_limit: str = "120/minute"
    rate_limit_index: str = "10/minute"
    index_timeout: float = 780.0
    batch_index: BatchIndexConfig = field(default_factory=BatchIndexConfig)


@dataclass(frozen=True)
class AdminAuthConfig:
    username: str
    password: str = field(repr=False)


@dataclass(frozen=True)
class AppCredential:
    app_id: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class AuthConfig:
    admin: AdminAuthConfig
    apps: list[AppCredential] = field(default_factory=list)


@dataclass(frozen=True)
class RerankConfig:
    name: str
    model_path: str | None = None
    model_name: str | None = None


@dataclass(frozen=True)
class AppConfig:
    search: SearchConfig
    auth: AuthConfig
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    services: ServiceClientsConfig = field(default_factory=ServiceClientsConfig)
    database: DatabaseConfig | None = None
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    available_components: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    name: str = ""


def parse_app_config(raw: dict[str, Any]) -> AppConfig:
    search = raw.get("search") or {}
    services = raw.get("services") or {}
    services_config = _parse_service_clients_config(services)
    database = raw.get("database") or {}
    logging = raw.get("logging") or {}
    storage = raw.get("storage") or {}
    api = raw.get("api") or {}
    batch_index = api.get("batch_index") or {}
    auth = raw.get("auth") or {}
    auth_admin = auth.get("admin") or {}

    if services_config.vector is None:
        raise ValueError("services.vector is required")
    return AppConfig(
        search=SearchConfig(
            mode=str(search.get("mode", "dense")),
            top_k=int(search.get("top_k", 5)),
            rerank_fetch_k=int(search.get("rerank_fetch_k", 20)),
            rerank=_bool(search.get("rerank", False)),
            rrf_k=int((search.get("hybrid") or {}).get("rrf_k", search.get("rrf_k", 60))),
        ),
        chunking=_parse_chunking_config(raw.get("chunking") or {}),
        services=services_config,
        database=_parse_database_config(database) if database else None,
        logging=LoggingConfig(
            level=str(logging.get("level", "INFO")),
            file=logging.get("file"),
            max_bytes=int(logging.get("max_bytes", 10485760)),
            backup_count=int(logging.get("backup_count", 5)),
            search_trace=bool(logging.get("search_trace", True)),
            loki_url=logging.get("loki_url"),
        ),
        storage=StorageConfig(
            endpoint_url=storage.get("endpoint_url"),
            bucket=str(storage.get("bucket", "rag")),
            download_timeout=int(storage.get("download_timeout", 60)),
        ),
        api=ApiConfig(
            rate_limit=str(api.get("rate_limit", "120/minute")),
            rate_limit_index=str(api.get("rate_limit_index", "10/minute")),
            index_timeout=float(api.get("index_timeout", 780.0)),
            batch_index=BatchIndexConfig(
                base_url=str(batch_index.get("base_url", "http://rag:6000")),
                max_files=int(batch_index.get("max_files", 10)),
                max_concurrency=int(batch_index.get("max_concurrency", 5)),
            ),
        ),
        auth=AuthConfig(
            admin=AdminAuthConfig(
                username=str(auth_admin.get("username", "admin")),
                password=str(auth_admin.get("password", "")),
            ),
            apps=[AppCredential(app_id=app["app_id"], api_key=app["api_key"]) for app in auth.get("apps", [])],
        ),
    )


def _parse_chunking_config(raw: dict[str, Any]) -> ChunkingConfig:
    text = raw.get("text") or {}
    return ChunkingConfig(
        text=TextParserConfig(
            chunk_size=int(text.get("chunk_size", 500)),
            chunk_overlap=int(text.get("chunk_overlap", 80)),
        ),
    )


def _parse_qdrant_quantization(quantization) -> QdrantQuantizationConfig | None:
    if not isinstance(quantization, dict):
        return None
    return QdrantQuantizationConfig(
        enable=_bool(quantization.get("enable", False)),
        type=str(quantization.get("type", "int8")),
        quantile=float(quantization["quantile"]) if quantization.get("quantile") is not None else None,
        always_ram=_bool(quantization["always_ram"]) if quantization.get("always_ram") is not None else None,
    )


def _parse_service_clients_config(raw: dict[str, Any]) -> ServiceClientsConfig:
    vector = raw.get("vector")
    for name, supported in (("parser", {"internal"}), ("inference", {"internal"})):
        provider = (raw.get(name) or {}).get("provider", "internal")
        _validate_supported(f"services.{name}.provider", provider, supported)
    return ServiceClientsConfig(
        parser=_parse_service_client_config(raw.get("parser") or {}),
        inference=_parse_service_client_config(raw.get("inference") or {}),
        vector=_parse_vector_service_config(vector) if isinstance(vector, dict) else None,
    )


def _parse_service_client_config(raw: dict[str, Any]) -> ServiceClientConfig:
    _required(raw, "base_url", "services")
    timeout = int(raw.get("timeout", 60))
    return ServiceClientConfig(
        base_url=raw.get("base_url"),
        timeout=timeout,
        api_key=raw.get("api_key"),
        provider=str(raw.get("provider", "internal")),
        embedding=_parse_timeout_config(raw.get("embedding"), timeout),
        rerank=_parse_timeout_config(raw.get("rerank"), timeout),
    )


def _parse_timeout_config(raw: Any, default_timeout: int) -> TimeoutConfig:
    if not isinstance(raw, dict):
        return TimeoutConfig(timeout=default_timeout)
    return TimeoutConfig(timeout=int(raw.get("timeout", default_timeout)))


def _parse_vector_service_config(raw: dict[str, Any]) -> VectorServiceConfig:
    provider = str(_required(raw, "provider", "services.vector"))
    _validate_supported("services.vector.provider", provider, {"qdrant", "milvus", "qdrant_cloud", "milvus_cloud"})
    _required(raw, "base_url", "services.vector")
    timeout = int(raw.get("timeout", 30))
    return VectorServiceConfig(
        provider=provider.removesuffix("_cloud"),
        base_url=raw.get("base_url"),
        timeout=timeout,
        query_timeout=int(raw.get("query_timeout", timeout)),
        write_timeout=int(raw.get("write_timeout", timeout)),
        init_timeout=int(raw.get("init_timeout", timeout)),
        drop_timeout=int(raw.get("drop_timeout", timeout)),
        retry=_parse_retry_config(raw.get("retry")),
        quantization=_parse_qdrant_quantization(raw.get("quantization")),
        api_key=raw.get("api_key"),
        token=raw.get("token"),
    )


def _parse_database_config(raw: dict[str, Any]) -> DatabaseConfig:
    provider = str(_required(raw, "provider", "database"))
    _validate_supported("database.provider", provider, {"postgres"})
    return DatabaseConfig(
        provider=provider,
        url=str(_required(raw, "url", "database")),
        pool_size=int(raw.get("pool_size", 5)),
        retry=_parse_retry_config(raw.get("retry")),
    )


def _parse_retry_config(raw: Any) -> RetryConfig:
    if raw is None:
        return RetryConfig()
    if not isinstance(raw, dict):
        raise ValueError("retry config must be an object")
    return RetryConfig(
        max_attempts=max(1, int(raw.get("max_attempts", 3))),
        interval_seconds=max(0.0, float(raw.get("interval_seconds", 0.5))),
    )


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


def _required(section: dict[str, Any], key: str, section_name: str) -> Any:
    value = section.get(key)
    if value is None:
        raise ValueError(f"{section_name}.{key} is required")
    return value


def _validate_supported(name: str, value: str, supported: set[str]) -> None:
    if value not in supported:
        raise ValueError(f"unsupported {name}: {value}")
