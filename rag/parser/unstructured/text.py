from rag.ocr.base import OCR
from rag.parser.common.base import BlockParser
from rag.parser.common.schema import Block
from rag.parser.unstructured.blocks import partition_blocks


class TextBlockParser(BlockParser):
    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        return partition_blocks(filepath, self.parser_config)
