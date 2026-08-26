from ocr.base import OCR
from schema import ParserConfig

from parser.text import TextParser
from parser.table import TableParser


class ParserService:
    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr
        self.text = TextParser(config, ocr=ocr)
        self.table = TableParser(config, self.text)
        self.ready = False

    def start(self) -> None:
        self.text.start()
        self.table.start()
        self.ready = True

    def stop(self) -> None:
        self.table.stop()
        self.text.stop()
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        return self.table.parse_file(filepath, original_filename=original_filename, ocr=ocr or self.ocr)

    def is_available(self) -> bool:
        return self.table.is_available()
