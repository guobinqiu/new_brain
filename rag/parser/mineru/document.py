import logging
import os
import time

from rag.ocr.base import OCR
from rag.parser import mineru
from rag.parser.common.base import BlockParser
from rag.parser.common.chunker import blocks_to_documents
from rag.parser.mineru.docx import DocxBlockParser
from rag.parser.mineru.excel import ExcelBlockParser
from rag.parser.mineru.image import ImageBlockParser
from rag.parser.mineru.markdown import MarkdownBlockParser
from rag.parser.mineru.pdf import PdfBlockParser
from rag.parser.mineru.text import TextBlockParser
from rag.schema import MineruParserConfig


logger = logging.getLogger("rag.parser")


class MineruDocumentParser:
    ready = False

    def __init__(self, config: MineruParserConfig, ocr: OCR | None = None):
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
        started = time.perf_counter()
        logger.info("Parser start", extra={"event": "parser_start", "parser": "mineru", "document_filename": filename, "ext": ext})
        chunks = blocks_to_documents(block_parser.parse(filepath, ocr or self.ocr), filename, self.config)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "mineru", "document_filename": filename, "ext": ext, "chunk_count": len(chunks), "total_ms": total_ms})
        if not chunks:
            raise ValueError(f"Empty file: {filename}")
        return chunks

    def is_available(self) -> bool:
        return mineru.table_parser_available()
