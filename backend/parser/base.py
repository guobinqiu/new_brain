from __future__ import annotations

from typing import Protocol

from ocr.base import OCR


class Parser(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None, parser_type: str | None = None) -> list[dict]:
        ...
