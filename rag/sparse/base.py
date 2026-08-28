from __future__ import annotations

from typing import Protocol


class Sparse(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def search(self, query: str, documents: list[dict], limit: int) -> list[dict]:
        ...
