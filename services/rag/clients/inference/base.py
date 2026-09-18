from __future__ import annotations

from typing import Protocol

from shared.contracts import Dense, Rerank, Sparse


class InferenceClient(Protocol):
    dense: Dense
    sparse: Sparse | None
    rerank: Rerank | None

    def ping(self) -> bool:
        ...

    def close(self) -> None:
        ...
