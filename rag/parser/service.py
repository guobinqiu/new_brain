from rag.ocr.base import OCR
from rag.schema import ParserConfig

from rag.parser.document import DocumentParser


class ParserService:
    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr
        self.document = DocumentParser(config, ocr=ocr)
        self.ready = False

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
