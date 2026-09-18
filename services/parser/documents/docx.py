from services.parser.common.base import BlockParser
from services.parser.common.schema import Block, TextBlock
from services.parser.common.table_blocks import table_rows_to_blocks
from services.parser.common.validation import validate_docx_file


class DocxBlockParser(BlockParser):
    def parse(self, filepath: str) -> list[Block]:
        validate_docx_file(filepath)
        return self._read_blocks(filepath)

    def _read_blocks(self, filepath: str) -> list[Block]:
        from docx import Document
        from docx.text.paragraph import Paragraph
        from docx.table import Table

        merged: list[Block] = []
        document = Document(filepath)
        for child in document.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                paragraph = Paragraph(child, document)
                text = paragraph.text.strip()
                if text:
                    merged.append(TextBlock(text, kind=_paragraph_kind(paragraph)))
                continue
            if tag == "tbl":
                table = Table(child, document)
                rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
                merged.extend(table_rows_to_blocks("", rows))
        return merged


def _paragraph_kind(paragraph) -> str:
    from docx.oxml.ns import qn

    properties = [paragraph._p.pPr]
    style = paragraph.style
    while style is not None:
        if style.style_id == "Title" or style.style_id.startswith("Heading"):
            return "heading"
        properties.append(style.element.pPr)
        style = style.base_style
    for prop in properties:
        if prop is None:
            continue
        outline = prop.find(qn("w:outlineLvl"))
        if outline is not None and int(outline.get(qn("w:val"))) < 9:
            return "heading"
        numbering = prop.find(qn("w:numPr"))
        if numbering is not None:
            num_id = numbering.find(qn("w:numId"))
            if num_id is None or num_id.get(qn("w:val")) != "0":
                return "list_item"
            break
    if paragraph.style.style_id.startswith("List"):
        return "list_item"
    return "paragraph"
