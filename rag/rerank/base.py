from __future__ import annotations

from typing import Protocol


class Rerank(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def rerank(self, query: str, items: list[dict], top_k: int) -> list[dict]:
        ...
