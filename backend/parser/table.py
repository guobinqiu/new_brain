from pathlib import Path

from ocr.base import OCR
from parser.text import TextParser
from parser import mineru
from parser.table_splitter import split_table
from schema import ParserConfig


class TableParser:
    def __init__(self, config: ParserConfig, text_parser: TextParser):
        self.config = config
        self.text_parser = text_parser
        self.ready = False

    def start(self) -> None:
        if table_parser_available():
            load_table_parser()
            self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None, parser_type: str | None = None) -> list[dict]:
        if Path(filepath).suffix.lower() == ".pdf":
            if not self.ready:
                raise RuntimeError("table parser is not loaded")
            return parse_pdf_table(filepath, original_filename or Path(filepath).name, self.config)
        return self.text_parser.parse_file(filepath, original_filename=original_filename, ocr=ocr, parser_type=parser_type)

    def is_available(self) -> bool:
        return table_parser_available()


def table_parser_available() -> bool:
    return mineru.table_parser_available()


def load_table_parser() -> None:
    mineru.load_table_parser()


def parse_pdf_table(filepath: str, filename: str, parser_config: ParserConfig) -> list[dict]:
    return mineru.parse_pdf_table(filepath, filename, parser_config)
