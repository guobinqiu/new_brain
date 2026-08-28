import tempfile
from pathlib import Path

from rag.ocr.base import OCR
from rag.parser import mineru
from rag.parser.base import BlockParser
from rag.parser.image import ImageBlockParser
from rag.parser.schema import Block, TableBlock, TextBlock
from rag.parser.validation import validate_docx_file


class DocxBlockParser(BlockParser):
    def __init__(self, parser_config, image_parser: ImageBlockParser | None = None):
        super().__init__(parser_config)
        self.image_parser = image_parser or ImageBlockParser(parser_config)

    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        validate_docx_file(filepath)
        mineru_blocks = mineru.parse_document_blocks(filepath, filepath, "docx", self.parser_config)
        blocks = self._merge_native_text(filepath, mineru_blocks)
        with tempfile.TemporaryDirectory(prefix="parser_images_") as image_dir:
            blocks.extend(self.image_parser.parse_embedded_image_blocks(filepath, "word/media/", Path(image_dir), ocr))
            return self.image_parser.expand_blocks(blocks)

    def _merge_native_text(self, filepath: str, mineru_blocks: list[Block]) -> list[Block]:
        from docx import Document
        from docx.text.paragraph import Paragraph

        table_blocks = [block for block in mineru_blocks if isinstance(block, TableBlock)]
        merged: list[Block] = []
        table_index = 0
        document = Document(filepath)
        for child in document.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = Paragraph(child, document).text.strip()
                if text:
                    merged.append(TextBlock(text))
                continue
            if tag == "tbl":
                if table_index < len(table_blocks):
                    merged.append(table_blocks[table_index])
                    table_index += 1
        merged.extend(table_blocks[table_index:])
        return merged or mineru_blocks
