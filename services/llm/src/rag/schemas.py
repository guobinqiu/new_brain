"""rag.schemas: Pydantic 数据契约（请求 / 响应 / 文档）。

被 rag/client.py 与 rag/tool.py 共用。生成紧凑 JSON body 用于 HTTP 调用。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Document(BaseModel):
    """单条检索结果。响应契约中无 score 字段（不依赖分数做后续逻辑）。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    content: str


class SearchRequest(BaseModel):
    """RAG search 请求体。

    LLM 只传业务查询参数；检索模式、候选池和 rerank 由 RAG 服务配置决定。
    """

    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    top_k: int | None = None
    file_ids: list[str] | None = None

    @field_validator("file_ids")
    @classmethod
    def _validate_file_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) == 0:
            raise ValueError("file_ids must not be empty when provided")
        return v


class SearchResponse(BaseModel):
    """RAG search 响应体。"""

    model_config = ConfigDict(extra="ignore")

    results: list[Document] = Field(default_factory=list)
    mode: str | None = None
    rerank: bool | None = None
    rerank_fetch_k: int | None = None
    elapsed_ms: float | None = None
