from rag.ocr.base import OCR
from rag.parser.common.base import BlockParser
from rag.parser.common.schema import Block
from rag.parser.unstructured.blocks import partition_blocks
from rag.parser.unstructured.image import ImageBlockParser


class MarkdownBlockParser(BlockParser):
    def __init__(self, parser_config, image_parser: ImageBlockParser | None = None):
        super().__init__(parser_config)
        self.image_parser = image_parser or ImageBlockParser(parser_config)

    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        blocks = partition_blocks(filepath, self.parser_config)
        if self._should_parse_embedded_images():
            blocks.extend(self.image_parser.parse_markdown_image_blocks(filepath, ocr))
        return blocks

    def _should_parse_embedded_images(self) -> bool:
        return self.parser_config.strategy != "fast" or self.parser_config.infer_table_structure
