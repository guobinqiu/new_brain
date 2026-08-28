from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ─── LLM（OpenAI 兼容端点：OpenRouter / 本地 vLLM） ───────────────────
    openai_api_key: str
    openai_base_url: str
    model_name: str = "openai/gpt-4o-mini"
    llm_kwargs: str = ""
    use_responses_api: bool = False

    # ─── DB（LangGraph checkpointer） ────────────────────────────────
    database_url: str

    # ─── 并发 / 连接池 ──────────────────────────────────────────────
    llm_concurrency_limit: int = 10
    db_pool_min: int = 2
    db_pool_max: int = 10

    # ─── HTTP 层 ────────────────────────────────────────────────────
    request_timeout_s: int = 60

    # ─── CORS / Rate Limiting ────────────────────────────────────────
    cors_origins: list[str] = ["*"]
    rate_limit_default: str = "100/minute"
    rate_limit_chat: str = "30/minute"
    rate_limit_history: str = "60/minute"
    rate_limit_storage: str = "memory://"

    # ─── Checkpoint 垃圾回收 ─────────────────────────────────────────
    checkpoint_gc_enabled: bool = True
    checkpoint_retention_days: int = 60
    checkpoint_gc_interval_sec: int = 21600

    # ─── 日志 ───────────────────────────────────────────────────────
    log_level: str = "INFO"
    debug_llm_http: bool = False

    # ─── 可选：LangSmith 跟踪 ────────────────────────────────────────
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "llm-rag"

    # ─── 外部 RAG 服务（核心新增） ───────────────────────────────────
    rag_base_url: str = "http://rag:6000"
    rag_timeout_s: float = 10.0
    rag_max_retries: int = 2

    # Docker / 环境里被系统环境变量覆盖，不生效
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
