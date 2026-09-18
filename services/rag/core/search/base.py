from __future__ import annotations

from typing import Protocol


class Search(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...
