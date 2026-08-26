from ocr.base import OCR
from parser import mineru
from parser.image import parse_zip_image_blocks
from parser.schema import Block
from parser.validation import validate_xlsx_file
from schema import ParserConfig


def parse_excel_blocks(filepath: str, parser_config: ParserConfig, ocr: OCR | None = None) -> list[Block]:
    validate_xlsx_file(filepath)
    blocks = mineru.parse_document_blocks(filepath, filepath, "xlsx", parser_config)
    blocks.extend(parse_zip_image_blocks(filepath, "xl/media/", ocr, parser_config))
    return blocks
