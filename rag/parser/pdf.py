import tempfile
from pathlib import Path

from rag.ocr.base import OCR
from rag.parser import mineru
from rag.parser.base import BlockParser
from rag.parser.image import ImageBlockParser
from rag.parser.schema import Block, ImageBlock
from rag.parser.validation import validate_pdf_file


class PdfBlockParser(BlockParser):
    def __init__(self, parser_config, image_parser: ImageBlockParser | None = None):
        super().__init__(parser_config)
        self.image_parser = image_parser or ImageBlockParser(parser_config)

    def parse(self, filepath: str, ocr: OCR | None = None) -> list[Block]:
        validate_pdf_file(filepath)
        blocks = mineru.parse_document_blocks(filepath, filepath, "pdf", self.parser_config)
        with tempfile.TemporaryDirectory(prefix="parser_images_") as image_dir:
            blocks.extend(self._parse_image_blocks(filepath, Path(image_dir), ocr))
            return self.image_parser.expand_blocks(blocks)

    def _parse_image_blocks(self, filepath: str, image_dir: Path, ocr: OCR | None) -> list[Block]:
        import fitz

        doc = fitz.open(filepath)
        blocks: list[Block] = []
        for page in doc:
            blocks.extend(self._parse_page_image_blocks(doc, page, image_dir, ocr))
        doc.close()
        return blocks

    def _parse_page_image_blocks(self, doc, page, image_dir: Path, ocr: OCR | None) -> list[Block]:
        blocks: list[Block] = []
        import fitz

        for index, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                image_path = image_dir / f"page_{page.number}_image_{index}.png"
                pix.save(str(image_path))
                blocks.append(ImageBlock(str(image_path), "png"))
            except Exception:
                continue
        return blocks
