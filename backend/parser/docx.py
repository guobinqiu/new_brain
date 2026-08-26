import tempfile
from pathlib import Path

from ocr.base import OCR
from parser import mineru
from parser.image import expand_image_blocks, parse_zip_image_blocks
from parser.schema import Block
from parser.validation import validate_docx_file
from schema import ParserConfig


def parse_docx_blocks(filepath: str, parser_config: ParserConfig, ocr: OCR | None = None) -> list[Block]:
    validate_docx_file(filepath)
    blocks = mineru.parse_document_blocks(filepath, filepath, "docx", parser_config)
    with tempfile.TemporaryDirectory(prefix="parser_images_") as image_dir:
        blocks.extend(parse_zip_image_blocks(filepath, "word/media/", Path(image_dir), ocr, parser_config))
        return expand_image_blocks(blocks, parser_config)
