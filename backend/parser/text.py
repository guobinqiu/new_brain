import os
import tempfile
import uuid

from langchain_community.document_loaders import TextLoader
from ocr.base import OCR
from schema import ParserConfig

from parser.docx import parse_docx_blocks
from parser.excel import parse_excel_blocks
from parser.image import parse_image_blocks, parse_image_documents
from parser.markdown import parse_markdown_blocks
from parser.chunker import blocks_to_documents
from parser.schema import Block, TextBlock
from parser.text_splitter import clean_cjk_spaces, split_text
from parser.validation import validate_pdf_file


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
STRUCTURED_EXTS = {".md", ".markdown", ".docx", ".xlsx"}

LOADERS = {
    ".txt": TextLoader,
}


class TextParser:
    ready = False

    def __init__(self, config: ParserConfig, ocr: OCR | None = None):
        self.config = config
        self.ocr = ocr

    def start(self) -> None:
        self.ready = True

    def stop(self) -> None:
        self.ready = False

    def parse_file(self, filepath: str, *, original_filename: str | None = None, ocr: OCR | None = None) -> list[dict]:
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in LOADERS and ext not in STRUCTURED_EXTS and ext not in IMAGE_EXTS and ext != ".pdf":
            raise ValueError(f"Unsupported file type: {ext}")
        filename = original_filename or os.path.basename(filepath)

        if ext in (".md", ".markdown"):
            chunks = blocks_to_documents(parse_markdown_blocks(filepath, self.config, ocr or self.ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        if ext == ".docx":
            chunks = blocks_to_documents(parse_docx_blocks(filepath, self.config, ocr or self.ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        if ext == ".xlsx":
            chunks = blocks_to_documents(parse_excel_blocks(filepath, self.config, ocr or self.ocr), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks

        if ext == ".pdf":
            chunks = blocks_to_documents(_parse_pdf_blocks(filepath, filename, ocr or self.ocr, self.config), filename, self.config)
            if not chunks:
                raise ValueError(f"Empty file: {filename}")
            return chunks
        elif ext in IMAGE_EXTS:
            return parse_image_documents(filepath, filename, ocr or self.ocr, self.config)
        else:
            text = _load_text(filepath, ext, filename)

        text = clean_cjk_spaces(text)
        if not text.strip():
            raise ValueError(f"Empty file: {filename}")

        return chunks_to_documents(
            split_text(text, self.config.text.chunk_size, self.config.text.chunk_overlap),
            filename,
        )


def chunk_text(text: str, filename: str, chunk_size: int = 500, overlap: int = 80) -> list[dict]:
    text = clean_cjk_spaces(text)
    return chunks_to_documents(split_text(text, chunk_size=chunk_size, overlap=overlap), filename)


def chunks_to_documents(chunks: list[str], filename: str) -> list[dict]:
    results = []
    for chunk_index, chunk_text in enumerate(chunks):
        chunk_text = chunk_text.strip()
        if not chunk_text:
            continue
        results.append({
            "content": chunk_text,
            "metadata": {
                "filename": filename,
                "content_type": "text",
                "chunk_index": chunk_index,
            },
            "id": str(uuid.uuid4()),
        })
    return results


def _parse_pdf_blocks(filepath: str, filename: str, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    import fitz

    validate_pdf_file(filepath)
    doc = fitz.open(filepath)
    blocks: list[Block] = []
    for page in doc:
        page_text = page.get_text()
        if page_text.strip():
            blocks.append(TextBlock(page_text))
        blocks.extend(_parse_page_image_blocks(doc, page, ocr, parser_config))
    doc.close()
    return blocks


def parse_pdf_image_documents(filepath: str, filename: str, ocr: OCR | None, parser_config: ParserConfig) -> list[dict]:
    chunks = blocks_to_documents(parse_pdf_image_blocks(filepath, ocr, parser_config), filename, parser_config)
    return chunks


def parse_pdf_image_blocks(filepath: str, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    import fitz

    validate_pdf_file(filepath)
    doc = fitz.open(filepath)
    blocks: list[Block] = []
    for page in doc:
        blocks.extend(_parse_page_image_blocks(doc, page, ocr, parser_config))
    doc.close()
    return blocks


def _parse_page_image_blocks(doc, page, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    blocks: list[Block] = []
    import fitz

    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            try:
                pix.save(tmp.name)
                blocks.extend(parse_image_blocks(tmp.name, ocr, parser_config))
            finally:
                os.unlink(tmp.name)
        except Exception:
            continue
    return blocks


def _load_text(filepath: str, ext: str, filename: str) -> str:
    loader_cls = LOADERS[ext]
    docs = loader_cls(filepath).load()
    if not docs or not docs[0].page_content.strip():
        raise ValueError(f"Empty file: {filename}")
    return "\n".join(doc.page_content for doc in docs)
