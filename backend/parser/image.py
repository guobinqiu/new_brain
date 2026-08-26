import os
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from ocr.base import OCR
from parser import mineru
from parser.chunker import blocks_to_documents
from parser.schema import Block, ImageBlock
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
    return mineru.parse_document_blocks(filepath, Path(filepath).name, file_type, parser_config)


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
        image_block = _safe_image_block_from_file(image_path)
        if image_block is not None:
            blocks.append(image_block)
    return blocks


def parse_zip_image_blocks(filepath: str, media_prefix: str, image_dir: Path, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    blocks: list[Block] = []
    with zipfile.ZipFile(filepath) as archive:
        for index, name in enumerate(archive.namelist()):
            if not name.startswith(media_prefix):
                continue
            suffix = os.path.splitext(name)[1].lower()
            if not suffix:
                continue
            image_path = image_dir / f"embedded_{index}{suffix}"
            image_path.write_bytes(archive.read(name))
            image_block = _safe_image_block_from_file(image_path)
            if image_block is not None:
                blocks.append(image_block)
    return blocks


def expand_image_blocks(blocks: list[Block], parser_config: ParserConfig) -> list[Block]:
    expanded: list[Block] = []
    for block in blocks:
        if isinstance(block, ImageBlock):
            try:
                image_path = Path(block.path)
                expanded.extend(mineru.parse_document_blocks(str(image_path), image_path.name, block.file_type, parser_config))
            except ValueError:
                continue
            continue
        expanded.append(block)
    return expanded


def _safe_image_block_from_file(filepath: Path) -> ImageBlock | None:
    try:
        validate_image_file(str(filepath))
        return ImageBlock(str(filepath), filepath.suffix.lower().lstrip("."))
    except ValueError:
        return None
