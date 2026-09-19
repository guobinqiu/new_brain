import logging
import os
import time
from pathlib import Path

from services.parser.common.schema import Block
from services.parser.common.validation import InvalidDocumentError
from services.parser.providers.mineru.normalizer import content_list_to_blocks
from shared.config import MineruParserConfig
from shared.paths import MODELS_DIR


logger = logging.getLogger("services.parser.providers")


class MineruDocumentParser:
    def __init__(self, config: MineruParserConfig):
        self.config = config
        self.ready = False
        self._parse = None
        self._render = None
        self._content_list_format = None

    def start(self) -> None:
        self.ready = False
        started = time.perf_counter()
        logger.info("Parser model initialization started", extra={"parser": "mineru", "tier": self.config.tier})
        # MinerU reads its process-wide configuration on first import.
        os.environ.setdefault("MINERU_MODEL_BASE_DIR", str(MODELS_DIR / "mineru"))
        os.environ.setdefault("MINERU_MODEL_SOURCE", "local")
        from mineru.parser import parse
        from mineru.render import RenderFormat, render

        if self.config.tier != "flash":
            # Reuse the preload path of the pinned MinerU 4.0.3 API server.
            from mineru.parser.api_server import _preload_server_models
            _preload_server_models(self.config.tier)
        self._parse = parse
        self._render = render
        self._content_list_format = RenderFormat.CONTENT_LIST
        self.ready = True
        logger.info("Parser model initialization completed", extra={"parser": "mineru", "tier": self.config.tier, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)})

    def stop(self) -> None:
        self._parse = None
        self._render = None
        self._content_list_format = None
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        if not self.ready:
            self.start()
        filename = original_filename or Path(filepath).name
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "mineru", "document_filename": filename, "tier": self.config.tier})
        result = self._parse(filepath, tier=self.config.tier, ocr_mode=self.config.parse_method, image_analysis=self.config.image_analysis)
        content = self._render(result.middle_json, self._content_list_format)
        blocks = content_list_to_blocks(content)
        if not blocks:
            raise InvalidDocumentError(f"Empty file: {filename}")
        logger.info("Parser done", extra={"event": "parser_done", "parser": "mineru", "document_filename": filename, "block_count": len(blocks), "total_ms": round((time.perf_counter() - started) * 1000, 1)})
        return blocks
