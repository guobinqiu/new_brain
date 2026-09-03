import tempfile
from pathlib import Path

from rag.ocr.base import OCR
from rag.parser.common.base import BlockParser
from rag.parser.common.excel import xlsx_to_table_blocks
from rag.parser.common.schema import Block
from rag.parser.common.validation import validate_xlsx_file
from rag.parser.unstructured.image import ImageBlockParser


class ExcelBlockParser(BlockParser):
    def __init__(self, parser_config, image_parser: ImageBlockParser | None = None):
        super().__init__(parser_config)
        self.image_parser = image_parser or ImageBlockParser(parser_config)

    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        validate_xlsx_file(filepath)
        blocks = xlsx_to_table_blocks(filepath, self.parser_config)
        if self._should_parse_embedded_images():
            with tempfile.TemporaryDirectory(prefix="unstructured_images_") as image_dir:
                blocks.extend(self.image_parser.parse_embedded_image_blocks(filepath, "xl/media/", Path(image_dir), ocr))
        return blocks

    def _should_parse_embedded_images(self) -> bool:
        return self.parser_config.strategy != "fast" or self.parser_config.infer_table_structure
