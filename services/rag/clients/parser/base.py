from __future__ import annotations

from typing import Protocol


class ParserClient(Protocol):
    def ping(self) -> bool:
        ...

    def close(self) -> None:
        ...

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[dict]:
        ...
