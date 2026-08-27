from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from ocr.base import OCR
from parser.schema import Block
from schema import ParserConfig


class Parser(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        ...


class BlockParser(ABC):
    def __init__(self, parser_config: ParserConfig):
        self.parser_config = parser_config

    @abstractmethod
    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        ...
