import os

from ocr.base import OCR
from parser import mineru
from parser.chunker import blocks_to_documents
from parser.docx import parse_docx_blocks
from parser.excel import parse_excel_blocks
from parser.image import parse_image_documents
from parser.markdown import parse_markdown_blocks
from parser.pdf import parse_pdf_blocks
from parser.text import chunks_to_documents, load_text_chunks
from schema import ParserConfig


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
STRUCTURED_EXTS = {".md", ".docx", ".xlsx"}
TEXT_EXTS = {".txt"}


class DocumentParser:
    ready = False

    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr

    def start(self) -> None:
        if mineru.table_parser_available():
            mineru.load_table_parser()
            self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in TEXT_EXTS and ext not in STRUCTURED_EXTS and ext not in IMAGE_EXTS and ext != ".pdf":
            raise ValueError(f"Unsupported file type: {ext}")
        filename = original_filename or os.path.basename(filepath)
        ocr = ocr or self.ocr

        if ext == ".pdf":
            chunks = blocks_to_documents(parse_pdf_blocks(filepath, self.config, ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        if ext == ".md":
            chunks = blocks_to_documents(parse_markdown_blocks(filepath, self.config, ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        if ext == ".docx":
            chunks = blocks_to_documents(parse_docx_blocks(filepath, self.config, ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        if ext == ".xlsx":
            chunks = blocks_to_documents(parse_excel_blocks(filepath, self.config, ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        if ext in IMAGE_EXTS:
            return parse_image_documents(filepath, filename, ocr, self.config)

        text_chunks = load_text_chunks(filepath, ext, filename, self.config)
        return chunks_to_documents(text_chunks, filename)

    def is_available(self) -> bool:
        return mineru.table_parser_available()
