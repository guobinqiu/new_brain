import tempfile
from pathlib import Path

from ocr.base import OCR
from parser import mineru
from parser.image import expand_image_blocks
from parser.schema import Block, ImageBlock
from parser.validation import validate_pdf_file
from schema import ParserConfig


def parse_pdf_blocks(filepath: str, parser_config: ParserConfig, ocr: OCR | None = None) -> list[Block]:
    validate_pdf_file(filepath)
    blocks = mineru.parse_document_blocks(filepath, filepath, "pdf", parser_config)
    with tempfile.TemporaryDirectory(prefix="parser_images_") as image_dir:
        blocks.extend(parse_pdf_image_blocks(filepath, Path(image_dir), ocr, parser_config))
        return expand_image_blocks(blocks, parser_config)


def parse_pdf_image_blocks(filepath: str, image_dir: Path, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
    import fitz

    doc = fitz.open(filepath)
    blocks: list[Block] = []
    for page in doc:
        blocks.extend(_parse_page_image_blocks(doc, page, image_dir, ocr, parser_config))
    doc.close()
    return blocks


def _parse_page_image_blocks(doc, page, image_dir: Path, ocr: OCR | None, parser_config: ParserConfig) -> list[Block]:
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
