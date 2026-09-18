from services.parser.common.validation import InvalidDocumentError
import threading
import os

from services.parser.common.validation import validate_pdf_file
from services.parser.providers.docling.pdf_pipeline import DoclingPipelineDocumentParser
from services.parser.providers.docling.pdf_vlm import DoclingVlmDocumentParser
from services.parser.documents.parser import DocumentParser
from services.parser.common.schema import Block
from services.parser.providers.mineru.pdf_pipeline import MineruPipelineDocumentParser
from services.parser.providers.mineru.pdf_vlm import MineruVlmDocumentParser
from services.parser.providers.volcengine import VolcengineDocumentParser
from shared.config import ParserConfig


class ParserService:
    def __init__(self, config: ParserConfig):
        self.config = config
        self.pdf_parser = self._build_pdf_parser(config)
        self.document_parser = DocumentParser()
        self._parse_lock = threading.Lock()
        self.ready = False

    def _build_pdf_parser(self, config: ParserConfig):
        if config.active == "volcengine":
            return VolcengineDocumentParser(config.volcengine)
        if config.active == "docling":
            return DoclingPipelineDocumentParser(config.docling)
        if config.active == "docling_vlm":
            return DoclingVlmDocumentParser(config.docling_vlm)
        if config.active == "mineru_vlm":
            return MineruVlmDocumentParser(config.mineru_vlm)
        return MineruPipelineDocumentParser(config.mineru)

    def start(self) -> None:
        self.pdf_parser.start()
        self.ready = self.pdf_parser.ready

    def stop(self) -> None:
        self.pdf_parser.stop()
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None) -> list[Block]:
        with self._parse_lock:
            ext = os.path.splitext(filepath)[1].lower()
            if self.document_parser.supports(filepath):
                return self.document_parser.parse_file(filepath)
            if ext != ".pdf":
                raise InvalidDocumentError(f"Unsupported file type: {ext}")
            validate_pdf_file(filepath)
            return self.pdf_parser.parse_file(filepath, original_filename=original_filename)
