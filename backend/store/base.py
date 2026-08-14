from __future__ import annotations

from typing import Protocol

from files.base import FilePage
from sparse.base import Sparse


SearchMode = str


class Store(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def drop_collections(self) -> None:
        ...

    def add_file_chunks(self, chunks: list[dict], file_id: str) -> int:
        ...

    def delete_file_chunks(self, file_id: str) -> int:
        ...

    def get_total_chunks(self, file_ids: list[str] | None = None) -> int:
        ...

    def list_files(self, limit: int = 50, cursor: str | None = None) -> FilePage:
        ...

    def count_files(self) -> int:
        ...

    def get_search_documents(self, metadata_filter: object) -> list[dict]:
        ...

    def build_file_filter(self, file_ids: list[str] | None = None):
        ...

    def search_dense(self, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_sparse(self, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_hybrid(
        self,
        query: str,
        limit: int,
        metadata_filter: object,
        dense_weight: float,
        sparse_weight: float,
        rrf_k: int,
    ) -> list[dict]:
        ...

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        ...
