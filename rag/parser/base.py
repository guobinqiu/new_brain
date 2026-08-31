from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from rag.ocr.base import OCR
from rag.parser.schema import Block
from rag.schema import MineruParserConfig, UnstructuredParserConfig


BackendParserConfig = MineruParserConfig | UnstructuredParserConfig


class Parser(Protocol):
    ready: bool

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        ...


class BlockParser(ABC):
    def __init__(self, parser_config: BackendParserConfig):
        self.parser_config = parser_config

    @abstractmethod
    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        ...
