import tempfile
from pathlib import Path

from ocr.base import OCR
from parser import mineru
from parser.base import BlockParser
from parser.image import ImageBlockParser
from parser.schema import Block
from parser.validation import validate_xlsx_file


class ExcelBlockParser(BlockParser):
    def __init__(self, parser_config, image_parser: ImageBlockParser | None = None):
        super().__init__(parser_config)
        self.image_parser = image_parser or ImageBlockParser(parser_config)

    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        validate_xlsx_file(filepath)
        blocks = mineru.parse_document_blocks(filepath, filepath, "xlsx", self.parser_config)
        with tempfile.TemporaryDirectory(prefix="parser_images_") as image_dir:
            blocks.extend(self.image_parser.parse_embedded_image_blocks(filepath, "xl/media/", Path(image_dir), ocr))
            return self.image_parser.expand_blocks(blocks)
