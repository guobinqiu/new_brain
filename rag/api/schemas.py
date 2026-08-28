from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag.config import SEARCH_CONFIG


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    app_id: str | None = None
    mode: Literal["dense", "sparse", "hybrid"] = SEARCH_CONFIG["default_mode"]
    top_k: int = Field(SEARCH_CONFIG["top_k"], ge=1, le=50)
    rerank: bool = SEARCH_CONFIG["rerank"]
    fetch_k: int = Field(SEARCH_CONFIG["fetch_k"], ge=1)
    dense_weight: float = Field(SEARCH_CONFIG["dense_weight"], ge=0, le=1)
    sparse_weight: float = Field(SEARCH_CONFIG["sparse_weight"], ge=0, le=1)
    rrf_k: int = Field(SEARCH_CONFIG["rrf_k"], ge=1)
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_fetch_k(self):
        if self.fetch_k < self.top_k:
            raise ValueError("fetch_k must be greater than or equal to top_k")
        if self.file_ids is not None and len(self.file_ids) == 0:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        return self


class ObjectIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    presigned_url: str = Field(..., min_length=1)
    s3_url: str = Field(..., min_length=1)
    filename: str | None = None
    app_id: str | None = None
    file_id: str | None = Field(None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_request(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


class AdminIndexJobRequest(ObjectIndexRequest):
    file_id: str = Field(..., min_length=1, max_length=64)


class PresignRequest(BaseModel):
    s3_url: str = Field(..., min_length=1)
    expires_in: int = Field(3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_s3_url(self):
        if not self.s3_url.startswith("s3://"):
            raise ValueError("s3_url must start with s3://")
        return self


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AppCreateRequest(BaseModel):
    app_id: str = Field(..., min_length=2, max_length=64)


class ChunksQueryRequest(BaseModel):
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None
    app_id: str | None = None
    file_ids: list[str] | None = None

    @model_validator(mode="after")
    def validate_file_ids(self):
        if self.file_ids is not None and len(self.file_ids) == 0:
            raise ValueError("file_ids cannot be empty")
        if self.file_ids is not None and len(self.file_ids) > 1000:
            raise ValueError("file_ids exceeds max limit: 1000")
        return self

