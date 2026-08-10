from __future__ import annotations

from typing import Protocol

from sparse.base import Sparse


CollectionType = str
SearchMode = str


class Store(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def drop_collections(self) -> None:
        ...

    def add_common_documents(self, chunks: list[dict], namespace: str = "default") -> int:
        ...

    def add_scoped_documents(self, chunks: list[dict], namespace: str = "default", scope_id: str | None = None) -> int:
        ...

    def delete_common_document(self, filename: str, namespace: str = "default") -> int:
        ...

    def delete_scoped_document(self, filename: str, namespace: str = "default", scope_id: str | None = None) -> int:
        ...

    def list_documents(
        self,
        collection_type: str = "all",
        namespace: str = "default",
        scope_ids: list[str] | None = None,
    ) -> list[dict]:
        ...

    def get_total_chunks(self, namespace: str = "default", scope_ids: list[str] | None = None) -> int:
        ...

    def get_search_documents(self, collection_type: CollectionType, metadata_filter: object) -> list[dict]:
        ...

    def build_common_filter(self, namespace: str):
        ...

    def build_scoped_filter(self, namespace: str, scope_ids: list[str]):
        ...

    def search_dense(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_sparse(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def search_hybrid(self, collection_type: CollectionType, query: str, limit: int, metadata_filter: object) -> list[dict]:
        ...

    def sparse_uses_store(self, sparse: Sparse | None = None) -> bool:
        ...
