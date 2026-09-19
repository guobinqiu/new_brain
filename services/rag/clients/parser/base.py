from __future__ import annotations

from typing import Protocol


class ParserClient(Protocol):
    def ping(self) -> bool:
        ...

    def close(self) -> None:
        ...

    def parse_file(self, presigned_url: str, *, filename: str) -> dict:
        ...
