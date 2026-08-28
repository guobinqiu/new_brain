from __future__ import annotations

from typing import Protocol
from typing import Any


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
