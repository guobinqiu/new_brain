from services.parser.common.validation import InvalidDocumentError, validate_pdf_file
import logging
import os
import time

from services.parser.providers import mineru
from services.parser.common.schema import Block
from shared.config import MineruParserConfig


logger = logging.getLogger("services.parser.providers")


class MineruPipelineDocumentParser:
    def __init__(self, config: MineruParserConfig):
        self.config = config
        self.ready = False

    def start(self) -> None:
        if mineru.table_parser_available():
            mineru.load_table_parser(self.config)
            self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext != ".pdf":
            raise InvalidDocumentError(f"Unsupported file type: {ext}")
        validate_pdf_file(filepath)
        filename = original_filename or os.path.basename(filepath)
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "mineru", "document_filename": filename, "ext": ext})
        blocks = mineru.parse_document_blocks(filepath, filepath, "pdf", self.config)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "mineru", "document_filename": filename, "ext": ext, "block_count": len(blocks), "total_ms": total_ms})
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        return blocks
