import logging
import os
import time

from services.parser.common.schema import Block
from services.parser.common.validation import InvalidDocumentError, validate_pdf_file
from services.parser.providers.mineru.api_server import MineruApiServerClient
from shared.config import MineruParserConfig


logger = logging.getLogger("services.parser.providers")


class MineruApiServerDocumentParser:
    def __init__(self, config: MineruParserConfig, *, http_client=None):
        self.config = config
        self.client = MineruApiServerClient(config, http_client=http_client)
        self.ready = False

    def start(self) -> None:
        self.client.start()
        self.ready = True

    def stop(self) -> None:
        self.client.stop()
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext != ".pdf":
            raise InvalidDocumentError(f"Unsupported file type: {ext}")
        validate_pdf_file(filepath)
        filename = original_filename or os.path.basename(filepath)
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "mineru", "document_filename": filename, "ext": ext})
        blocks = self.client.parse_file(filepath, original_filename=filename)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "mineru", "document_filename": filename, "ext": ext, "block_count": len(blocks), "total_ms": total_ms})
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        return blocks
