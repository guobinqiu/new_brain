from __future__ import annotations

from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: str | None
    retryable: StrictBool
    traceId: str = Field(pattern=r"^[0-9a-f]{32}$")


TextKind = Literal["heading", "paragraph", "list_item", "code", "text"]


class ParserTextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str
    kind: TextKind = "text"
    page: int | None = None


class ParserTableBlock(BaseModel):
    type: Literal["table"] = "table"
    rows: list[list[str]]
    caption: str | None = None
    page: int | None = None


class ParserFormulaBlock(BaseModel):
    type: Literal["formula"] = "formula"
    text: str
    format: str = "latex"
    page: int | None = None


ParserBlock = Annotated[ParserTextBlock | ParserTableBlock | ParserFormulaBlock, Field(discriminator="type")]


class EmbeddingRequest(BaseModel):
    texts: list[str]


class EmbeddingResponse(BaseModel):
    vectors: list[list[float]]


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_k: int


class RerankResponse(BaseModel):
    results: list[dict[str, Any]]


class Dense(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def as_langchain_dense(self) -> Any:
        ...

    @property
    def vector_size(self) -> int:
        ...


class Sparse(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def embed_query(self, text: str) -> dict[int, float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[dict[int, float]]:
        ...


class Rerank(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        ...


class Parser(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[dict]:
        ...
