import logging
import os
import time

from rag.ocr.base import OCR
from rag.parser.common.base import BlockParser
from rag.parser.common.chunker import blocks_to_documents
from rag.parser.unstructured import runtime
from rag.parser.unstructured.docx import DocxBlockParser
from rag.parser.unstructured.excel import ExcelBlockParser
from rag.parser.unstructured.image import ImageBlockParser
from rag.parser.unstructured.markdown import MarkdownBlockParser
from rag.parser.unstructured.pdf import PdfBlockParser
from rag.parser.unstructured.text import TextBlockParser
from rag.schema import UnstructuredParserConfig


logger = logging.getLogger("rag.parser")


class UnstructuredDocumentParser:
    ready = False

    def __init__(self, config: UnstructuredParserConfig, ocr: OCR | None = None):
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
        self.ready = False
        runtime.prepare_unstructured_runtime_config()
        if self.config.strategy == "hi_res":
            runtime.load_unstructured_layout_model()
        if self.config.infer_table_structure:
            runtime.load_unstructured_table_model()
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
        logger.info("Parser start", extra={"event": "parser_start", "parser": "unstructured", "document_filename": filename, "ext": ext, "strategy": self.config.strategy, "infer_table_structure": self.config.infer_table_structure})
        chunks = blocks_to_documents(block_parser.parse(filepath, ocr or self.ocr), filename, self.config)
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Parser done", extra={"event": "parser_done", "parser": "unstructured", "document_filename": filename, "ext": ext, "strategy": self.config.strategy, "infer_table_structure": self.config.infer_table_structure, "chunk_count": len(chunks), "total_ms": total_ms})
        if not chunks:
            raise ValueError(f"Empty file: {filename}")
        return chunks

    def is_available(self) -> bool:
        return runtime.unstructured_available()
