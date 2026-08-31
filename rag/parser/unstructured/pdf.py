import tempfile
from pathlib import Path

from rag.ocr.base import OCR
from rag.parser.common.base import BlockParser
from rag.parser.common.schema import Block
from rag.parser.common.validation import validate_pdf_file
from rag.parser.unstructured.blocks import partition_blocks
from rag.parser.unstructured.image import ImageBlockParser


class PdfBlockParser(BlockParser):
    def __init__(self, parser_config, image_parser: ImageBlockParser | None = None):
        super().__init__(parser_config)
        self.image_parser = image_parser or ImageBlockParser(parser_config)

    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        validate_pdf_file(filepath)
        blocks = partition_blocks(filepath, self.parser_config)
        if self._should_parse_embedded_images():
            with tempfile.TemporaryDirectory(prefix="unstructured_images_") as image_dir:
                blocks.extend(self._parse_image_blocks(filepath, Path(image_dir), ocr))
        return blocks

    def _should_parse_embedded_images(self) -> bool:
        return self.parser_config.strategy != "fast" or self.parser_config.infer_table_structure

    def _parse_image_blocks(self, filepath: str, image_dir: Path, ocr: OCR | None) -> list[Block]:
        import fitz

        doc = fitz.open(filepath)
        blocks: list[Block] = []
        try:
            for page in doc:
                for index, img_info in enumerate(page.get_images(full=True)):
                    xref = img_info[0]
                    try:
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n - pix.alpha > 3:
                            pix = fitz.Pixmap(fitz.csRGB, pix)
                        image_path = image_dir / f"page_{page.number}_image_{index}.png"
                        pix.save(str(image_path))
                        blocks.extend(self.image_parser._safe_parse_image_file(image_path, ocr))
                    except Exception:
                        continue
        finally:
            doc.close()
        return blocks
