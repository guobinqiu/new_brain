from pathlib import Path

from ocr.base import OCR
from parser.text import TextParser, parse_pdf_image_documents
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

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        if Path(filepath).suffix.lower() == ".pdf":
            if not self.ready:
                raise RuntimeError("table parser is not loaded")
            filename = original_filename or Path(filepath).name
            chunks = parse_pdf_table(filepath, filename, self.config)
            chunks.extend(parse_pdf_image_documents(filepath, filename, ocr, self.config))
            for chunk_index, chunk in enumerate(chunks):
                chunk["metadata"]["chunk_index"] = chunk_index
            return chunks
        return self.text_parser.parse_file(filepath, original_filename=original_filename, ocr=ocr)

    def is_available(self) -> bool:
        return table_parser_available()


def table_parser_available() -> bool:
    return mineru.table_parser_available()


def load_table_parser() -> None:
    mineru.load_table_parser()


def parse_pdf_table(filepath: str, filename: str, parser_config: ParserConfig) -> list[dict]:
    return mineru.parse_pdf_table(filepath, filename, parser_config)
