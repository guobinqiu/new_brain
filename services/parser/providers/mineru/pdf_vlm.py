from services.parser.common.validation import InvalidDocumentError
import logging
import os
import time
from pathlib import Path

from services.parser.providers import mineru
from services.parser.common.schema import Block
from shared.config import MineruVlmParserConfig


logger = logging.getLogger("services.parser.providers")


class MineruVlmDocumentParser:
    def __init__(self, config: MineruVlmParserConfig):
        self.config = config
        self.ready = False

    def start(self) -> None:
        if mineru.table_parser_available():
            mineru.prepare_mineru_runtime_config()
            self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        ext = os.path.splitext(filepath)[1].lower()
        filename = original_filename or os.path.basename(filepath)
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "mineru_vlm", "document_filename": filename, "ext": ext})
        blocks = self._parse_blocks(filepath, filename, ext)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "mineru_vlm", "document_filename": filename, "ext": ext, "block_count": len(blocks), "total_ms": total_ms})
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        return blocks

    def _parse_blocks(self, filepath: str, filename: str, ext: str) -> list[Block]:
        if ext != ".pdf":
            raise InvalidDocumentError(f"Unsupported file type: {ext}")
        return mineru.parse_document_blocks(
            filepath,
            filename,
            Path(filename).suffix.lower().lstrip("."),
            backend="vlm-auto-engine",
        )
