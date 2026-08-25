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
        self.parsers = {
            "text": self.text,
            "table": self.table,
        }
        self.ready = False

    def start(self) -> None:
        for parser in self.parsers.values():
            parser.start()
        self.ready = True

    def stop(self) -> None:
        for parser in self.parsers.values():
            parser.stop()
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None, parser_type: str | None = None) -> list[dict]:
        selected_parser = self._internal_parser(parser_type or self.config.type)
        parser = self.parsers.get(selected_parser)
        if parser is None:
            raise ValueError(f"Unsupported parser: {selected_parser}")
        return parser.parse_file(filepath, original_filename=original_filename, ocr=ocr or self.ocr, parser_type=parser_type)

    def is_available(self, parser_type: str) -> bool:
        parser_type = self._internal_parser(parser_type)
        if parser_type == "text":
            return True
        if parser_type == "table":
            return self.table.is_available()
        return False

    def _internal_parser(self, parser_type: str | None) -> str | None:
        return {
            "standard": "table",
            "fast": "text",
        }.get(parser_type, parser_type)
