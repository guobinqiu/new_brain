from __future__ import annotations

from pydantic import BaseModel, Field, FiniteFloat


class _EmbeddingData(BaseModel):
    embedding: list[FiniteFloat] = Field(min_length=1)


class _EmbeddingResponse(BaseModel):
    data: _EmbeddingData


class _SparseEntry(BaseModel):
    index: int = Field(ge=0)
    value: FiniteFloat


class _SparseData(BaseModel):
    sparse_embedding: list[_SparseEntry]


class _SparseResponse(BaseModel):
    data: _SparseData


class _RerankData(BaseModel):
    scores: list[FiniteFloat]


class _RerankResponse(BaseModel):
    code: int
    message: str | None = None
    data: _RerankData | None = None
