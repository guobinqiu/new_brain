from __future__ import annotations

from typing import Protocol


class Sparse(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def supports_search_index(self) -> bool:
        ...

    def supports_sparse_vector(self) -> bool:
        ...

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        ...
