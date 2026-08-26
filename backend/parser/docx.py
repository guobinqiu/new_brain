from ocr.base import OCR
from parser import mineru
from parser.image import parse_zip_image_blocks
from parser.schema import Block
from parser.validation import validate_docx_file
from schema import ParserConfig


def parse_docx_blocks(filepath: str, parser_config: ParserConfig, ocr: OCR | None = None) -> list[Block]:
    validate_docx_file(filepath)
    blocks = mineru.parse_document_blocks(filepath, filepath, "docx", parser_config)
    blocks.extend(parse_zip_image_blocks(filepath, "word/media/", ocr, parser_config))
    return blocks
