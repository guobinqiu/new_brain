import os

from ocr.base import OCR
from parser import mineru
from parser.base import BlockParser
from parser.chunker import blocks_to_documents
from parser.docx import DocxBlockParser
from parser.excel import ExcelBlockParser
from parser.image import ImageBlockParser
from parser.markdown import MarkdownBlockParser
from parser.pdf import PdfBlockParser
from parser.text import TextBlockParser
from schema import ParserConfig


class DocumentParser:
    ready = False

    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr
        image_parser = ImageBlockParser(config)
        pdf_parser = PdfBlockParser(config, image_parser)
        markdown_parser = MarkdownBlockParser(config, image_parser)
        docx_parser = DocxBlockParser(config, image_parser)
        excel_parser = ExcelBlockParser(config, image_parser)
        text_parser = TextBlockParser(config)
        self._block_parsers: dict[str, BlockParser] = {
            ".pdf": pdf_parser,
            ".md": markdown_parser,
            ".docx": docx_parser,
            ".xlsx": excel_parser,
            ".txt": text_parser,
            ".png": image_parser,
            ".jpg": image_parser,
            ".jpeg": image_parser,
            ".webp": image_parser,
            ".bmp": image_parser,
        }

    def start(self) -> None:
        if mineru.table_parser_available():
            mineru.load_table_parser()
            self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        ext = os.path.splitext(filepath)[1].lower()
        block_parser = self._block_parsers.get(ext)
        if block_parser is None:
            raise ValueError(f"Unsupported file type: {ext}")
        filename = original_filename or os.path.basename(filepath)
        chunks = blocks_to_documents(block_parser.parse(filepath, ocr or self.ocr), filename, self.config)
        if not chunks:
            raise ValueError(f"Empty file: {filename}")
        return chunks

    def is_available(self) -> bool:
        return mineru.table_parser_available()
