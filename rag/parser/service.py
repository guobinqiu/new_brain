from rag.ocr.base import OCR
from rag.parser.mineru.document import MineruDocumentParser
from rag.parser.unstructured import UnstructuredDocumentParser
from rag.schema import ParserConfig


class ParserService:
    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr
        self.document = self._build_document_parser(config, ocr)
        self.ready = False

    def _build_document_parser(self, config: ParserConfig, ocr: OCR | None):
        if config.enabled_parser == "mineru":
            return MineruDocumentParser(config.mineru, ocr=ocr)
        if config.enabled_parser == "unstructured":
            return UnstructuredDocumentParser(config.unstructured, ocr=ocr)
        raise ValueError(f"unsupported parser: {config.enabled_parser}")

    def start(self) -> None:
        self.document.start()
        self.ready = True

    def stop(self) -> None:
        self.document.stop()
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        return self.document.parse_file(filepath, original_filename=original_filename, ocr=ocr or self.ocr)

    def is_available(self) -> bool:
        return self.document.is_available()
