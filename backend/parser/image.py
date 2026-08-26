import os
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from ocr.base import OCR
from parser import mineru
from parser.chunker import blocks_to_documents
from parser.schema import Block
from parser.validation import validate_image_file
from schema import ParserConfig


def parse_image_documents(filepath: str, filename: str, ocr: OCR | None, parser_config: ParserConfig) -> list[dict]:
    documents = blocks_to_documents(parse_image_blocks(filepath, ocr, parser_config), filename, parser_config)
    if not documents:
        raise ValueError(f"Empty file: {filename}")
    return documents


def parse_image_blocks(filepath: str, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    validate_image_file(filepath)
    file_type = Path(filepath).suffix.lower().lstrip(".")
    return mineru.parse_document_blocks(filepath, filepath, file_type, parser_config)


def parse_markdown_image_blocks(filepath: str, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    markdown = Path(filepath).read_text(encoding="utf-8")
    base_dir = Path(filepath).parent
    blocks: list[Block] = []
    for match in re.finditer(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", markdown):
        image_ref = unquote(match.group(1).strip("<>"))
        parsed = urlparse(image_ref)
        if parsed.scheme or parsed.netloc:
            continue
        image_path = (base_dir / image_ref).resolve()
        if not image_path.exists():
            continue
        blocks.extend(_safe_parse_image_blocks(str(image_path), ocr, parser_config))
    return blocks


def parse_zip_image_blocks(filepath: str, media_prefix: str, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    blocks: list[Block] = []
    with zipfile.ZipFile(filepath) as archive:
        for name in archive.namelist():
            if not name.startswith(media_prefix):
                continue
            suffix = os.path.splitext(name)[1].lower()
            if not suffix:
                continue
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(archive.read(name))
            try:
                blocks.extend(_safe_parse_image_blocks(tmp.name, ocr, parser_config))
            finally:
                os.unlink(tmp.name)
    return blocks


def _safe_parse_image_blocks(filepath: str, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    try:
        return parse_image_blocks(filepath, ocr, parser_config)
    except ValueError:
        return []
