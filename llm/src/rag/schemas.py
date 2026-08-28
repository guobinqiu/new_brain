"""rag.schemas: Pydantic 数据契约（请求 / 响应 / 文档）。

被 rag/client.py 与 rag/tool.py 共用。生成紧凑 JSON body 用于 HTTP 签名。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Document(BaseModel):
    """单条检索结果。响应契约中无 score 字段（不依赖分数做后续逻辑）。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    content: str


class SearchRequest(BaseModel):
    """RAG search 请求体。

    所有字段均可选（mode / top_k / rerank / fetch_k / dense_weight /
    sparse_weight / rrf_k / file_ids）。
    """

    model_config = ConfigDict(extra="ignore")

    query: str | None = None
    top_k: int | None = None
    mode: str | None = None  # hybrid | dense | sparse
    rerank: bool | None = None
    fetch_k: int | None = None
    dense_weight: float | None = None
    sparse_weight: float | None = None
    rrf_k: int | None = None
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> SearchRequest:
        # fetch_k ≥ top_k 物理约束；fetch_k 未设时不校验
        if (
            self.fetch_k is not None
            and self.top_k is not None
            and self.fetch_k < self.top_k
        ):
            raise ValueError(
                f"fetch_k ({self.fetch_k}) must be >= top_k ({self.top_k})"
            )
        return self

    @field_validator("file_ids")
    @classmethod
    def _validate_file_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) == 0:
            raise ValueError("file_ids must not be empty when provided")
        return v


class SearchResponse(BaseModel):
    """RAG search 响应体（qdrant 服务契约）。"""

    model_config = ConfigDict(extra="ignore")

    results: list[Document] = Field(default_factory=list)
    mode: str | None = None
    rerank: bool | None = None
    fetch_k: int | None = None
    dense_weight: float | None = None
    sparse_weight: float | None = None
    rrf_k: int | None = None
    elapsed_ms: float | None = None
