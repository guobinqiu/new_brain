from __future__ import annotations

from typing import Protocol


class Tokenizer(Protocol):
    def start(self) -> None:
        ...

    def tokenize(self, text: str) -> list[str]:
        ...
